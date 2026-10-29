"""
Wave 421 -- Trade Sign Run-Length Persistence Guard
===================================================
Tracks consecutive identical trade sign sequences (e.g., continuous buy fills +++...+
or continuous sell fills ---...-). Under the independent Bernoulli flow null hypothesis,
the probability of a run of length k decays exponentially: P(L >= k) = 2^{-(k-1)}.
When a run length k >= `max_run_length` or average run length spikes, predatory execution
algorithms (such as hidden iceberg sweeps or momentum ignition) are actively consuming
book depth unilaterally, causing guaranteed adverse fills.

Methodology
-----------
* Observes incoming trade signs: is_buy (True for buy, False for sell) and timestamp.
* Tracks current consecutive run length k_{run} of identical trade direction.
* Maintains a rolling window of recent run lengths.
* If k_{run} >= `max_run_length`, blocks with PERSISTENT_TRADE_SIGN_RUN.
* If average run length >= `max_avg_run_length`, blocks with UNILATERAL_ORDER_MOMENTUM_IGNITION.

Blocking reasons
----------------
PERSISTENT_TRADE_SIGN_RUN                -- consecutive trade signs exceeded geometric null limit
UNILATERAL_ORDER_MOMENTUM_IGNITION       -- persistent one-sided directional order splitting
INPUT_VALIDATION_ERROR                   -- non-boolean trade sign, invalid timestamp, or non-monotonic ts

Public API (standardised)
-------------------------
update(is_buy, timestamp)      -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
current_run_length             -> int
average_run_length             -> float
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave421TradeSignRunLengthGuard"]

_REASON_RUN = "PERSISTENT_TRADE_SIGN_RUN"
_REASON_IGNITION = "UNILATERAL_ORDER_MOMENTUM_IGNITION"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave421TradeSignRunLengthGuard:
    """Trade Sign Run-Length Persistence Guard."""

    def __init__(
        self,
        max_run_length: int = 7,
        max_avg_run_length: float = 3.5,
        window_size: int = 15,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if (
            max_run_length < 3
            or max_avg_run_length <= 1.0
            or window_size < 5
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave421TradeSignRunLengthGuard")

        self._max_run = int(max_run_length)
        self._max_avg_run = float(max_avg_run_length)
        self._window_size = int(window_size)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_ts: Optional[float] = None
        self._last_sign: Optional[bool] = None
        self._curr_run: int = 0
        self._run_history: deque[int] = deque(maxlen=self._window_size)
        self._avg_run: float = 1.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def current_run_length(self) -> int:
        with self._lock:
            return self._curr_run

    @property
    def average_run_length(self) -> float:
        with self._lock:
            return self._avg_run

    def reset(self) -> None:
        with self._lock:
            self._last_ts = None
            self._last_sign = None
            self._curr_run = 0
            self._run_history.clear()
            self._avg_run = 1.0
            self._blocked_until = 0.0
            self._last_reason = ""

    def _block(self, reason: str, ts: Optional[float] = None) -> None:
        ref_t = time.monotonic() if ts is None else ts
        self._blocked_until = max(self._blocked_until, ref_t + self._cooldown)
        self._last_reason = reason

    def update(self, is_buy: bool, timestamp: float) -> None:
        with self._lock:
            if not isinstance(is_buy, bool) or not isinstance(timestamp, (int, float)) or timestamp < 0.0:
                self._block(_REASON_VAL, timestamp if isinstance(timestamp, (int, float)) and timestamp > 0 else None)
                return

            if self._last_ts is not None and timestamp < self._last_ts:
                self._block(_REASON_VAL, timestamp)
                return

            ts = float(timestamp)
            if self._last_sign is None:
                self._last_sign = is_buy
                self._curr_run = 1
            elif is_buy == self._last_sign:
                self._curr_run += 1
            else:
                self._run_history.append(self._curr_run)
                self._last_sign = is_buy
                self._curr_run = 1

            if len(self._run_history) >= 3:
                avg = (sum(self._run_history) + self._curr_run) / float(len(self._run_history) + 1)
                self._avg_run = avg

                if avg >= self._max_avg_run:
                    self._block(_REASON_IGNITION, ts)

            if self._curr_run >= self._max_run:
                self._block(_REASON_RUN, ts)

            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
