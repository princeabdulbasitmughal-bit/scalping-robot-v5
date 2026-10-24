"""
Wave 345 -- Trade Size Pareto Alpha Decay Guard
================================================
Monitors the power-law tail exponent (Pareto alpha / Hill index) of trade sizes:
    alpha_Hill = [ (1/k) * sum_{i=1}^k ln(s_{(i)} / s_{(k+1)}) ]^(-1)

Under normal market conditions, alpha > 2.0 (finite variance, balanced sizing).
When aggressive whales or predatory sweep algorithms enter, huge block trades dominate,
causing alpha to compress below alpha_decay_threshold (heavy-tailed regime).
This indicates severe adverse selection risk and impending price shock, triggering
preemptive execution lockout.

Blocking reasons
----------------
PARETO_ALPHA_DECAY      -- Hill tail index alpha <= alpha_decay_threshold
INPUT_VALIDATION_ERROR  -- Non-positive, boolean or non-numeric inputs

Public API
----------
update(trade_size, timestamp)  -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave345TradeSizeParetoAlphaDecayGuard"]

_REASON_DECAY = "PARETO_ALPHA_DECAY"
_REASON_VAL   = "INPUT_VALIDATION_ERROR"


class Wave345TradeSizeParetoAlphaDecayGuard:
    """Detects power-law tail exponent decay in trade sizes via Hill estimator."""

    def __init__(
        self,
        window_size: int = 20,
        top_k: int = 6,
        alpha_decay_threshold: float = 1.25,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if window_size < 10 or top_k < 2 or top_k >= window_size or alpha_decay_threshold <= 0:
            raise ValueError("Invalid parameters for Trade Size Pareto Alpha Decay Guard.")
        self._window = int(window_size)
        self._top_k = int(top_k)
        self._threshold = float(alpha_decay_threshold)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._sizes: deque = deque(maxlen=window_size)
        self._blocked_until = 0.0
        self._blocked_until_sim = 0.0
        self._last_reason = ""

    def update(self, trade_size: float, timestamp: float) -> None:
        with self._lock:
            # Type and boolean validation
            if isinstance(trade_size, bool) or isinstance(timestamp, bool):
                self._block(timestamp, _REASON_VAL)
                return
            if not (isinstance(trade_size, (int, float)) and isinstance(timestamp, (int, float))):
                self._block(timestamp, _REASON_VAL)
                return

            s = float(trade_size)
            ts = float(timestamp)

            if s <= 0:
                self._block(ts, _REASON_VAL)
                return

            self._sizes.append(s)

            if len(self._sizes) >= self._window:
                # Sort descending: s_{(1)} >= s_{(2)} >= ...
                sorted_sizes = sorted(self._sizes, reverse=True)
                threshold_size = sorted_sizes[self._top_k]

                if threshold_size <= 0:
                    return

                # Hill Estimator:
                # sum_{i=0}^{k-1} ln(s_{(i)} / s_{(k)})
                log_sum = sum(math.log(sorted_sizes[i] / threshold_size) for i in range(self._top_k))

                if log_sum > 1e-9:
                    alpha_hill = self._top_k / log_sum
                    if alpha_hill <= self._threshold:
                        self._block(ts, _REASON_DECAY)

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
            self._sizes.clear()
            self._blocked_until = 0.0
            self._blocked_until_sim = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
