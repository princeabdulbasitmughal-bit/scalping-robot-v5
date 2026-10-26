# wave355_trade_flow_volume_weighted_arrival_rate_surge_guard.py
# WAVE 355 - Trade Flow Volume-Weighted Arrival Rate Surge Guard
# ASCII-only file. No live server calls.

import threading
import time
from collections import deque


class Wave355TradeFlowVolumeWeightedArrivalRateSurgeGuard:
    """
    Tracks Volume-Weighted Arrival Rate (VWAR) per trade tick and blocks when
    the current VWAR is a surge_multiple times larger than the rolling mean.

    Algorithm:
      VWAR_i       = volume_i / delta_t_i   (volume per second)
      rolling_mean = mean(last window_size VWARs)
      Block when: current_VWAR >= surge_multiple * rolling_mean AND rolling_mean > 0

    Blocking reasons: VWAR_SURGE_DETECTED, INPUT_VALIDATION_ERROR
    """

    REASON_SURGE       = "VWAR_SURGE_DETECTED"
    REASON_INPUT_ERROR = "INPUT_VALIDATION_ERROR"

    def __init__(
        self,
        window_size: int = 15,
        surge_multiple: float = 5.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if not isinstance(window_size, int) or window_size < 1:
            raise ValueError("window_size must be a positive int")
        if not isinstance(surge_multiple, (int, float)) or surge_multiple <= 0:
            raise ValueError("surge_multiple must be a positive number")
        if not isinstance(cooldown_seconds, (int, float)) or cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be a non-negative number")

        self._window_size      = window_size
        self._surge_multiple   = float(surge_multiple)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock                   = threading.RLock()
        self._vwars: deque           = deque(maxlen=window_size)
        self._prev_timestamp: float | None = None
        self._blocked_until: float   = 0.0
        self._last_reason: str       = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, volume: float, timestamp: float) -> None:
        """
        Ingest one trade tick.  Blocks on any invalid input.

        Parameters
        ----------
        volume    : traded volume for this tick (positive float)
        timestamp : monotonic tick timestamp (non-negative float);
                    must be strictly greater than the previous timestamp
                    (zero delta-t is treated as invalid to avoid division by zero)
        """
        with self._lock:
            # --- validation (bool before numeric) ---
            for name, val in [("volume", volume), ("timestamp", timestamp)]:
                if isinstance(val, bool):
                    self._block_now(self.REASON_INPUT_ERROR)
                    return
                if not isinstance(val, (int, float)):
                    self._block_now(self.REASON_INPUT_ERROR)
                    return

            volume    = float(volume)
            timestamp = float(timestamp)

            if volume <= 0:
                self._block_now(self.REASON_INPUT_ERROR)
                return
            if timestamp < 0:
                self._block_now(self.REASON_INPUT_ERROR)
                return

            # --- compute delta_t ---
            if self._prev_timestamp is None:
                # First tick: store timestamp, cannot yet compute VWAR.
                self._prev_timestamp = timestamp
                return

            delta_t = timestamp - self._prev_timestamp
            if delta_t <= 0:
                # Non-monotonic or duplicate timestamp.
                self._block_now(self.REASON_INPUT_ERROR)
                return

            self._prev_timestamp = timestamp

            # --- compute VWAR and check surge against baseline ---
            current_vwar = volume / delta_t

            if len(self._vwars) >= 1:
                baseline_mean = sum(self._vwars) / len(self._vwars)
                if baseline_mean > 0 and current_vwar >= self._surge_multiple * baseline_mean:
                    self._block_now(self.REASON_SURGE)

            self._vwars.append(current_vwar)

    def is_blocked(self, current_time: float | None = None) -> bool:
        """Return True if currently within a cooldown block period."""
        with self._lock:
            t = current_time if current_time is not None else time.monotonic()
            return t < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: float) -> bool:
        """Convenience: block check that accepts positional quote params."""
        return self.is_blocked(current_time=ts)

    def reset(self) -> None:
        """Clear all rolling state and lift any active block."""
        with self._lock:
            self._vwars.clear()
            self._prev_timestamp  = None
            self._blocked_until   = 0.0
            self._last_reason     = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _block_now(self, reason: str) -> None:
        """Set block; monotonic cooldown. Caller must hold self._lock."""
        self._blocked_until = time.monotonic() + self._cooldown_seconds
        self._last_reason   = reason
