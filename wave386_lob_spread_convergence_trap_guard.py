"""
Wave 386 -- LOB Spread Convergence Trap Guard
==============================================
Detects predatory spread convergence traps: a sequence where bid-ask spread
progressively compresses over multiple ticks (luring in retail limit orders)
and then explodes abruptly outward (triggering stop-outs / adverse execution).

Methodology
-----------
* Calculates spread_bps at each tick.
* Tracks consecutive narrowing ticks: spread_t < spread_{t-1}.
* If spread compressed for >= `compress_ticks` reaching `min_compressed_spread`,
  and the next tick widens by >= `explosion_multiple * min_compressed_spread`,
  blocks trading for `cooldown_seconds`.

Blocking reasons
----------------
SPREAD_TRAP_DETECTED   -- compression followed by rapid spread blowout
INPUT_VALIDATION_ERROR -- malformed price inputs

Public API (standardised)
-------------------------
update(bid, ask, timestamp)    -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
"""

from __future__ import annotations

import threading
import time
from typing import Optional

__all__ = ["Wave386LOBSpreadConvergenceTrapGuard"]

_REASON_TRAP = "SPREAD_TRAP_DETECTED"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave386LOBSpreadConvergenceTrapGuard:
    """LOB spread convergence trap and predatory blowout guard."""

    def __init__(
        self,
        compress_ticks: int = 3,
        explosion_multiple: float = 2.5,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if compress_ticks < 2 or explosion_multiple <= 1.0:
            raise ValueError("Invalid parameters for Wave386LOBSpreadConvergenceTrapGuard")
        self._compress_ticks = int(compress_ticks)
        self._explosion_mult = float(explosion_multiple)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._prev_spread: Optional[float] = None
        self._compress_count = 0
        self._min_spread: Optional[float] = None
        self._blocked_until = 0.0
        self._last_reason = ""

    def update(self, bid: float, ask: float, timestamp: float) -> None:
        with self._lock:
            for val in (bid, ask, timestamp):
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    self._block(_REASON_VAL)
                    return

            if bid <= 0.0 or ask <= 0.0 or ask <= bid:
                self._block(_REASON_VAL)
                return

            mid = (bid + ask) / 2.0
            spread_bps = ((ask - bid) / mid) * 10_000.0

            if self._prev_spread is not None:
                if spread_bps < self._prev_spread - 1e-6:
                    # Compressing
                    self._compress_count += 1
                    if self._min_spread is None or spread_bps < self._min_spread:
                        self._min_spread = spread_bps
                elif spread_bps > self._prev_spread + 1e-6:
                    # Widened
                    if self._compress_count >= self._compress_ticks and self._min_spread is not None:
                        if spread_bps >= self._explosion_mult * self._min_spread:
                            self._block(_REASON_TRAP)
                    self._compress_count = 0
                    self._min_spread = None
                else:
                    # Unchanged
                    pass

            self._prev_spread = spread_bps

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
            self._prev_spread = None
            self._compress_count = 0
            self._min_spread = None
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
