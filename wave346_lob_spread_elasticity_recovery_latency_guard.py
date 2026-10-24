"""
Wave 346 -- LOB Spread Elasticity Recovery Latency Guard
=========================================================
Monitors the elasticity and recovery latency of the bid-ask spread following
an exogenous spread expansion shock:
    Spread S(t) = Ask(t) - Bid(t)
    Spread Shock: S(t) >= expansion_ratio * S_baseline

When a spread shock occurs, healthy market makers rapidly replenish the inside quotes
(high elasticity, sub-100ms recovery). If the spread fails to contract back to baseline
within max_recovery_latency_sec, liquidity providers have vacated the orderbook due to
severe informed adverse selection risk.
The guard detects slow spread recovery latency and locks out new market orders.

Blocking reasons
----------------
SPREAD_ELASTICITY_RECOVERY_TIMEOUT  -- Spread remains expanded beyond max_recovery_latency_sec
CROSSED_QUOTES_ERROR                -- bid >= ask
INPUT_VALIDATION_ERROR              -- Non-positive, boolean or non-numeric inputs

Public API
----------
update(bid, ask, timestamp)    -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave346LOBSpreadElasticityRecoveryLatencyGuard"]

_REASON_TIMEOUT = "SPREAD_ELASTICITY_RECOVERY_TIMEOUT"
_REASON_CROSSED = "CROSSED_QUOTES_ERROR"
_REASON_VAL     = "INPUT_VALIDATION_ERROR"


class Wave346LOBSpreadElasticityRecoveryLatencyGuard:
    """Monitors bid-ask spread resilience and recovery latency following expansion shocks."""

    def __init__(
        self,
        baseline_window: int = 15,
        expansion_ratio: float = 2.0,
        max_recovery_latency_sec: float = 0.50,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if baseline_window < 5 or expansion_ratio <= 1.0 or max_recovery_latency_sec <= 0:
            raise ValueError("Invalid parameters for Spread Elasticity Recovery Latency Guard.")
        self._baseline_window = int(baseline_window)
        self._expansion_ratio = float(expansion_ratio)
        self._max_latency = float(max_recovery_latency_sec)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._baseline_spreads: deque = deque(maxlen=baseline_window)
        self._shock_start_ts: Optional[float] = None
        self._blocked_until = 0.0
        self._blocked_until_sim = 0.0
        self._last_reason = ""

    def update(self, bid: float, ask: float, timestamp: float) -> None:
        with self._lock:
            # Type and bool validations
            if isinstance(bid, bool) or isinstance(ask, bool) or isinstance(timestamp, bool):
                self._block(timestamp, _REASON_VAL)
                return
            if not (isinstance(bid, (int, float)) and isinstance(ask, (int, float)) and isinstance(timestamp, (int, float))):
                self._block(timestamp, _REASON_VAL)
                return

            b = float(bid)
            a = float(ask)
            ts = float(timestamp)

            if b <= 0 or a <= 0:
                self._block(ts, _REASON_VAL)
                return

            if b >= a:
                self._block(ts, _REASON_CROSSED)
                return

            spread = a - b

            # Check if we have enough baseline history
            if len(self._baseline_spreads) >= self._baseline_window:
                avg_baseline = sum(self._baseline_spreads) / len(self._baseline_spreads)
                shock_threshold = avg_baseline * self._expansion_ratio

                if spread >= shock_threshold:
                    if self._shock_start_ts is None:
                        # Shock started at this timestamp
                        self._shock_start_ts = ts
                    else:
                        # Spread is still expanded; check duration
                        elapsed = ts - self._shock_start_ts
                        if elapsed >= self._max_latency:
                            self._block(ts, _REASON_TIMEOUT)
                else:
                    # Spread recovered below shock threshold!
                    self._shock_start_ts = None
                    self._baseline_spreads.append(spread)
            else:
                self._baseline_spreads.append(spread)

    def _block(self, timestamp: float, reason: str) -> None:
        now_mono = time.monotonic()
        self._blocked_until = now_mono + self._cooldown
        if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool) and timestamp > 0:
            self._blocked_until_sim = timestamp + self._cooldown
        else:
            self._blocked_until_sim = self._blocked_until
        self._last_reason = reason

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            if current_time is not None:
                return current_time < self._blocked_until_sim
            return time.monotonic() < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: float) -> bool:
        return self.is_blocked(ts)

    def reset(self) -> None:
        with self._lock:
            self._baseline_spreads.clear()
            self._shock_start_ts = None
            self._blocked_until = 0.0
            self._blocked_until_sim = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
