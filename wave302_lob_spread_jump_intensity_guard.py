"""
wave302_lob_spread_jump_intensity_guard.py
------------------------------------------
Guard: LOB Bid-Ask Spread Jump Intensity & Poisson Discontinuity Guard

Monitors limit order book bid-ask spread jump arrivals, Poisson jump intensity, and acute spread widening shocks
(Merton 1976; Johannes 2004; Cont & Tankov 2004; Ait-Sahalia & Jacod 2009, 2012):
    Spread at Tick t:            S_t in bps
    Spread Increment:            Delta S_t = S_t - S_{t-1} in bps
    Jump Event:                  Delta S_t >= JUMP_THRESHOLD_BPS (default: 2.20 bps)
    Sliding Window:              W = 30.0 seconds
    Spread Jump Intensity:       lambda_J = N_{jump} / W  (jumps / sec)
    Acute Double-Jump:           2 spread jumps >= 3.00 bps within Delta t <= 2.0 seconds

Under continuous, liquid quoting conditions:
    - Spread changes are continuous, gradual, and Gaussian-like:
      lambda_J <= 0.067 jumps/sec (<= 2 jumps in 30s).

During sudden liquidity withdrawal, quote flickering shocks, or news breaks:
    - Order book spread suffers frequent discontinuous jump explosions:
        1) Spread Jump Intensity Surge:
           Jump count N_{jump} >= MAX_JUMP_COUNT (default: 5 jumps in 30.0s, lambda_J >= 0.167/s).
        2) Acute Spread Double-Jump:
           2 consecutive spread jumps >= ACUTE_JUMP_SIZE_BPS (default: 3.00 bps)
           within Delta t <= ACUTE_DOUBLE_JUMP_WINDOW_SEC (default: 2.0s).

Entering orders during active spread jump clustering exposes executions to severe adverse fills,
instant execution price gaps, and catastrophic slippage.

When spread jump intensity surge or an acute double-jump is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests spread via record_spread(spread_bps, ts=None) or
  direct metrics via record_jump_metrics(jump_count, jump_intensity=None, ts=None).
- Maintains sliding window timestamps of detected jumps.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative spreads are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_spread(spread_bps, ts=None)                                                           -> None
  record_jump_metrics(jump_count, jump_intensity=None, ts=None)                                -> None
  update(spread_bps, ts=None)                                                                  -> None   (alias)
  get_jump_metrics()                                                                           -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave302LobSpreadJumpIntensityGuard:
    """
    Guards against high-frequency bid-ask spread jump clustering, Poisson discontinuities, and flash spread widening.
    """

    JUMP_THRESHOLD_BPS: float = 2.20
    MAX_JUMP_COUNT: int = 5
    WINDOW_SEC: float = 30.0
    ACUTE_JUMP_SIZE_BPS: float = 3.00
    ACUTE_DOUBLE_JUMP_WINDOW_SEC: float = 2.0
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        jump_threshold_bps: float = JUMP_THRESHOLD_BPS,
        max_jump_count: int = MAX_JUMP_COUNT,
        window_sec: float = WINDOW_SEC,
        acute_jump_size_bps: float = ACUTE_JUMP_SIZE_BPS,
        acute_double_jump_window_sec: float = ACUTE_DOUBLE_JUMP_WINDOW_SEC,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.jump_threshold_bps = float(jump_threshold_bps)
        self.max_jump_count = int(max_jump_count)
        self.window_sec = float(window_sec)
        self.acute_jump_size_bps = float(acute_jump_size_bps)
        self.acute_double_jump_window_sec = float(acute_double_jump_window_sec)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._jump_timestamps = collections.deque()
        self._acute_jumps = collections.deque()

        self._last_spread: Optional[float] = None
        self._last_ts: Optional[float] = None

        self._latest_spread: float = 0.0
        self._latest_jump_count: int = 0
        self._latest_intensity: float = 0.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _purge_old_jumps(self, now_ts: float) -> None:
        cutoff = now_ts - self.window_sec
        while self._jump_timestamps and self._jump_timestamps[0] < cutoff:
            self._jump_timestamps.popleft()

        acute_cutoff = now_ts - self.acute_double_jump_window_sec
        while self._acute_jumps and self._acute_jumps[0] < acute_cutoff:
            self._acute_jumps.popleft()

    def _check_and_trigger_block(self, jump_cnt: int, acute_cnt: int) -> bool:
        # 1. Acute spread double-jump
        if acute_cnt >= 2:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_SPREAD_DOUBLE_JUMP: 2 jumps >= {self.acute_jump_size_bps:.2f}bps "
                f"in dt <= {self.acute_double_jump_window_sec:.2f}s"
            )
            return True

        # 2. Spread jump intensity surge
        if jump_cnt >= self.max_jump_count:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"SPREAD_JUMP_INTENSITY_SURGE: jumps={jump_cnt} >= {self.max_jump_count} in {self.window_sec:.1f}s"
            )
            return True

        return False

    def record_spread(self, spread_bps: float, ts: Optional[float] = None) -> None:
        """
        Record instantaneous bid-ask spread in bps and evaluate jump occurrence.
        """
        with self._lock:
            if not self._is_valid_num(spread_bps) or spread_bps < 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_SPREAD_INPUT"
                return

            now_ts = float(ts) if (self._is_valid_num(ts) and ts >= 0.0) else time.time()
            spr = float(spread_bps)
            self._latest_spread = spr
            self._sample_count += 1

            if self._last_spread is not None:
                delta_s = spr - self._last_spread
                if delta_s >= self.jump_threshold_bps:
                    self._jump_timestamps.append(now_ts)

                if delta_s >= self.acute_jump_size_bps:
                    self._acute_jumps.append(now_ts)

            self._purge_old_jumps(now_ts)
            jump_cnt = len(self._jump_timestamps)
            acute_cnt = len(self._acute_jumps)
            intensity = jump_cnt / self.window_sec

            self._latest_jump_count = jump_cnt
            self._latest_intensity = intensity
            self._last_spread = spr
            self._last_ts = now_ts

            self._check_and_trigger_block(jump_cnt, acute_cnt)

    def record_jump_metrics(
        self,
        jump_count: int,
        jump_intensity: Optional[float] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed jump metrics.
        """
        with self._lock:
            if not self._is_valid_num(jump_count) or jump_count < 0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_JUMP_METRIC"
                return

            cnt = int(jump_count)
            inten = float(jump_intensity) if (self._is_valid_num(jump_intensity) and jump_intensity >= 0.0) else cnt / self.window_sec

            self._latest_jump_count = cnt
            self._latest_intensity = inten
            self._sample_count = cnt

            self._check_and_trigger_block(cnt, 2 if cnt >= 8 else 0)

    def update(self, spread_bps: float, ts: Optional[float] = None) -> None:
        """Alias for record_spread."""
        self.record_spread(spread_bps, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_jump_metrics(self) -> Dict[str, Any]:
        with self._lock:
            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "jump_count": int(self._latest_jump_count),
                "jump_intensity": float(self._latest_intensity),
                "latest_spread_bps": float(self._latest_spread),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_jump_metrics()

    def reset(self) -> None:
        with self._lock:
            self._jump_timestamps.clear()
            self._acute_jumps.clear()
            self._last_spread = None
            self._last_ts = None
            self._latest_spread = 0.0
            self._latest_jump_count = 0
            self._latest_intensity = 0.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
