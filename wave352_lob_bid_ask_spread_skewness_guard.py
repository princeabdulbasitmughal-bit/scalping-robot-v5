"""
wave352_lob_bid_ask_spread_skewness_guard.py
LOB Bid-Ask Spread Skewness Guard (Wave 352)

Algorithm:
  - Each tick: spread_bps = (ask - bid) / mid * 10000
  - Rolling window of last window_size spreads
  - Pearson second skewness: (mean - median) / std
  - Block when |skewness| >= skewness_threshold
  - Reasons: SPREAD_DISTRIBUTION_SKEWED, INSUFFICIENT_VARIANCE, INPUT_VALIDATION_ERROR
"""

import math
import threading
import time
import statistics

_SENTINEL = object()


class Wave352LobBidAskSpreadSkewnessGuard:
    """LOB Bid-Ask Spread Skewness Guard -- Wave 352."""

    def __init__(
        self,
        window_size: int = 20,
        skewness_threshold: float = 1.5,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if not isinstance(window_size, int) or isinstance(window_size, bool):
            raise TypeError("window_size must be a positive int")
        if window_size < 2:
            raise ValueError("window_size must be >= 2")
        if isinstance(skewness_threshold, bool):
            raise TypeError("skewness_threshold must be a positive float/int")
        if not isinstance(skewness_threshold, (int, float)):
            raise TypeError("skewness_threshold must be a positive float/int")
        if skewness_threshold <= 0:
            raise ValueError("skewness_threshold must be > 0")
        if isinstance(cooldown_seconds, bool):
            raise TypeError("cooldown_seconds must be a positive float/int")
        if not isinstance(cooldown_seconds, (int, float)):
            raise TypeError("cooldown_seconds must be a positive float/int")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be >= 0")

        self._window_size = window_size
        self._skewness_threshold = float(skewness_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._spreads: list = []
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, bid, ask, timestamp=None) -> None:  # noqa: ANN001
        """Record a new tick and evaluate skewness."""
        with self._lock:
            # --- input validation (fail-closed) ---
            if isinstance(bid, bool) or not isinstance(bid, (int, float)):
                self._block("INPUT_VALIDATION_ERROR")
                return
            if isinstance(ask, bool) or not isinstance(ask, (int, float)):
                self._block("INPUT_VALIDATION_ERROR")
                return
            if bid <= 0 or ask <= 0:
                self._block("INPUT_VALIDATION_ERROR")
                return
            if ask < bid:
                self._block("INPUT_VALIDATION_ERROR")
                return

            mid = (bid + ask) / 2.0
            if mid == 0.0:
                self._block("INPUT_VALIDATION_ERROR")
                return

            spread_bps = (ask - bid) / mid * 10_000.0

            self._spreads.append(spread_bps)
            if len(self._spreads) > self._window_size:
                self._spreads.pop(0)

            if len(self._spreads) < self._window_size:
                # window not yet full -- do not block
                return

            self._evaluate()

    def is_blocked(self, current_time=None) -> bool:
        """Return True if the guard is currently blocking."""
        with self._lock:
            t = time.monotonic() if current_time is None else current_time
            return t < self._blocked_until

    def is_entry_blocked(self, bid, ask, ts=None) -> bool:
        """Convenience: update then check block state."""
        self.update(bid, ask, ts)
        return self.is_blocked()

    def reset(self) -> None:
        """Clear all state."""
        with self._lock:
            self._spreads.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        """Return the reason for the most recent block (empty if never blocked)."""
        with self._lock:
            return self._last_reason

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _block(self, reason: str) -> None:
        self._blocked_until = time.monotonic() + self._cooldown_seconds
        self._last_reason = reason

    def _evaluate(self) -> None:
        data = self._spreads  # already length == window_size
        n = len(data)
        mean_val = sum(data) / n
        m2 = sum((x - mean_val) ** 2 for x in data) / n
        std_val = math.sqrt(m2)

        if std_val < 1e-6:
            return  # Uniform distribution, zero skewness -> do not block

        m3 = sum((x - mean_val) ** 3 for x in data) / n
        skewness = m3 / (std_val ** 3)

        if abs(skewness) >= self._skewness_threshold:
            self._block("SPREAD_DISTRIBUTION_SKEWED")
