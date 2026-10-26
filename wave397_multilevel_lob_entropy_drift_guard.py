"""
Wave 397 -- Multi-Level Order Book Entropy Drift Guard
======================================================
Monitors the spatial distribution and Shannon entropy of resting depth across
multiple order book levels. An abrupt collapse or extreme drift in depth entropy
reveals predatory phantom liquidity spoofing, wall clustering, or order book hollow-out.

Methodology
-----------
* Observes depth across K levels: `depths = [d_1, d_2, ..., d_K]`.
* Validates at least 3 levels, all depths >= 0, sum(depths) > 0, numeric timestamp.
* Computes normalized depth probabilities: p_i = d_i / sum(depths).
* Computes Shannon entropy: H = -sum(p_i * ln(p_i)) for p_i > 0.
* Normalizes entropy by maximum entropy ln(K): H_norm = H / ln(K) in [0.0, 1.0].
* If H_norm <= `min_normalized_entropy` -> blocks with `LOB_ENTROPY_COLLAPSE`.
* If |H_norm - H_norm_last| >= `max_entropy_drift` -> blocks with `LOB_ENTROPY_COLLAPSE`.

Blocking reasons
----------------
LOB_ENTROPY_COLLAPSE   -- depth distribution collapsed into single tier or drifted abruptly
INPUT_VALIDATION_ERROR -- invalid depth array, zero total volume, non-numeric timestamp

Public API (standardised)
-------------------------
update(depths, timestamp)      -> None
is_blocked(current_time=None)  -> bool
is_entry_blocked(bid, ask, ts) -> bool
reset()                        -> None
last_reason                    -> str
"""

from __future__ import annotations

import math
import threading
import time
from typing import Optional, Sequence

__all__ = ["Wave397MultilevelLOBEntropyDriftGuard"]

_REASON_COLLAPSE = "LOB_ENTROPY_COLLAPSE"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave397MultilevelLOBEntropyDriftGuard:
    """Multi-level LOB spatial depth Shannon entropy guard."""

    def __init__(
        self,
        min_normalized_entropy: float = 0.35,
        max_entropy_drift: float = 0.50,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if not (0.0 < min_normalized_entropy < 1.0) or not (0.0 < max_entropy_drift <= 1.0):
            raise ValueError("Invalid parameters for Wave397MultilevelLOBEntropyDriftGuard")
        self._min_entropy = float(min_normalized_entropy)
        self._max_drift = float(max_entropy_drift)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._last_entropy: Optional[float] = None
        self._blocked_until = 0.0
        self._last_reason = ""

    def update(self, depths: Sequence[float], timestamp: float) -> None:
        with self._lock:
            if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
                self._block(_REASON_VAL)
                return

            if not isinstance(depths, (list, tuple)) or len(depths) < 3:
                self._block(_REASON_VAL)
                return

            for d in depths:
                if isinstance(d, bool) or not isinstance(d, (int, float)) or d < 0.0:
                    self._block(_REASON_VAL)
                    return

            total_depth = sum(float(d) for d in depths)
            if total_depth <= 0.0:
                self._block(_REASON_VAL)
                return

            k = len(depths)
            max_h = math.log(k)

            h = 0.0
            for d in depths:
                val = float(d)
                if val > 0.0:
                    p = val / total_depth
                    h -= p * math.log(p)

            norm_h = h / max_h if max_h > 0.0 else 1.0

            if norm_h <= self._min_entropy:
                self._block(_REASON_COLLAPSE)
            elif self._last_entropy is not None:
                drift = abs(norm_h - self._last_entropy)
                if drift >= self._max_drift:
                    self._block(_REASON_COLLAPSE)

            self._last_entropy = norm_h

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
            self._last_entropy = None
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
