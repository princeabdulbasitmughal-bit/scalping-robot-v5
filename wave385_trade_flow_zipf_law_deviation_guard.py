"""
Wave 385 -- Trade Flow Zipf Law Deviation Guard
================================================
Evaluates trade volume scaling against empirical power-law / Zipf's law distributions.
Natural market orders exhibit heavy-tailed power-law decay in trade volume frequencies.
Significant deviation (e.g., severe flat or non-scaling distribution) indicates
synthetic algo churn, spoofing clusters, or unnatural trading volume.

Methodology
-----------
* Accumulates individual trade volumes over a rolling window of `window_size` trades.
* Bins trade volumes into logarithmic intervals to determine frequency counts.
* Sorts non-empty bins by frequency descending, assigning ranks r = 1, 2, ...
* Computes Pearson correlation between ln(rank) and ln(frequency).
* For natural power-law flow, correlation is strongly negative (<= -0.75).
* Blocks if correlation > `max_zipf_correlation` (e.g. > -0.50, indicating poor scaling).

Blocking reasons
----------------
ZIPF_DEVIATION_DETECTED -- trade size distribution violates empirical power-law scaling
INSUFFICIENT_DATA       -- too few distinct volume bins to calculate fit
INPUT_VALIDATION_ERROR  -- invalid volume or timestamp

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
from collections import deque
from typing import Optional

__all__ = ["Wave385TradeFlowZipfLawDeviationGuard"]

_REASON_ZIPF = "ZIPF_DEVIATION_DETECTED"
_REASON_DATA = "INSUFFICIENT_DATA"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave385TradeFlowZipfLawDeviationGuard:
    """Trade flow Zipf's law scaling and volume distribution conformity guard."""

    def __init__(
        self,
        window_size: int = 30,
        max_zipf_correlation: float = -0.50,
        min_distinct_bins: int = 4,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if window_size < 10 or min_distinct_bins < 3:
            raise ValueError("Invalid parameters for Wave385TradeFlowZipfLawDeviationGuard")
        self._window_size = int(window_size)
        self._max_corr = float(max_zipf_correlation)
        self._min_bins = int(min_distinct_bins)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._volumes: deque[float] = deque(maxlen=self._window_size)
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

            self._volumes.append(float(volume))

            if len(self._volumes) >= self._window_size:
                vols = list(self._volumes)
                # Discretize into powers of 2 (log2 bins)
                bin_counts: dict[int, int] = {}
                for v in vols:
                    b_idx = int(math.floor(math.log2(v)))
                    bin_counts[b_idx] = bin_counts.get(b_idx, 0) + 1

                freqs = sorted(bin_counts.values(), reverse=True)
                if len(freqs) < self._min_bins:
                    # Not enough bin variation to fit
                    return

                # Calculate Pearson correlation between ln(rank) and ln(freq)
                ranks = list(range(1, len(freqs) + 1))
                log_r = [math.log(r) for r in ranks]
                log_f = [math.log(f) for f in freqs]

                n = len(ranks)
                mr = sum(log_r) / n
                mf = sum(log_f) / n

                cov = sum((log_r[i] - mr) * (log_f[i] - mf) for i in range(n))
                vr = sum((x - mr) ** 2 for x in log_r)
                vf = sum((y - mf) ** 2 for y in log_f)

                if vr > 1e-12:
                    if vf < 1e-12:
                        # Completely flat frequencies across all bins is an extreme violation of Zipf's law
                        self._block(_REASON_ZIPF)
                        return

                    corr = cov / (math.sqrt(vr) * math.sqrt(vf))
                    if corr > self._max_corr:
                        self._block(_REASON_ZIPF)

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
            self._volumes.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
