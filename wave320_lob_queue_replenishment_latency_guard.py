"""
wave320_lob_queue_replenishment_latency_guard.py
------------------------------------------------
Guard: LOB Queue Replenishment Latency & Restock Lag Guard [Wave 320 Landmark]

Monitors post-sweep limit order book queue replenishment latency tau_{restock},
guarding against liquidity desertion, prolonged queue vacuums, and persistent book hollowing
(Biais, Hillion & Spatt 1995; Large 2007; Ponzi et al. 2009; Cont & de Larrard 2013):
    Pre-Sweep Depth:              Q_{pre} = (q_{bid, 1} + q_{ask, 1}) in lots
    Sweep Event:                  Delta Q_{sweep} >= MIN_SWEEP_DEPTH (default: 2.0 lots)
    Restock Threshold:            Q_{target} = 0.50 * Q_{pre}
    Replenishment Latency:        tau_{restock} = t_{restocked} - t_{sweep} in seconds
    Rolling Mean Latency:         \\bar{tau}_{restock} = (1 / N) * sum_{i=1}^N tau_{restock, i}

Under healthy, resilient market making:
    - Depleted queues are replenished swiftly by passive limit orders:
      \\bar{tau}_{restock} <= 1.20 seconds.

Under liquidity withdrawal, phantom liquidity traps, or market maker panic:
    - Depleted queues remain empty and hollow for prolonged intervals:
        1) Replenishment Latency Surge:
           Rolling mean replenishment latency \\bar{tau}_{restock} >= MAX_REPLENISHMENT_SEC (default: 4.50s)
           over rolling N >= MIN_CYCLES (default: 8 replenishment cycles).
        2) Acute Queue Desertion Freeze:
           Following a sweep >= ACUTE_MIN_SWEEP_LOTS (default: 3.0 lots),
           queue fails to restock for duration >= ACUTE_DESERTION_SEC (default: 6.0s).

Trading into a deserted, slow-to-replenish order book guarantees paying exorbitant execution impact,
as successive market orders cascade directly into deeper, wider price levels.

When replenishment latency surge or an acute queue desertion freeze is detected, entry orders
are blocked for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests sweep cycles via record_sweep_cycle(sweep_lots, latency_sec, ts=None) or
  direct metrics via record_latency_metrics(mean_latency_sec, sample_count=None, ts=None).
- Rolling window of WINDOW_SIZE = 20 cycles.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive latencies/sweeps are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_sweep_cycle(sweep_lots, latency_sec, ts=None)                                         -> None
  record_latency_metrics(mean_latency_sec, sample_count=None, ts=None)                         -> None
  update(sweep_lots, latency_sec, ts=None)                                                     -> None   (alias)
  get_replenishment_metrics()                                                                  -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave320LobQueueReplenishmentLatencyGuard:
    """
    Guards against LOB post-sweep replenishment latency surges, queue desertion, and empty book freezes.
    """

    MAX_REPLENISHMENT_SEC: float = 4.50
    MIN_CYCLES: int = 8
    MIN_SWEEP_DEPTH: float = 2.00
    ACUTE_MIN_SWEEP_LOTS: float = 3.00
    ACUTE_DESERTION_SEC: float = 6.00
    WINDOW_SIZE: int = 20
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_replenishment_sec: float = MAX_REPLENISHMENT_SEC,
        min_cycles: int = MIN_CYCLES,
        min_sweep_depth: float = MIN_SWEEP_DEPTH,
        acute_min_sweep_lots: float = ACUTE_MIN_SWEEP_LOTS,
        acute_desertion_sec: float = ACUTE_DESERTION_SEC,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_replenishment_sec = float(max_replenishment_sec)
        self.min_cycles = int(min_cycles)
        self.min_sweep_depth = float(min_sweep_depth)
        self.acute_min_sweep_lots = float(acute_min_sweep_lots)
        self.acute_desertion_sec = float(acute_desertion_sec)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._latencies = collections.deque(maxlen=self.window_size)

        self._latest_latency: float = 0.50
        self._latest_mean_latency: float = 0.50
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _check_and_trigger_block(
        self,
        latency: float,
        mean_latency: float,
        sweep_lots: float,
        count: int,
    ) -> bool:
        # 1. Acute queue desertion freeze
        if sweep_lots >= self.acute_min_sweep_lots and latency >= self.acute_desertion_sec:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_QUEUE_DESERTION_FREEZE: latency={latency:.2f} >= {self.acute_desertion_sec:.2f}s "
                f"after sweep={sweep_lots:.2f} >= {self.acute_min_sweep_lots:.2f} lots"
            )
            return True

        # 2. Replenishment latency surge
        if count >= self.min_cycles and mean_latency >= self.max_replenishment_sec:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"REPLENISHMENT_LATENCY_SURGE: mean_latency={mean_latency:.2f} >= {self.max_replenishment_sec:.2f}s "
                f"over N={count} cycles"
            )
            return True

        return False

    def record_sweep_cycle(self, sweep_lots: float, latency_sec: float, ts: Optional[float] = None) -> None:
        """
        Record a completed sweep replenishment cycle with sweep volume and latency in seconds.
        """
        with self._lock:
            if not self._is_valid_num(sweep_lots) or not self._is_valid_num(latency_sec) or sweep_lots <= 0.0 or latency_sec < 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_SWEEP_CYCLE_INPUT"
                return

            swp = float(sweep_lots)
            lat = float(latency_sec)

            self._latencies.append(lat)
            self._sample_count += 1

            mean_lat = statistics.fmean(self._latencies)
            self._latest_latency = lat
            self._latest_mean_latency = mean_lat

            self._check_and_trigger_block(
                lat,
                mean_lat,
                swp,
                len(self._latencies),
            )

    def record_latency_metrics(
        self,
        mean_latency_sec: float,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed replenishment latency metrics.
        """
        with self._lock:
            if not self._is_valid_num(mean_latency_sec) or mean_latency_sec < 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_LATENCY_METRIC"
                return

            lat = float(mean_latency_sec)
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_cycles

            self._latest_latency = lat
            self._latest_mean_latency = lat
            self._sample_count = cnt

            self._check_and_trigger_block(
                lat,
                lat,
                self.acute_min_sweep_lots + 1.0 if lat >= 7.0 else 1.0,
                cnt,
            )

    def update(self, sweep_lots: float, latency_sec: float, ts: Optional[float] = None) -> None:
        """Alias for record_sweep_cycle."""
        self.record_sweep_cycle(sweep_lots, latency_sec, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_replenishment_metrics(self) -> Dict[str, Any]:
        with self._lock:
            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "latest_latency_sec": float(self._latest_latency),
                "mean_latency_sec": float(self._latest_mean_latency),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_replenishment_metrics()

    def reset(self) -> None:
        with self._lock:
            self._latencies.clear()
            self._latest_latency = 0.50
            self._latest_mean_latency = 0.50
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
