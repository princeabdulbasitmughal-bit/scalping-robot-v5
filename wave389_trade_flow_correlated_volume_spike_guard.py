"""
Wave 389 -- Trade Flow Correlated Volume Spike Guard
=====================================================
Detects consecutive clustered volume spikes. When multiple large trades
execute in direct succession, this signals institutional block execution,
predatory sweeps, or coordinated stop-loss cascades.

Methodology
-----------
* Examines executed trade volumes.
* A trade is a spike candidate if volume >= `spike_volume_threshold`.
* Tracks consecutive spike trades.
* If the consecutive spike count reaches `max_consecutive_spikes`,
  blocks trading for `cooldown_seconds`.
* Any trade below the threshold resets the consecutive streak.

Blocking reasons
----------------
CORRELATED_VOLUME_SPIKE -- run of consecutive large volume trades exceeds threshold
INPUT_VALIDATION_ERROR  -- invalid volume, side, or timestamp

Public API (standardised)
-------------------------
update(volume, side, timestamp) -> None
is_blocked(current_time=None)   -> bool
is_entry_blocked(bid, ask, ts)  -> bool
reset()                         -> None
last_reason                     -> str
"""

from __future__ import annotations

import threading
import time
from typing import Optional

__all__ = ["Wave389TradeFlowCorrelatedVolumeSpikeGuard"]

_REASON_SPIKE = "CORRELATED_VOLUME_SPIKE"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave389TradeFlowCorrelatedVolumeSpikeGuard:
    """Trade flow correlated volume spike and clustered block execution guard."""

    def __init__(
        self,
        spike_volume_threshold: float = 200.0,
        max_consecutive_spikes: int = 4,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if spike_volume_threshold <= 0.0 or max_consecutive_spikes < 2:
            raise ValueError("Invalid parameters for Wave389TradeFlowCorrelatedVolumeSpikeGuard")
        self._spike_thresh = float(spike_volume_threshold)
        self._max_spikes = int(max_consecutive_spikes)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._consecutive_spikes = 0
        self._blocked_until = 0.0
        self._last_reason = ""

    def update(self, volume: float, side: str, timestamp: float) -> None:
        with self._lock:
            for val in (volume, timestamp):
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    self._block(_REASON_VAL)
                    return

            if volume <= 0.0 or side not in ("buy", "sell"):
                self._block(_REASON_VAL)
                return

            v = float(volume)

            if v >= self._spike_thresh:
                self._consecutive_spikes += 1
                if self._consecutive_spikes >= self._max_spikes:
                    self._block(_REASON_SPIKE)
            else:
                self._consecutive_spikes = 0

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
            self._consecutive_spikes = 0
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
