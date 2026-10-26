"""
Wave 350 -- Market Depth Entropy Spectral Density Guard (Jubilee Wave)
=======================================================================
Monitors the normalized Shannon entropy and distribution of market depth
across multiple order book levels:
    p_k = Q_k / sum(Q)
    H   = - sum_{k=1}^M p_k * ln(p_k)
    H_norm = H / ln(M)

Under healthy, competitive market conditions, depth is distributed across levels
with high normalized entropy (H_norm >= min_entropy_threshold).
When predatory algorithms, spoofing walls, or ghost quotes concentrate liquidity
into a single level (causing liquidity collapse on adjacent levels), H_norm drops
sharply towards zero.
The guard detects this structural entropy collapse and locks out market orders.

Blocking reasons
----------------
DEPTH_ENTROPY_COLLAPSE  -- Normalized depth entropy H_norm <= min_entropy_threshold
INPUT_VALIDATION_ERROR  -- Empty list, non-positive or bool elements/ts

Public API
----------
update(depth_sizes, timestamp) -> None
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
from typing import List, Optional

__all__ = ["Wave350MarketDepthEntropySpectralDensityGuard"]

_REASON_COLLAPSE = "DEPTH_ENTROPY_COLLAPSE"
_REASON_VAL      = "INPUT_VALIDATION_ERROR"


class Wave350MarketDepthEntropySpectralDensityGuard:
    """Monitors normalized Shannon entropy across multi-level orderbook depth."""

    def __init__(
        self,
        window_size: int = 10,
        min_entropy_threshold: float = 0.65,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if window_size < 4 or not (0.0 < min_entropy_threshold < 1.0):
            raise ValueError("Invalid parameters for Market Depth Entropy Guard.")
        self._window = int(window_size)
        self._threshold = float(min_entropy_threshold)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._entropies: deque = deque(maxlen=window_size)
        self._blocked_until = 0.0
        self._blocked_until_sim = 0.0
        self._last_reason = ""

    def update(self, depth_sizes: List[float], timestamp: float) -> None:
        with self._lock:
            # Type and boolean validation
            if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
                self._block(time.monotonic(), _REASON_VAL)
                return
            if not isinstance(depth_sizes, (list, tuple)) or len(depth_sizes) < 2:
                self._block(timestamp, _REASON_VAL)
                return

            ts = float(timestamp)
            sizes: List[float] = []

            for x in depth_sizes:
                if isinstance(x, bool) or not isinstance(x, (int, float)):
                    self._block(ts, _REASON_VAL)
                    return
                val = float(x)
                if val <= 0:
                    self._block(ts, _REASON_VAL)
                    return
                sizes.append(val)

            total_q = sum(sizes)
            if total_q <= 0:
                self._block(ts, _REASON_VAL)
                return

            m = len(sizes)
            max_entropy = math.log(m)

            # Shannon entropy: - sum(p_k * ln(p_k))
            entropy = 0.0
            for q in sizes:
                p_k = q / total_q
                if p_k > 1e-12:
                    entropy -= p_k * math.log(p_k)

            h_norm = entropy / max_entropy
            self._entropies.append(h_norm)

            if len(self._entropies) >= self._window:
                avg_h = sum(self._entropies) / len(self._entropies)
                if avg_h <= self._threshold:
                    self._block(ts, _REASON_COLLAPSE)

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
            self._entropies.clear()
            self._blocked_until = 0.0
            self._blocked_until_sim = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
