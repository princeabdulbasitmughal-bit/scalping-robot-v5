"""
wave301_trade_arrival_poisson_clumping_guard.py
-----------------------------------------------
Guard: High-Frequency Trade Arrival Poisson Clumping Heuristic & Hyper-Clump Guard

Monitors trade arrival clustering, Aldous Poisson clumping heuristic, and hyper-cluster burst cascades
(Aldous 1989; Barbour, Holst & Janson 1992; Pacurar 2008; Bauwens & Hautsch 2009):
    Inter-Arrival Duration:       tau_i = max(t_i - t_{i-1}, 1e-4) in seconds
    Clump Distance Threshold:     Delta t_{clump} <= 0.050 seconds (50 ms)
    Contiguous Clump Size:        C = count of trades in an unbroken cluster with tau <= 50 ms
    Rolling Mean Clump Size:      \\bar{C} = (1 / K) * sum_{k=1}^K C_k  (trades / clump)

Under homogeneous Poisson or weakly dependent renewal arrival processes:
    - Arrivals are sparse and separated; clumps are small and rare:
      \\bar{C} in [1.10, 2.50], with rare instances exceeding 3 trades.

During high-frequency algorithmic barrage, predatory sweeping, or panic liquidity exhaustion:
    - Trades bunch into massive contiguous hyper-clumps separated by dead zones:
        1) Poisson Clumping Burst Surge:
           Rolling mean clump size \\bar{C} >= MAX_MEAN_CLUMP_SIZE (default: 5.5 trades/clump)
           over rolling K >= MIN_CLUMPS (default: 8 clumps).
        2) Acute Hyper-Clump Avalanche:
           Instantaneous contiguous clump size C >= ACUTE_HYPER_CLUMP (default: 16 trades).

Trading into an active arrival hyper-clump exposes orders to extreme queue racing,
front-running by predatory algos, and catastrophic adverse selection.

When clumping burst surge or an acute hyper-clump is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade arrival via record_trade_arrival(ts=None) or record_duration(duration_sec, ts=None) or
  direct metrics via record_clump_metrics(mean_clump_size, acute_clump=None, sample_count=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 15 completed clumps.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative durations are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade_arrival(ts=None)                                                                -> None
  record_duration(duration_sec, ts=None)                                                       -> None
  record_clump_size(clump_size, ts=None)                                                       -> None
  record_clump_metrics(mean_clump_size, acute_clump=None, sample_count=None, ts=None)          -> None
  update(duration_sec, ts=None)                                                                -> None   (alias)
  get_clumping_metrics()                                                                       -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave301TradeArrivalPoissonClumpingGuard:
    """
    Guards against trade arrival Poisson hyper-clumping, microsecond cluster bursts, and algorithmic barrages.
    """

    MAX_MEAN_CLUMP_SIZE: float = 5.5
    MIN_CLUMPS: int = 8
    ACUTE_HYPER_CLUMP: int = 16
    CLUMP_DISTANCE_SEC: float = 0.050
    WINDOW_SIZE: int = 15
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_mean_clump_size: float = MAX_MEAN_CLUMP_SIZE,
        min_clumps: int = MIN_CLUMPS,
        acute_hyper_clump: int = ACUTE_HYPER_CLUMP,
        clump_distance_sec: float = CLUMP_DISTANCE_SEC,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_mean_clump_size = float(max_mean_clump_size)
        self.min_clumps = int(min_clumps)
        self.acute_hyper_clump = int(acute_hyper_clump)
        self.clump_distance_sec = float(clump_distance_sec)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._clump_history = collections.deque(maxlen=self.window_size)

        self._last_ts: Optional[float] = None
        self._current_clump_size: int = 1

        self._latest_clump: int = 1
        self._latest_mean_clump: float = 1.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _check_and_trigger_block(
        self,
        mean_clump: float,
        acute_clump: int,
        sample_count: int,
    ) -> bool:
        # 1. Acute hyper-clump avalanche
        if acute_clump >= self.acute_hyper_clump:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_HYPER_CLUMP: clump_size={acute_clump} >= {self.acute_hyper_clump} trades "
                f"(interval <= {self.clump_distance_sec * 1000:.1f}ms)"
            )
            return True

        # 2. Poisson clumping burst surge
        if sample_count >= self.min_clumps and mean_clump >= self.max_mean_clump_size:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"POISSON_CLUMPING_SURGE: mean_clump={mean_clump:.2f} >= {self.max_mean_clump_size:.2f} "
                f"trades/clump (K={sample_count})"
            )
            return True

        return False

    def record_clump_size(self, clump_size: int, ts: Optional[float] = None) -> None:
        """
        Record a completed clump size in trades.
        """
        with self._lock:
            if not self._is_valid_num(clump_size) or clump_size < 1:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_CLUMP_SIZE"
                return

            c = int(clump_size)
            self._latest_clump = c
            self._clump_history.append(c)
            self._sample_count += 1

            mean_c = statistics.mean(self._clump_history) if self._clump_history else float(c)
            self._latest_mean_clump = mean_c

            self._check_and_trigger_block(
                mean_c,
                c,
                len(self._clump_history),
            )

    def record_duration(self, duration_sec: float, ts: Optional[float] = None) -> None:
        """
        Record an observed trade inter-arrival duration and manage ongoing clump.
        """
        with self._lock:
            if not self._is_valid_num(duration_sec) or duration_sec < 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_DURATION_INPUT"
                return

            dur = float(duration_sec)

            if dur <= self.clump_distance_sec:
                self._current_clump_size += 1
                # Check acute hyper-clump during active accumulation
                if self._current_clump_size >= self.acute_hyper_clump:
                    self._check_and_trigger_block(
                        self._latest_mean_clump,
                        self._current_clump_size,
                        len(self._clump_history),
                    )
            else:
                # Close ongoing clump and record it
                completed_clump = self._current_clump_size
                self._current_clump_size = 1
                self.record_clump_size(completed_clump, ts=ts)

    def record_trade_arrival(self, ts: Optional[float] = None) -> None:
        """
        Record a live trade arrival timestamp.
        """
        with self._lock:
            now_ts = float(ts) if (self._is_valid_num(ts) and ts >= 0.0) else time.time()
            if self._last_ts is not None:
                duration = max(now_ts - self._last_ts, 1e-4)
                self.record_duration(duration, ts=now_ts)
            self._last_ts = now_ts

    def record_clump_metrics(
        self,
        mean_clump_size: float,
        acute_clump: Optional[int] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed Poisson clumping metrics.
        """
        with self._lock:
            if not self._is_valid_num(mean_clump_size) or mean_clump_size < 1.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_CLUMP_METRIC"
                return

            mc = float(mean_clump_size)
            ac = int(acute_clump) if (self._is_valid_num(acute_clump) and acute_clump >= 0) else 1
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_clumps

            self._latest_mean_clump = mc
            self._latest_clump = ac
            self._sample_count = cnt

            self._check_and_trigger_block(
                mc,
                ac,
                cnt,
            )

    def update(self, duration_sec: float, ts: Optional[float] = None) -> None:
        """Alias for record_duration."""
        self.record_duration(duration_sec, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_clumping_metrics(self) -> Dict[str, Any]:
        with self._lock:
            if self._clump_history:
                mean_c = statistics.mean(self._clump_history)
                max_c = max(self._clump_history)
            else:
                mean_c = self._latest_mean_clump
                max_c = self._latest_clump

            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "mean_clump_size": float(mean_c),
                "max_clump_size": int(max_c),
                "current_clump_size": int(self._current_clump_size),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_clumping_metrics()

    def reset(self) -> None:
        with self._lock:
            self._clump_history.clear()
            self._last_ts = None
            self._current_clump_size = 1
            self._latest_clump = 1
            self._latest_mean_clump = 1.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
