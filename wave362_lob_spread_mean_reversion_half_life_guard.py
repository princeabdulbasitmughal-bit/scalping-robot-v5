"""
wave362_lob_spread_mean_reversion_half_life_guard.py
=====================================================
LOB Spread Mean-Reversion Half-Life Guard (Wave 362)

Algorithm:
  - Records spread_bps at each tick via update(bid, ask, timestamp).
  - Once rolling window (window_size ticks) is full, fits AR(1) via closed-form OLS:
        spread_t = mu + phi * spread_{t-1} + eps
  - Computes half-life = -log(2) / log(|phi|) in ticks.
  - Blocks when half_life > max_half_life_ticks  -> SLOW_SPREAD_REVERSION
    OR phi >= 1.0 (non-stationary / explosive)   -> EXPLOSIVE_SPREAD
  - Any invalid input is fail-closed              -> INPUT_VALIDATION_ERROR
  - Thread-safe via threading.RLock; cooldown uses time.monotonic().
"""

import math
import threading
import time

_VALID_REASONS = frozenset([
    "SLOW_SPREAD_REVERSION",
    "EXPLOSIVE_SPREAD",
    "INPUT_VALIDATION_ERROR",
])


class Wave362LobSpreadMeanReversionHalfLifeGuard:
    """LOB Spread Mean-Reversion Half-Life Guard."""

    def __init__(
        self,
        window_size: int = 20,
        max_half_life_ticks: float = 30.0,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if isinstance(window_size, bool) or not isinstance(window_size, int):
            raise TypeError("window_size must be a positive int")
        if window_size < 2:
            raise ValueError("window_size must be >= 2")

        if isinstance(max_half_life_ticks, bool) or not isinstance(
            max_half_life_ticks, (int, float)
        ):
            raise TypeError("max_half_life_ticks must be a positive number")
        if max_half_life_ticks <= 0:
            raise ValueError("max_half_life_ticks must be > 0")

        if isinstance(cooldown_seconds, bool) or not isinstance(
            cooldown_seconds, (int, float)
        ):
            raise TypeError("cooldown_seconds must be a non-negative number")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be >= 0")

        self._window_size = window_size
        self._max_half_life_ticks = float(max_half_life_ticks)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._spreads: list = []
        self._blocked_until: float = 0.0
        self._last_reason: str = ""
        self._last_timestamp = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def update(self, bid, ask, timestamp) -> None:
        """Ingest a new tick (bid, ask, timestamp) and evaluate guard logic."""
        with self._lock:
            # --- input validation (fail-closed) ---
            if isinstance(bid, bool) or not isinstance(bid, (int, float)):
                self._trigger_block("INPUT_VALIDATION_ERROR")
                return
            if isinstance(ask, bool) or not isinstance(ask, (int, float)):
                self._trigger_block("INPUT_VALIDATION_ERROR")
                return
            if isinstance(timestamp, bool) or not isinstance(
                timestamp, (int, float)
            ):
                self._trigger_block("INPUT_VALIDATION_ERROR")
                return
            if not math.isfinite(bid) or not math.isfinite(ask):
                self._trigger_block("INPUT_VALIDATION_ERROR")
                return
            if not math.isfinite(timestamp):
                self._trigger_block("INPUT_VALIDATION_ERROR")
                return
            if bid <= 0 or ask <= 0:
                self._trigger_block("INPUT_VALIDATION_ERROR")
                return
            if ask < bid:
                self._trigger_block("INPUT_VALIDATION_ERROR")
                return

            mid = (bid + ask) / 2.0
            if mid == 0:
                self._trigger_block("INPUT_VALIDATION_ERROR")
                return

            spread_bps = ((ask - bid) / mid) * 10000.0

            # Append and maintain rolling window
            self._spreads.append(spread_bps)
            if len(self._spreads) > self._window_size:
                self._spreads.pop(0)

            self._last_timestamp = timestamp

            # Need at least window_size observations
            if len(self._spreads) < self._window_size:
                return

            # Fit AR(1) via closed-form OLS
            phi, ok = self._fit_ar1(self._spreads)
            if not ok:
                # Degenerate data — treat as input validation error
                self._trigger_block("INPUT_VALIDATION_ERROR")
                return

            abs_phi = abs(phi)

            # Check explosive / non-stationary
            if phi >= 1.0:
                self._trigger_block("EXPLOSIVE_SPREAD")
                return

            # Check half-life (phi must be in (0, 1) exclusive for log to be valid)
            if abs_phi <= 0.0 or abs_phi >= 1.0:
                # abs_phi==0 => instant reversion, never block for this
                # abs_phi>=1 already handled above
                return

            half_life = -math.log(2.0) / math.log(abs_phi)
            if half_life > self._max_half_life_ticks:
                self._trigger_block("SLOW_SPREAD_REVERSION")

    def is_blocked(self, current_time: float = None) -> bool:
        """Return True if the guard is currently in a cooldown block."""
        with self._lock:
            t = current_time if current_time is not None else time.monotonic()
            return t < self._blocked_until

    def is_entry_blocked(self, bid, ask, ts) -> bool:
        """Convenience wrapper: update then return is_blocked."""
        self.update(bid, ask, ts)
        return self.is_blocked()

    def reset(self) -> None:
        """Clear all state: spread window, block, and last reason."""
        with self._lock:
            self._spreads.clear()
            self._blocked_until = 0.0
            self._last_reason = ""
            self._last_timestamp = None

    @property
    def last_reason(self) -> str:
        """Return the most recent blocking reason string."""
        with self._lock:
            return self._last_reason

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _trigger_block(self, reason: str) -> None:
        """Set blocked_until using monotonic clock and record reason."""
        self._blocked_until = time.monotonic() + self._cooldown_seconds
        self._last_reason = reason

    @staticmethod
    def _fit_ar1(series: list):
        """
        Fit AR(1): y_t = mu + phi * y_{t-1} via closed-form OLS.

        Returns (phi, True) on success, (0.0, False) on degenerate input.
        """
        n = len(series)
        if n < 2:
            return 0.0, False

        # x = series[:-1], y = series[1:]
        x = series[:-1]
        y = series[1:]
        m = len(x)  # m = n - 1

        sum_x = 0.0
        sum_y = 0.0
        sum_xx = 0.0
        sum_xy = 0.0

        for xi, yi in zip(x, y):
            sum_x += xi
            sum_y += yi
            sum_xx += xi * xi
            sum_xy += xi * yi

        denom = m * sum_xx - sum_x * sum_x
        if denom == 0.0:
            # Zero-variance constant spread: perfectly stable, phi ~ 0
            return 0.0, True

        phi = (m * sum_xy - sum_x * sum_y) / denom
        return phi, True
