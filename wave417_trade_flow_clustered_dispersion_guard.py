"""
Wave 417 -- Trade Flow Clustered Dispersion & Burst Entropy Guard
=================================================================
Monitors trade inter-arrival time dispersion coefficient C_v = sigma_{Delta t} / mu_{Delta t}.
Under a memoryless Poisson process, C_v = 1.0. During predatory high-frequency sweeps,
trades arrive in ultra-dense bursts followed by dry periods (super-Poisson clustering),
producing extreme dispersion C_v >> 1.5. Such clustering warns of aggressive institutional
iceberg liquidations that overrun passive book liquidity.

Methodology
-----------
* Observes trade arrival timestamps t_i.
* Computes inter-arrival intervals Delta t_i = t_i - t_{i-1}.
* Maintains rolling window of size N (`window_size`).
* Evaluates sample mean mu and standard deviation sigma of Delta t.
* Coefficient of variation: C_v = sigma / max(mu, 1e-6).
* If C_v >= `max_burst_dispersion`, blocks with TRADE_FLOW_BURST_CLUSTERING.
* If mu <= `min_interarrival_sec` and C_v >= 1.5, blocks with SUPER_POISSON_INTENSITY_SPIKE.

Blocking reasons
----------------
TRADE_FLOW_BURST_CLUSTERING     -- inter-arrival time dispersion exceeded super-Poisson limit
SUPER_POISSON_INTENSITY_SPIKE   -- dense trade burst clustering combined with rapid arrival rate
INPUT_VALIDATION_ERROR          -- non-numeric, negative, or non-monotonic timestamp

Public API (standardised)
-------------------------
update(timestamp)              -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
dispersion_coefficient         -> float
mean_interarrival_sec          -> float
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave417TradeFlowClusteredDispersionGuard"]

_REASON_CLUSTERING = "TRADE_FLOW_BURST_CLUSTERING"
_REASON_BURST = "SUPER_POISSON_INTENSITY_SPIKE"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave417TradeFlowClusteredDispersionGuard:
    """Trade Flow Clustered Dispersion and Burst Guard."""

    def __init__(
        self,
        window_size: int = 15,
        max_burst_dispersion: float = 2.0,
        min_interarrival_sec: float = 0.05,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if (
            window_size < 5
            or max_burst_dispersion <= 1.0
            or min_interarrival_sec <= 0.0
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave417TradeFlowClusteredDispersionGuard")

        self._window_size = int(window_size)
        self._max_dispersion = float(max_burst_dispersion)
        self._min_interarrival = float(min_interarrival_sec)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_ts: Optional[float] = None
        self._deltas: deque[float] = deque(maxlen=self._window_size)
        self._cv: float = 1.0
        self._mean_dt: float = 1.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def dispersion_coefficient(self) -> float:
        with self._lock:
            return self._cv

    @property
    def mean_interarrival_sec(self) -> float:
        with self._lock:
            return self._mean_dt

    def reset(self) -> None:
        with self._lock:
            self._last_ts = None
            self._deltas.clear()
            self._cv = 1.0
            self._mean_dt = 1.0
            self._blocked_until = 0.0
            self._last_reason = ""

    def _block(self, reason: str, ts: Optional[float] = None) -> None:
        ref_t = time.monotonic() if ts is None else ts
        self._blocked_until = max(self._blocked_until, ref_t + self._cooldown)
        self._last_reason = reason

    def update(self, timestamp: float) -> None:
        with self._lock:
            if not isinstance(timestamp, (int, float)) or timestamp < 0.0:
                self._block(_REASON_VAL, None)
                return

            if self._last_ts is not None and timestamp < self._last_ts:
                self._block(_REASON_VAL, timestamp)
                return

            ts = float(timestamp)
            if self._last_ts is not None:
                dt = max(ts - self._last_ts, 1e-6)
                self._deltas.append(dt)

                n = len(self._deltas)
                if n >= self._window_size:
                    mean_dt = sum(self._deltas) / float(n)
                    var_dt = sum((d - mean_dt) ** 2 for d in self._deltas) / float(n - 1)
                    std_dt = math.sqrt(max(var_dt, 0.0))

                    cv = std_dt / max(mean_dt, 1e-6)
                    self._cv = cv
                    self._mean_dt = mean_dt

                    if cv >= self._max_dispersion:
                        self._block(_REASON_CLUSTERING, ts)
                    elif mean_dt <= self._min_interarrival and cv >= 1.50:
                        self._block(_REASON_BURST, ts)

            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
