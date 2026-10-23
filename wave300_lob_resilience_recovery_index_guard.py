"""
wave300_lob_resilience_recovery_index_guard.py
----------------------------------------------
Guard: LOB Post-Trade Queue Resilience & Depth Recovery Index Guard [Wave 300 Milestone]

Monitors post-sweep limit order book resilience, liquidity restitution index, and queue replenishment half-life
(Biais, Hillion & Spatt 1995; Large 2007; Ponzi, Lillo & Mantegna 2009; Bouchaud, Farmer & Lillo 2009):
    Sweep Consumption:           Delta Q_{sweep} = Q_{pre-sweep} - Q_{post-sweep} in lots
    Depth Restitution:           Q_{recovered} = Q_{curr} - Q_{post-sweep} in lots
    Resilience Recovery Ratio:   R_{resilience} = max(0.0, Q_{recovered}) / max(Delta Q_{sweep}, 0.50) in [0.0, 1.0+]
    Unrecovered Duration:        Delta t_{freeze} = elapsed seconds since sweep while R_{resilience} <= 0.10

Under healthy, active market making competition:
    - Depleted depth is swiftly restocked within tau <= 1.0s by competitive quote posting:
      R_{resilience} >= 0.70 to 1.00+.
    - Market makers step in to capture the bid-ask spread, eliminating hollow gaps.

During liquidity provider flight, inventory exhaustion, or adverse selection panic:
    - Order book depth remains permanently depleted or recovers at a sluggish, impaired rate:
        1) Impaired Book Resilience Persistence:
           Rolling mean resilience ratio \\bar{R}_{resilience} <= MIN_RESILIENCE_RATIO (default: 0.25)
           over rolling N >= MIN_CYCLES (default: 8 sweep cycles).
        2) Acute Post-Sweep Hollow Freeze:
           Recovery ratio R_{resilience} <= ACUTE_FREEZE_RATIO (default: 0.10)
           persisting for Delta t >= ACUTE_FREEZE_DURATION_SEC (default: 3.0s) after sweep Delta Q >= 5.0 lots.

Trading into unreplenished, non-resilient order books exposes execution to severe liquidity premia,
depth vacuum gaps, and extreme price-walking slippage.

When impaired resilience or an acute hollow freeze is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests sweep cycle via record_sweep_recovery(sweep_depth, recovered_depth, duration_sec=None, ts=None) or
  direct metrics via record_resilience_metrics(recovery_ratio, duration_sec=None, sweep_depth=None, sample_count=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 15 sweep cycles.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative depths are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_sweep_recovery(sweep_depth, recovered_depth, duration_sec=None, ts=None)              -> None
  record_resilience_metrics(recovery_ratio, duration_sec=None, sweep_depth=None)               -> None
  update(recovery_ratio, ts=None)                                                              -> None   (alias)
  get_resilience_metrics()                                                                     -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave300LobResilienceRecoveryIndexGuard:
    """
    Guards against LOB post-sweep depth replenishment failure, impaired resilience, and hollow book gaps.
    """

    MIN_RESILIENCE_RATIO: float = 0.25
    MIN_CYCLES: int = 8
    ACUTE_FREEZE_RATIO: float = 0.10
    ACUTE_FREEZE_DURATION_SEC: float = 3.0
    ACUTE_MIN_SWEEP_DEPTH: float = 5.0
    WINDOW_SIZE: int = 15
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        min_resilience_ratio: float = MIN_RESILIENCE_RATIO,
        min_cycles: int = MIN_CYCLES,
        acute_freeze_ratio: float = ACUTE_FREEZE_RATIO,
        acute_freeze_duration_sec: float = ACUTE_FREEZE_DURATION_SEC,
        acute_min_sweep_depth: float = ACUTE_MIN_SWEEP_DEPTH,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.min_resilience_ratio = float(min_resilience_ratio)
        self.min_cycles = int(min_cycles)
        self.acute_freeze_ratio = float(acute_freeze_ratio)
        self.acute_freeze_duration_sec = float(acute_freeze_duration_sec)
        self.acute_min_sweep_depth = float(acute_min_sweep_depth)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._ratio_history = collections.deque(maxlen=self.window_size)

        self._latest_ratio: float = 1.0
        self._latest_duration: float = 0.0
        self._latest_sweep: float = 0.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _check_and_trigger_block(
        self,
        mean_ratio: float,
        acute_ratio: float,
        freeze_duration: float,
        sweep_depth: float,
        sample_count: int,
    ) -> bool:
        # 1. Acute post-sweep hollow freeze
        if (
            acute_ratio <= self.acute_freeze_ratio
            and freeze_duration >= self.acute_freeze_duration_sec
            and sweep_depth >= self.acute_min_sweep_depth
        ):
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_HOLLOW_FREEZE: ratio={acute_ratio:.2f} <= {self.acute_freeze_ratio:.2f}, "
                f"duration={freeze_duration:.2f}s >= {self.acute_freeze_duration_sec:.2f}s (sweep={sweep_depth:.2f} lots)"
            )
            return True

        # 2. Impaired book resilience persistence
        if sample_count >= self.min_cycles and mean_ratio <= self.min_resilience_ratio:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"IMPAIRED_BOOK_RESILIENCE: mean_ratio={mean_ratio:.2f} <= {self.min_resilience_ratio:.2f} (N={sample_count})"
            )
            return True

        return False

    def record_sweep_recovery(
        self,
        sweep_depth: float,
        recovered_depth: float,
        duration_sec: Optional[float] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Record post-sweep replenishment cycle: depth consumed by sweep and depth replenished.
        """
        with self._lock:
            if (
                not self._is_valid_num(sweep_depth)
                or not self._is_valid_num(recovered_depth)
                or sweep_depth <= 0.0
                or recovered_depth < 0.0
            ):
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_SWEEP_DEPTH"
                return

            swp = float(sweep_depth)
            rec = float(recovered_depth)
            dur = float(duration_sec) if (self._is_valid_num(duration_sec) and duration_sec >= 0.0) else 1.0

            ratio = max(0.0, rec) / max(swp, 0.50)

            self._latest_ratio = ratio
            self._latest_duration = dur
            self._latest_sweep = swp
            self._ratio_history.append(ratio)
            self._sample_count += 1

            mean_r = statistics.mean(self._ratio_history) if self._ratio_history else ratio

            self._check_and_trigger_block(
                mean_r,
                ratio,
                dur,
                swp,
                self._sample_count,
            )

    def record_resilience_metrics(
        self,
        recovery_ratio: float,
        duration_sec: Optional[float] = None,
        sweep_depth: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed resilience recovery metrics.
        """
        with self._lock:
            if not self._is_valid_num(recovery_ratio) or recovery_ratio < 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_RESILIENCE_METRIC"
                return

            r = float(recovery_ratio)
            dur = float(duration_sec) if (self._is_valid_num(duration_sec) and duration_sec >= 0.0) else 1.0
            swp = float(sweep_depth) if (self._is_valid_num(sweep_depth) and sweep_depth >= 0.0) else self.acute_min_sweep_depth
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_cycles

            self._latest_ratio = r
            self._latest_duration = dur
            self._latest_sweep = swp
            self._sample_count = cnt
            self._ratio_history.append(r)

            mean_r = statistics.mean(self._ratio_history) if self._ratio_history else r

            self._check_and_trigger_block(
                mean_r,
                r,
                dur,
                swp,
                cnt,
            )

    def update(self, recovery_ratio: float, ts: Optional[float] = None) -> None:
        """Alias for record_resilience_metrics."""
        self.record_resilience_metrics(recovery_ratio, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_resilience_metrics(self) -> Dict[str, Any]:
        with self._lock:
            if self._ratio_history:
                mean_r = statistics.mean(self._ratio_history)
            else:
                mean_r = self._latest_ratio

            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "mean_resilience_ratio": float(mean_r),
                "latest_resilience_ratio": float(self._latest_ratio),
                "latest_recovery_duration_sec": float(self._latest_duration),
                "latest_sweep_depth_lots": float(self._latest_sweep),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_resilience_metrics()

    def reset(self) -> None:
        with self._lock:
            self._ratio_history.clear()
            self._latest_ratio = 1.0
            self._latest_duration = 0.0
            self._latest_sweep = 0.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
