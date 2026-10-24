"""
Wave 349 -- Trade Flow Signed Volume Clustering Dispersion Guard
=================================================================
Monitors clustering and dispersion of trade signed volume:
    Signed Volume SV_i = (+1 if buy else -1) * Volume_i
    Dispersion Ratio   = Var(SV) / (Mean(|SV|)^2 + 1e-9)

Under normal balanced market conditions, signed volume arrives symmetrically with
low clustering dispersion. When predatory institutional algos or momentum sweepers
hit the tape, high-volume clumped clusters appear in bursts, causing the dispersion
ratio to exceed dispersion_ratio_threshold.
The guard flags this toxic clustering and preemptively locks out new market orders.

Blocking reasons
----------------
SIGNED_VOLUME_CLUSTERING_DISPERSION  -- Dispersion ratio >= dispersion_ratio_threshold
INPUT_VALIDATION_ERROR               -- Invalid side, non-positive or bool volume/ts

Public API
----------
update(side, volume, timestamp) -> None
is_blocked(current_time=None)   -> bool
is_entry_blocked(bid, ask, ts)  -> bool
reset()                         -> None
last_reason                     -> str
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave349TradeFlowSignedVolumeClusteringDispersionGuard"]

_REASON_DISP = "SIGNED_VOLUME_CLUSTERING_DISPERSION"
_REASON_VAL  = "INPUT_VALIDATION_ERROR"


class Wave349TradeFlowSignedVolumeClusteringDispersionGuard:
    """Detects predatory signed volume clustering bursts via variance-to-mean dispersion ratio."""

    def __init__(
        self,
        window_size: int = 15,
        dispersion_ratio_threshold: float = 2.5,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if window_size < 5 or dispersion_ratio_threshold <= 0:
            raise ValueError("Invalid parameters for Signed Volume Clustering Dispersion Guard.")
        self._window = int(window_size)
        self._threshold = float(dispersion_ratio_threshold)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._signed_volumes: deque = deque(maxlen=window_size)
        self._blocked_until = 0.0
        self._blocked_until_sim = 0.0
        self._last_reason = ""

    def update(self, side: str, volume: float, timestamp: float) -> None:
        with self._lock:
            # Type and boolean validations
            if isinstance(side, bool) or isinstance(volume, bool) or isinstance(timestamp, bool):
                self._block(timestamp, _REASON_VAL)
                return
            if not isinstance(side, str) or not (isinstance(volume, (int, float)) and isinstance(timestamp, (int, float))):
                self._block(timestamp, _REASON_VAL)
                return

            s_clean = side.strip().lower()
            if s_clean not in ("buy", "sell", "b", "s"):
                self._block(timestamp, _REASON_VAL)
                return

            v = float(volume)
            ts = float(timestamp)

            if v <= 0:
                self._block(ts, _REASON_VAL)
                return

            sign = 1.0 if s_clean in ("buy", "b") else -1.0
            sv = sign * v
            self._signed_volumes.append(sv)

            if len(self._signed_volumes) >= self._window:
                svs = list(self._signed_volumes)
                n = len(svs)
                mean_sv = sum(svs) / n
                var_sv = sum((x - mean_sv) ** 2 for x in svs) / n
                mean_abs = sum(abs(x) for x in svs) / n

                denom = (mean_abs ** 2) + 1e-9
                dispersion_ratio = var_sv / denom

                if dispersion_ratio >= self._threshold:
                    self._block(ts, _REASON_DISP)

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
            self._signed_volumes.clear()
            self._blocked_until = 0.0
            self._blocked_until_sim = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
