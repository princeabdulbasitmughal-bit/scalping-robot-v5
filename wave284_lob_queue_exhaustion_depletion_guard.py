"""
wave284_lob_queue_exhaustion_depletion_guard.py
-----------------------------------------------
Guard: LOB Inside-Queue Cumulative Exhaustion & Depth Depletion Rate Guard

Monitors limit order book touch queue consumption, cumulative depth depletion ratio, and evaporation velocity
(Biais, Hillion & Spatt 1995; Parlour 1998; Foucault, Kadan & Kandel 2005; Hautsch & Huang 2012):
    Queue Depth at Touch:        Q_{curr} = min(Q_{bid}, Q_{ask}) in lots
    Depth Baseline Capacity:     Q_{base} = rolling baseline capacity over window
    Cumulative Depletion Ratio:  R_{deplete} = max(0.0, Q_{base} - Q_{curr}) / max(Q_{base}, 0.50) in [0.0, 1.0]
    Depletion Velocity:          v_{deplete} = (Q_{prev} - Q_{curr}) / max(Delta t, 0.02)  (lots / sec)

Under equilibrium market conditions:
    - Order book queues are continually replenished as executions occur. Depletion ratio remains low
      (R_{deplete} <= 0.40) and depletion velocities are moderate (v_{deplete} <= 3.50 lots/s).

During aggressive market sweeping, multi-venue arbitrage bursts, or dealer quote cancellations:
    - Inside queue depth evaporates without replenishment, leaving a hollow Level-1 shell:
        1) Persistent Cumulative Queue Depletion:
           Rolling mean depletion ratio \\bar{R}_{deplete} >= MAX_DEPLETION_RATIO (default: 0.80)
           with spread S_{bps} >= MIN_SPREAD_BPS (default: 2.00 bps) over N >= MIN_SAMPLES (8 observations).
        2) Acute Queue Evaporation:
           Depletion velocity v_{deplete} >= ACUTE_DEPLETION_VELOCITY (default: 12.0 lots/sec)
           with remaining touch queue Q_{curr} <= ACUTE_REMAINING_QUEUE (default: 0.50 lots).

Trading into an exhausted, depleting order queue guarantees fill slippage across multiple ticks,
widespread quote widening, and severe adverse execution.

When queue exhaustion or acute evaporation is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests queue depth via record_queue_state(bid_depth, ask_depth, spread_bps=None, ts=None) or
  direct metrics via record_depletion_metrics(depletion_ratio, depletion_vel=None, spread_bps=None, sample_count=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 15 observations.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative depths are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_queue_state(bid_depth, ask_depth, spread_bps=None, ts=None)                           -> None
  record_depletion_metrics(depletion_ratio, depletion_vel=None, spread_bps=None)               -> None
  update(bid_depth, ask_depth, spread_bps=None, ts=None)                                       -> None   (alias)
  get_depletion_metrics()                                                                      -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, Optional


class Wave284LobQueueExhaustionDepletionGuard:
    """
    Guards against rapid Level-1 queue exhaustion, depth evaporation, and impending liquidity void gaps.
    """

    MAX_DEPLETION_RATIO: float = 0.80
    MIN_SPREAD_BPS: float = 2.00
    MIN_SAMPLES: int = 8
    ACUTE_DEPLETION_VELOCITY: float = 12.0
    ACUTE_REMAINING_QUEUE: float = 0.50
    WINDOW_SIZE: int = 15
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_depletion_ratio: float = MAX_DEPLETION_RATIO,
        min_spread_bps: float = MIN_SPREAD_BPS,
        min_samples: int = MIN_SAMPLES,
        acute_depletion_velocity: float = ACUTE_DEPLETION_VELOCITY,
        acute_remaining_queue: float = ACUTE_REMAINING_QUEUE,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_depletion_ratio = float(max_depletion_ratio)
        self.min_spread_bps = float(min_spread_bps)
        self.min_samples = int(min_samples)
        self.acute_depletion_velocity = float(acute_depletion_velocity)
        self.acute_remaining_queue = float(acute_remaining_queue)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._depletion_history = collections.deque(maxlen=self.window_size)
        self._spread_history = collections.deque(maxlen=self.window_size)
        self._depth_history = collections.deque(maxlen=self.window_size)

        self._last_depth: Optional[float] = None
        self._last_ts: Optional[float] = None

        self._latest_depletion_ratio: float = 0.0
        self._latest_velocity: float = 0.0
        self._latest_spread_bps: float = 0.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _check_and_trigger_block(
        self,
        mean_depletion: float,
        depletion_vel: float,
        remaining_depth: float,
        mean_spread: float,
        sample_count: int,
    ) -> bool:
        # 1. Acute queue evaporation
        if depletion_vel >= self.acute_depletion_velocity and remaining_depth <= self.acute_remaining_queue:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_QUEUE_EVAPORATION: vel={depletion_vel:.2f} >= {self.acute_depletion_velocity:.2f} lots/s, "
                f"remaining={remaining_depth:.2f} <= {self.acute_remaining_queue:.2f} lots"
            )
            return True

        # 2. Persistent cumulative queue depletion
        if (
            sample_count >= self.min_samples
            and mean_depletion >= self.max_depletion_ratio
            and mean_spread >= self.min_spread_bps
        ):
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"PERSISTENT_QUEUE_DEPLETION: mean_ratio={mean_depletion:.2f} >= {self.max_depletion_ratio:.2f}, "
                f"spread={mean_spread:.2f}bps >= {self.min_spread_bps:.2f}bps (N={sample_count})"
            )
            return True

        return False

    def record_queue_state(
        self,
        bid_depth: float,
        ask_depth: float,
        spread_bps: Optional[float] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Record instantaneous Level-1 bid and ask depths and spread.
        """
        with self._lock:
            if (
                not self._is_valid_num(bid_depth)
                or not self._is_valid_num(ask_depth)
                or bid_depth < 0.0
                or ask_depth < 0.0
            ):
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_QUEUE_STATE"
                return

            now_ts = float(ts) if (self._is_valid_num(ts) and ts >= 0.0) else time.time()
            spr = float(spread_bps) if (self._is_valid_num(spread_bps) and spread_bps >= 0.0) else 1.50

            curr_depth = min(float(bid_depth), float(ask_depth))
            self._depth_history.append(curr_depth)
            self._spread_history.append(spr)
            self._sample_count += 1

            baseline_depth = max(self._depth_history) if self._depth_history else curr_depth
            depletion_ratio = max(0.0, baseline_depth - curr_depth) / max(baseline_depth, 0.50)
            self._depletion_history.append(depletion_ratio)
            self._latest_depletion_ratio = depletion_ratio
            self._latest_spread_bps = spr

            velocity = 0.0
            if self._last_ts is not None and self._last_depth is not None:
                delta_t = max(now_ts - self._last_ts, 0.02)
                delta_depth = self._last_depth - curr_depth
                velocity = max(0.0, delta_depth / delta_t)

            self._latest_velocity = velocity
            self._last_depth = curr_depth
            self._last_ts = now_ts

            mean_dep = statistics.mean(self._depletion_history) if self._depletion_history else depletion_ratio
            mean_spr = statistics.mean(self._spread_history) if self._spread_history else spr

            self._check_and_trigger_block(
                mean_dep,
                velocity,
                curr_depth,
                mean_spr,
                self._sample_count,
            )

    def record_depletion_metrics(
        self,
        depletion_ratio: float,
        depletion_vel: Optional[float] = None,
        spread_bps: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed queue depletion metrics.
        """
        with self._lock:
            if not self._is_valid_num(depletion_ratio) or depletion_ratio < 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_DEPLETION_METRIC"
                return

            ratio = float(depletion_ratio)
            vel = float(depletion_vel) if (self._is_valid_num(depletion_vel) and depletion_vel >= 0.0) else 0.0
            spr = float(spread_bps) if (self._is_valid_num(spread_bps) and spread_bps >= 0.0) else self.min_spread_bps + 1.0
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_samples

            self._latest_depletion_ratio = ratio
            self._latest_velocity = vel
            self._latest_spread_bps = spr
            self._sample_count = cnt
            self._depletion_history.append(ratio)
            self._spread_history.append(spr)

            mean_dep = statistics.mean(self._depletion_history) if self._depletion_history else ratio
            mean_spr = statistics.mean(self._spread_history) if self._spread_history else spr

            self._check_and_trigger_block(
                mean_dep,
                vel,
                0.20 if vel >= self.acute_depletion_velocity else 5.0,
                mean_spr,
                cnt,
            )

    def update(
        self,
        bid_depth: float,
        ask_depth: float,
        spread_bps: Optional[float] = None,
        ts: Optional[float] = None,
    ) -> None:
        """Alias for record_queue_state."""
        self.record_queue_state(bid_depth, ask_depth, spread_bps=spread_bps, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_depletion_metrics(self) -> Dict[str, Any]:
        with self._lock:
            if self._depletion_history:
                mean_dep = statistics.mean(self._depletion_history)
                max_dep = max(self._depletion_history)
            else:
                mean_dep = self._latest_depletion_ratio
                max_dep = self._latest_depletion_ratio

            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "mean_depletion_ratio": float(mean_dep),
                "max_depletion_ratio": float(max_dep),
                "latest_depletion_velocity": float(self._latest_velocity),
                "latest_spread_bps": float(self._latest_spread_bps),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_depletion_metrics()

    def reset(self) -> None:
        with self._lock:
            self._depletion_history.clear()
            self._spread_history.clear()
            self._depth_history.clear()
            self._last_depth = None
            self._last_ts = None
            self._latest_depletion_ratio = 0.0
            self._latest_velocity = 0.0
            self._latest_spread_bps = 0.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
