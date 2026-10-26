"""
Wave 393 -- Trade Flow Amplitude Modulation Guard
==================================================
Monitors amplitude modulation and volume-envelope volatility of the signed
trade volume flow. Rapid oscillations in trade size envelopes indicate
irregular algorithmic pacing, pulsed block liquidity injection, or predatory pumping.

Methodology
-----------
* Observes absolute signed trade volume: |sv_i|.
* Tracks local peak envelope over a trailing `env_window`:
    envelope_t = max(|sv_{t-k}| for k in 0..env_window-1)
* Maintains a rolling window of recent envelope observations of size `am_window`.
* Computes standard deviation of the envelope series.
* If std(envelope) >= `modulation_threshold`, blocks trading for `cooldown_seconds`.

Blocking reasons
----------------
AMPLITUDE_MODULATION_BREACH -- excessive volume envelope volatility / pulsing
INPUT_VALIDATION_ERROR      -- invalid volume, side, or timestamp

Public API (standardised)
-------------------------
update(volume, side, timestamp) -> None
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

__all__ = ["Wave393TradeFlowAmplitudeModulationGuard"]

_REASON_AM = "AMPLITUDE_MODULATION_BREACH"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave393TradeFlowAmplitudeModulationGuard:
    """Trade flow signed volume amplitude modulation and envelope volatility guard."""

    def __init__(
        self,
        env_window: int = 5,
        am_window: int = 15,
        modulation_threshold: float = 100.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if env_window < 2 or am_window < 3 or modulation_threshold <= 0.0:
            raise ValueError("Invalid parameters for Wave393TradeFlowAmplitudeModulationGuard")
        self._env_window = int(env_window)
        self._am_window = int(am_window)
        self._thresh = float(modulation_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._raw_vols: deque[float] = deque(maxlen=self._env_window)
        self._envelopes: deque[float] = deque(maxlen=self._am_window)
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
            self._raw_vols.append(v)

            if len(self._raw_vols) >= self._env_window:
                env = max(self._raw_vols)
                self._envelopes.append(env)

                if len(self._envelopes) >= self._am_window:
                    envs = list(self._envelopes)
                    n = len(envs)
                    m = sum(envs) / n
                    var = sum((x - m) ** 2 for x in envs) / n
                    std = math.sqrt(var)

                    if std >= self._thresh:
                        self._block(_REASON_AM)

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
            self._raw_vols.clear()
            self._envelopes.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
