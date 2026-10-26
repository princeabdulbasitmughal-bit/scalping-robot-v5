"""
Wave 399 -- Limit Order Fill Hazard Guard
=========================================
Monitors the empirical Poisson hazard intensity of toxic adverse limit order fills.
When resting passive orders are filled predominantly before immediate adverse price runs
with collapsing survival duration, it indicates high toxic flow and predatory sweeps.

Methodology
-----------
* Observes passive execution events:
    - `survival_sec`: resting duration of the limit order before fill.
    - `is_adverse`: boolean flag indicating whether the fill moved adversely immediately post-trade.
* Validates positive numeric duration and boolean adverse flag.
* Maintains a rolling window of recent execution events of size `window_size`.
* Calculates adverse selection ratio: P_adv = sum(is_adverse) / N.
* Calculates mean survival time: T_mean = mean(survival_sec).
* Evaluates adverse hazard rate:
    hazard_rate = P_adv / max(T_mean, 0.001)
* If hazard_rate >= `hazard_threshold`, blocks trading for `cooldown_seconds`.

Blocking reasons
----------------
TOXIC_FILL_HAZARD      -- empirical adverse fill hazard rate exceeds risk threshold
INPUT_VALIDATION_ERROR -- negative duration, non-boolean is_adverse, or invalid timestamp

Public API (standardised)
-------------------------
update(survival_sec, is_adverse, timestamp) -> None
is_blocked(current_time=None)               -> bool
is_entry_blocked(bid, ask, ts)              -> bool
reset()                                     -> None
last_reason                                 -> str
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave399LimitOrderFillHazardGuard"]

_REASON_HAZARD = "TOXIC_FILL_HAZARD"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave399LimitOrderFillHazardGuard:
    """Empirical limit order fill adverse hazard rate guard."""

    def __init__(
        self,
        window_size: int = 15,
        hazard_threshold: float = 2.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if window_size < 4 or hazard_threshold <= 0.0 or cooldown_seconds <= 0.0:
            raise ValueError("Invalid parameters for Wave399LimitOrderFillHazardGuard")
        self._window_size = int(window_size)
        self._hazard_threshold = float(hazard_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._events: deque[tuple[float, int]] = deque(maxlen=self._window_size)
        self._blocked_until = 0.0
        self._last_reason = ""

    def update(self, survival_sec: float, is_adverse: bool, timestamp: float) -> None:
        with self._lock:
            for val in (survival_sec, timestamp):
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    self._block(_REASON_VAL)
                    return

            if not isinstance(is_adverse, bool) or survival_sec < 0.0:
                self._block(_REASON_VAL)
                return

            self._events.append((float(survival_sec), 1 if is_adverse else 0))

            if len(self._events) >= self._window_size:
                n = len(self._events)
                total_adverse = sum(adv for _, adv in self._events)
                p_adv = total_adverse / n
                mean_t = sum(t for t, _ in self._events) / n

                hazard_rate = p_adv / max(mean_t, 0.001)
                if hazard_rate >= self._hazard_threshold:
                    self._block(_REASON_HAZARD)

    def _block(self, reason: str) -> None:
        self._blocked_until = time.monotonic() + self._cooldown_seconds
        self._last_reason = reason

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            t = time.monotonic() if current_time is None else current_time
            return t < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: float) -> bool:
        return self.is_blocked(ts)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
