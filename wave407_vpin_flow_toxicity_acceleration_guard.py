"""
Wave 407 -- Volume-Synchronized Probability of Toxicity (VPIN) Acceleration Guard
=================================================================================
Implements the Easley, López de Prado, and O'Hara (2012) Volume-Synchronized
Probability of Toxicity (VPIN) metric. Accumulates continuous trade flow into constant
volume buckets and computes order imbalance. Supercritical VPIN values or rapid
acceleration warn of toxic informed order flow and predatory microstructure cascades.

Methodology
-----------
* Accumulates incoming trade fills: (volume, is_buy, timestamp).
* Partitions trade volume into fixed-size buckets of volume V (`bucket_size`).
* For each completed bucket k, calculates:
    I_k = |V_k^{buy} - V_k^{sell}| / V
* VPIN is the rolling average over N completed buckets:
    VPIN = (1 / N) * sum_{k=1}^N I_k
* Monitors VPIN level and acceleration Delta VPIN = VPIN_k - VPIN_{k-1}.
* If VPIN >= `max_vpin_threshold`, blocks with HIGH_VPIN_TOXIC_FLOW.
* If Delta VPIN >= `max_vpin_acceleration`, blocks with VPIN_RAPID_ACCELERATION.

Blocking reasons
----------------
HIGH_VPIN_TOXIC_FLOW      -- rolling VPIN exceeded toxic threshold
VPIN_RAPID_ACCELERATION   -- instantaneous VPIN surge over one bucket
INPUT_VALIDATION_ERROR    -- non-positive volume, invalid timestamp, or non-numeric params

Public API (standardised)
-------------------------
update(volume, is_buy, timestamp) -> None
is_blocked(current_time=None)     -> bool
is_entry_blocked(bid, ask, ts)    -> bool
reset()                           -> None
last_reason                       -> str
current_vpin                      -> float
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave407VpinFlowToxicityAccelerationGuard"]

_REASON_HIGH_VPIN = "HIGH_VPIN_TOXIC_FLOW"
_REASON_ACCEL = "VPIN_RAPID_ACCELERATION"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave407VpinFlowToxicityAccelerationGuard:
    """VPIN Flow Toxicity and Acceleration Guard."""

    def __init__(
        self,
        bucket_size: float = 100.0,
        num_buckets: int = 10,
        max_vpin_threshold: float = 0.65,
        max_vpin_acceleration: float = 0.25,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if (
            bucket_size <= 0.0
            or num_buckets < 3
            or not (0.10 <= max_vpin_threshold <= 0.95)
            or not (0.05 <= max_vpin_acceleration <= 0.90)
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave407VpinFlowToxicityAccelerationGuard")

        self._bucket_size = float(bucket_size)
        self._num_buckets = int(num_buckets)
        self._max_vpin = float(max_vpin_threshold)
        self._max_accel = float(max_vpin_acceleration)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._curr_bucket_buy: float = 0.0
        self._curr_bucket_sell: float = 0.0
        self._curr_bucket_filled: float = 0.0
        self._buckets: deque[float] = deque(maxlen=self._num_buckets)
        self._last_vpin: Optional[float] = None
        self._current_vpin: float = 0.0
        self._last_ts: Optional[float] = None
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def current_vpin(self) -> float:
        with self._lock:
            return self._current_vpin

    def reset(self) -> None:
        with self._lock:
            self._curr_bucket_buy = 0.0
            self._curr_bucket_sell = 0.0
            self._curr_bucket_filled = 0.0
            self._buckets.clear()
            self._last_vpin = None
            self._current_vpin = 0.0
            self._last_ts = None
            self._blocked_until = 0.0
            self._last_reason = ""

    def _block(self, reason: str, ts: Optional[float] = None) -> None:
        ref_t = time.monotonic() if ts is None else ts
        self._blocked_until = max(self._blocked_until, ref_t + self._cooldown)
        self._last_reason = reason

    def update(self, volume: float, is_buy: bool, timestamp: float) -> None:
        with self._lock:
            if (
                not isinstance(volume, (int, float))
                or not isinstance(timestamp, (int, float))
                or volume <= 0.0
                or timestamp < 0.0
            ):
                self._block(_REASON_VAL, timestamp if timestamp > 0 else None)
                return

            if self._last_ts is not None and timestamp < self._last_ts:
                self._block(_REASON_VAL, timestamp)
                return

            self._last_ts = float(timestamp)
            vol_remaining = float(volume)

            while vol_remaining > 0.0:
                needed = self._bucket_size - self._curr_bucket_filled
                alloc = min(vol_remaining, needed)
                if is_buy:
                    self._curr_bucket_buy += alloc
                else:
                    self._curr_bucket_sell += alloc
                self._curr_bucket_filled += alloc
                vol_remaining -= alloc

                if self._curr_bucket_filled >= self._bucket_size - 1e-9:
                    # Bucket complete
                    imbalance = abs(self._curr_bucket_buy - self._curr_bucket_sell) / self._bucket_size
                    self._buckets.append(imbalance)

                    # Reset current bucket
                    self._curr_bucket_buy = 0.0
                    self._curr_bucket_sell = 0.0
                    self._curr_bucket_filled = 0.0

                    if len(self._buckets) >= self._num_buckets:
                        vpin = sum(self._buckets) / len(self._buckets)
                        self._current_vpin = vpin

                        if vpin >= self._max_vpin:
                            self._block(_REASON_HIGH_VPIN, float(timestamp))

                        if self._last_vpin is not None:
                            accel = vpin - self._last_vpin
                            if accel >= self._max_accel:
                                self._block(_REASON_ACCEL, float(timestamp))

                        self._last_vpin = vpin

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
