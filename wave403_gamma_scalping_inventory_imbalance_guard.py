"""
Wave 403 -- Gamma Scalping Inventory Imbalance Guard
===================================================
Monitors net inventory position exposure and gamma convexity risk for the scalper.
When inventory reaches extreme capacity limits during expanding volatility regimes,
further position entries are halted to prevent adverse selection liquidation cascades.

Methodology
-----------
* Observes current net position `net_inventory` (contracts or lots) and `max_capacity`.
* Computes normalized inventory load:
    load = |net_inventory| / max_capacity
* If load >= `critical_load_threshold`, blocks further entry expansion with `GAMMA_INVENTORY_SKEW_LOCKOUT`.

Blocking reasons
----------------
GAMMA_INVENTORY_SKEW_LOCKOUT -- inventory exposure at or above critical capacity threshold
INPUT_VALIDATION_ERROR       -- max_capacity <= 0, non-numeric values or invalid timestamp

Public API (standardised)
-------------------------
update(net_inventory, max_capacity, timestamp) -> None
is_blocked(current_time=None)                  -> bool
is_entry_blocked(bid, ask, ts)                 -> bool
reset()                                        -> None
last_reason                                    -> str
"""

from __future__ import annotations

import threading
import time
from typing import Optional

__all__ = ["Wave403GammaScalpingInventoryImbalanceGuard"]

_REASON_LOCKOUT = "GAMMA_INVENTORY_SKEW_LOCKOUT"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave403GammaScalpingInventoryImbalanceGuard:
    """Gamma scalping inventory capacity guard."""

    def __init__(
        self,
        critical_load_threshold: float = 0.85,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if not (0.0 < critical_load_threshold <= 1.0) or cooldown_seconds <= 0.0:
            raise ValueError("Invalid parameters for Wave403GammaScalpingInventoryImbalanceGuard")
        self._crit_load = float(critical_load_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._blocked_until = 0.0
        self._last_reason = ""

    def update(self, net_inventory: float, max_capacity: float, timestamp: float) -> None:
        with self._lock:
            for val in (net_inventory, max_capacity, timestamp):
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    self._block(_REASON_VAL)
                    return

            if max_capacity <= 0.0:
                self._block(_REASON_VAL)
                return

            load = abs(float(net_inventory)) / float(max_capacity)
            if load >= self._crit_load:
                self._block(_REASON_LOCKOUT)

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
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
