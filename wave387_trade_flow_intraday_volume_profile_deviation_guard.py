"""
Wave 387 -- Trade Flow Intraday Volume Profile Deviation Guard
==============================================================
Monitors executed trade volumes against expected historical intraday volume
profile distributions. An anomalous surge in trade volume relative to typical
historical volume for the identical intraday time bin signals news catalysts,
institutional accumulation, or abnormal regime shifts.

Methodology
-----------
* Maps each execution timestamp into an intraday time bin:
    slot_id = int((timestamp % day_seconds) / slot_seconds)
* Accumulates volume in the current time slot.
* When slot transitions, archives slot total volume into historical bin distributions.
* If >= `min_history_slots` observations exist for the current slot:
    Computes historical mean mu and sample standard deviation sigma.
    Computes z-score = (current_slot_volume - mu) / max(sigma, 1e-6).
    If z-score >= `z_threshold`, blocks trading for `cooldown_seconds`.

Blocking reasons
----------------
VOLUME_PROFILE_ANOMALY -- slot volume deviates significantly from historical profile
INPUT_VALIDATION_ERROR -- invalid volume or timestamp

Public API (standardised)
-------------------------
update(volume, timestamp)      -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
"""

from __future__ import annotations

import math
import threading
import time
from typing import Optional

__all__ = ["Wave387TradeFlowIntradayVolumeProfileDeviationGuard"]

_REASON_ANOMALY = "VOLUME_PROFILE_ANOMALY"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave387TradeFlowIntradayVolumeProfileDeviationGuard:
    """Trade flow intraday volume profile z-score anomaly guard."""

    def __init__(
        self,
        slot_seconds: float = 60.0,
        day_seconds: float = 86400.0,
        min_history_slots: int = 3,
        z_threshold: float = 3.0,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if slot_seconds <= 0.0 or day_seconds <= slot_seconds or min_history_slots < 2 or z_threshold <= 0.0:
            raise ValueError("Invalid parameters for Wave387TradeFlowIntradayVolumeProfileDeviationGuard")
        self._slot_sec = float(slot_seconds)
        self._day_sec = float(day_seconds)
        self._min_hist = int(min_history_slots)
        self._z_thresh = float(z_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._current_slot_id: Optional[int] = None
        self._current_slot_vol = 0.0
        self._slot_history: dict[int, list[float]] = {}
        self._blocked_until = 0.0
        self._last_reason = ""

    def update(self, volume: float, timestamp: float) -> None:
        with self._lock:
            for val in (volume, timestamp):
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    self._block(_REASON_VAL)
                    return

            if volume <= 0.0:
                self._block(_REASON_VAL)
                return

            v = float(volume)
            ts = float(timestamp)
            slot_id = int((ts % self._day_sec) / self._slot_sec)

            if self._current_slot_id is not None and slot_id != self._current_slot_id:
                # Slot rollover: record previous slot total volume
                hist = self._slot_history.setdefault(self._current_slot_id, [])
                hist.append(self._current_slot_vol)
                self._current_slot_vol = 0.0

            self._current_slot_id = slot_id
            self._current_slot_vol += v

            # Check deviation if sufficient historical days for this slot
            hist = self._slot_history.get(slot_id, [])
            if len(hist) >= self._min_hist:
                n = len(hist)
                mu = sum(hist) / n
                var = sum((x - mu) ** 2 for x in hist) / n
                sigma = math.sqrt(var)

                if sigma > 1e-6:
                    z = (self._current_slot_vol - mu) / sigma
                    if z >= self._z_thresh:
                        self._block(_REASON_ANOMALY)

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
            self._current_slot_id = None
            self._current_slot_vol = 0.0
            self._slot_history.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
