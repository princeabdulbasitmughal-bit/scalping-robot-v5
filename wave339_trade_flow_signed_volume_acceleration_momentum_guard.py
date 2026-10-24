"""
Wave 339 — Trade Flow Signed-Volume Acceleration Momentum Guard
===============================================================
Monitors second-order dynamics of the signed-volume series: the *acceleration*
of signed order flow (the rate of change of the momentum of signed volume).

Methodology
-----------
* Maintain a rolling sum of signed volume over `momentum_window` ticks.
  signed_volume = +volume if side=="buy", -volume if side=="sell"
* Momentum_i = rolling_sum(i) - rolling_sum(i - momentum_window)   (first difference)
* Acceleration_i = Momentum_i - Momentum_{i-1}                     (second difference)
* Maintain a deque of the last `accel_window` accelerations.
* Block when the rolling mean of |acceleration| exceeds `accel_threshold`.

Blocking reasons
----------------
FLOW_ACCELERATION_BREACH — mean |acceleration| >= threshold
INPUT_VALIDATION_ERROR   — malformed arguments

Public API (standardised)
-------------------------
update(volume, side, timestamp) -> None
is_blocked(current_time=None)   -> bool
is_entry_blocked(bid, ask, ts)  -> bool
reset()                         -> None
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave339TradeFlowSignedVolumeAccelerationMomentumGuard"]

_REASON_ACCEL = "FLOW_ACCELERATION_BREACH"
_REASON_VAL   = "INPUT_VALIDATION_ERROR"


class Wave339TradeFlowSignedVolumeAccelerationMomentumGuard:
    """Signed-volume acceleration momentum guard."""

    def __init__(
        self,
        momentum_window: int = 5,
        accel_window: int = 10,
        accel_threshold: float = 50.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if momentum_window < 1 or accel_window < 2 or accel_threshold <= 0:
            raise ValueError("Invalid acceleration momentum guard parameters.")
        self._mom_win   = int(momentum_window)
        self._acc_win   = int(accel_window)
        self._acc_thr   = float(accel_threshold)
        self._cooldown  = float(cooldown_seconds)

        self._lock      = threading.RLock()
        # Signed volume history (enough to compute two rolling sums)
        self._sv: deque = deque(maxlen=momentum_window * 2 + 2)
        self._prev_mom: Optional[float] = None
        self._accels: deque = deque(maxlen=accel_window)
        self._blocked_until = 0.0
        self._last_reason   = ""

    # ------------------------------------------------------------------
    def update(self, volume: float, side: str, timestamp: float) -> None:
        with self._lock:
            if isinstance(volume, bool):
                self._block(timestamp, _REASON_VAL)
                return
            if not isinstance(volume, (int, float)) or volume <= 0:
                self._block(timestamp, _REASON_VAL)
                return
            if side not in ("buy", "sell"):
                self._block(timestamp, _REASON_VAL)
                return

            sv = float(volume) if side == "buy" else -float(volume)
            self._sv.append(sv)

            if len(self._sv) < self._mom_win + 1:
                return

            sv_list  = list(self._sv)
            # Momentum = sum of last mom_win signed volumes
            mom_now  = sum(sv_list[-self._mom_win:])

            if self._prev_mom is not None:
                accel = mom_now - self._prev_mom
                self._accels.append(abs(accel))

                if len(self._accels) >= self._acc_win:
                    mean_abs_accel = sum(self._accels) / len(self._accels)
                    if mean_abs_accel >= self._acc_thr:
                        self._block(timestamp, _REASON_ACCEL)

            self._prev_mom = mom_now

    def _block(self, timestamp: float, reason: str) -> None:
        self._blocked_until = time.monotonic() + self._cooldown
        self._last_reason   = reason

    # ------------------------------------------------------------------
    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            t = time.monotonic() if current_time is None else current_time
            return t < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: float) -> bool:
        return self.is_blocked(ts)

    def reset(self) -> None:
        with self._lock:
            self._sv.clear()
            self._prev_mom  = None
            self._accels.clear()
            self._blocked_until = 0.0
            self._last_reason   = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
