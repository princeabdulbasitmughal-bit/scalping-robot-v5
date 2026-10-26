"""
WAVE 350 -- LOB Order-Book Depth Imbalance Velocity Guard
==========================================================
Algorithm:
  - At each tick compute imbalance = (bid_size - ask_size) / (bid_size + ask_size)
    giving a value in [-1, +1].
  - velocity = imbalance_i - imbalance_{i-1}  (first difference)
  - Maintain a rolling deque of the last window_size velocities.
  - Block when rolling mean of |velocity| >= velocity_threshold.
Blocking reasons: DEPTH_IMBALANCE_VELOCITY_BREACH, INPUT_VALIDATION_ERROR
"""

import time
import threading
from collections import deque


class Wave350LobOrderBookDepthImbalanceVelocityGuard:
    """LOB Order-Book Depth Imbalance Velocity Guard (Wave 350)."""

    REASON_BREACH = "DEPTH_IMBALANCE_VELOCITY_BREACH"
    REASON_INPUT = "INPUT_VALIDATION_ERROR"

    def __init__(
        self,
        window_size: int = 15,
        velocity_threshold: float = 0.15,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if isinstance(window_size, bool) or not isinstance(window_size, int):
            raise TypeError("window_size must be a positive int")
        if window_size < 2:
            raise ValueError("window_size must be >= 2")
        if isinstance(velocity_threshold, bool) or not isinstance(
            velocity_threshold, (int, float)
        ):
            raise TypeError("velocity_threshold must be a positive number")
        if velocity_threshold <= 0:
            raise ValueError("velocity_threshold must be > 0")
        if isinstance(cooldown_seconds, bool) or not isinstance(
            cooldown_seconds, (int, float)
        ):
            raise TypeError("cooldown_seconds must be a positive number")
        if cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be > 0")

        self._window_size = window_size
        self._velocity_threshold = float(velocity_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._velocities: deque = deque(maxlen=window_size)
        self._last_imbalance: float | None = None
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    def reset(self) -> None:
        """Clear all rolling state and lift any active block."""
        with self._lock:
            self._velocities.clear()
            self._last_imbalance = None
            self._blocked_until = 0.0
            self._last_reason = ""

    def update(
        self,
        bid: float,
        ask: float,
        bid_size: float,
        ask_size: float,
        timestamp: float,
    ) -> None:
        """
        Ingest one order-book tick.

        Parameters
        ----------
        bid, ask        : best bid/ask prices (positive floats; unused in imbalance
                          math but validated for signal consistency)
        bid_size        : total size on the bid side (positive float)
        ask_size        : total size on the ask side (positive float)
        timestamp       : monotonic timestamp (positive float)
        """
        with self._lock:
            # --- Validation (fail-closed) ---
            for name, val in [
                ("bid", bid),
                ("ask", ask),
                ("bid_size", bid_size),
                ("ask_size", ask_size),
                ("timestamp", timestamp),
            ]:
                if isinstance(val, bool):
                    self._set_block(self.REASON_INPUT)
                    return
                if not isinstance(val, (int, float)):
                    self._set_block(self.REASON_INPUT)
                    return

            if bid <= 0 or ask <= 0:
                self._set_block(self.REASON_INPUT)
                return
            if bid_size <= 0 or ask_size <= 0:
                self._set_block(self.REASON_INPUT)
                return
            if timestamp <= 0:
                self._set_block(self.REASON_INPUT)
                return

            # --- Imbalance ---
            total = bid_size + ask_size
            imbalance = (bid_size - ask_size) / total  # in [-1, +1]

            # --- Velocity ---
            if self._last_imbalance is not None:
                velocity = imbalance - self._last_imbalance
                self._velocities.append(abs(velocity))

            self._last_imbalance = imbalance

            # --- Check threshold (only when window is full) ---
            if len(self._velocities) >= self._window_size:
                mean_abs_velocity = sum(self._velocities) / len(self._velocities)
                if mean_abs_velocity >= self._velocity_threshold:
                    self._set_block(self.REASON_BREACH)

    def is_blocked(self, current_time: float | None = None) -> bool:
        """Return True if a block is currently active."""
        if current_time is None:
            current_time = time.monotonic()
        with self._lock:
            return current_time < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: float) -> bool:
        """Convenience wrapper: validate price/ts then delegate to is_blocked."""
        if isinstance(bid, bool) or isinstance(ask, bool) or isinstance(ts, bool):
            with self._lock:
                self._set_block(self.REASON_INPUT)
            return True
        if (
            not isinstance(bid, (int, float))
            or not isinstance(ask, (int, float))
            or not isinstance(ts, (int, float))
        ):
            with self._lock:
                self._set_block(self.REASON_INPUT)
            return True
        if bid <= 0 or ask <= 0 or ts <= 0:
            with self._lock:
                self._set_block(self.REASON_INPUT)
            return True
        return self.is_blocked(current_time=ts)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_block(self, reason: str) -> None:
        """Set block (must be called with _lock held)."""
        self._blocked_until = time.monotonic() + self._cooldown_seconds
        self._last_reason = reason
