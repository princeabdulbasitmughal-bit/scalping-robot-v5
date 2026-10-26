"""
wave360_lob_bid_ask_level_count_asymmetry_guard.py
---------------------------------------------------
WAVE 360 - LOB Bid-Ask Level Count Asymmetry Guard

Algorithm:
  At each tick receive n_bid_levels and n_ask_levels (integer counts of
  price levels on each side of the limit-order book).
  Compute level_ratio = n_bid_levels / max(n_ask_levels, 1).
  Maintain a rolling deque of the last window_size ratios.
  Block when rolling_mean(ratios) >= ratio_threshold  -> BID_LEVEL_DOMINANCE
       or when rolling_mean(ratios) <= 1/ratio_threshold -> ASK_LEVEL_DOMINANCE
  Any invalid input triggers an immediate block with INPUT_VALIDATION_ERROR.

Thread safety: threading.RLock() guards all shared state.
Cooldown: monotonic clock, _blocked_until = time.monotonic() + cooldown_seconds.
"""

import time
import threading
from collections import deque


class Wave360LobBidAskLevelCountAsymmetryGuard:
    """LOB Bid-Ask Level Count Asymmetry Guard (WAVE 360)."""

    REASON_BID_DOMINANCE = "BID_LEVEL_DOMINANCE"
    REASON_ASK_DOMINANCE = "ASK_LEVEL_DOMINANCE"
    REASON_INPUT_ERROR = "INPUT_VALIDATION_ERROR"

    def __init__(
        self,
        window_size: int = 15,
        ratio_threshold: float = 3.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        # --- parameter validation ---
        if not isinstance(window_size, int) or isinstance(window_size, bool):
            raise TypeError("window_size must be a positive int")
        if window_size < 1:
            raise ValueError("window_size must be >= 1")

        if isinstance(ratio_threshold, bool):
            raise TypeError("ratio_threshold must be a positive float")
        if not isinstance(ratio_threshold, (int, float)):
            raise TypeError("ratio_threshold must be a positive float")
        if ratio_threshold <= 1.0:
            raise ValueError("ratio_threshold must be > 1.0")

        if isinstance(cooldown_seconds, bool):
            raise TypeError("cooldown_seconds must be a non-negative float")
        if not isinstance(cooldown_seconds, (int, float)):
            raise TypeError("cooldown_seconds must be a non-negative float")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be >= 0")

        self._window_size = window_size
        self._ratio_threshold = float(ratio_threshold)
        self._inv_threshold = 1.0 / float(ratio_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._ratios: deque = deque(maxlen=window_size)
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, n_bid_levels, n_ask_levels, timestamp=None) -> None:
        """Ingest one tick of LOB level counts and update block state."""
        with self._lock:
            # --- input validation (fail-closed) ---
            if isinstance(n_bid_levels, bool) or not isinstance(n_bid_levels, int):
                self._trigger_block(self.REASON_INPUT_ERROR)
                return
            if isinstance(n_ask_levels, bool) or not isinstance(n_ask_levels, int):
                self._trigger_block(self.REASON_INPUT_ERROR)
                return
            if n_bid_levels < 0 or n_ask_levels < 0:
                self._trigger_block(self.REASON_INPUT_ERROR)
                return

            ratio = n_bid_levels / max(n_ask_levels, 1)
            self._ratios.append(ratio)

            if len(self._ratios) < self._window_size:
                # Window not yet filled; no block signal
                return

            mean_ratio = sum(self._ratios) / len(self._ratios)

            if mean_ratio >= self._ratio_threshold:
                self._trigger_block(self.REASON_BID_DOMINANCE)
            elif mean_ratio <= self._inv_threshold:
                self._trigger_block(self.REASON_ASK_DOMINANCE)
            else:
                # Healthy state - clear any prior one-shot block if cooldown elapsed
                if time.monotonic() >= self._blocked_until:
                    self._last_reason = ""

    def is_blocked(self, current_time: float = None) -> bool:
        """Return True if the guard is currently in cooldown."""
        with self._lock:
            t = current_time if current_time is not None else time.monotonic()
            return t < self._blocked_until

    def is_entry_blocked(self, bid, ask, ts=None) -> bool:
        """Delegate: block entry if the guard is blocked (bid/ask unused here)."""
        return self.is_blocked(current_time=ts)

    def reset(self) -> None:
        """Clear all rolling state and lift any active block."""
        with self._lock:
            self._ratios.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        """Human-readable reason for the most recent block."""
        with self._lock:
            return self._last_reason

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _trigger_block(self, reason: str) -> None:
        """Set block with monotonic cooldown. Caller must hold _lock."""
        self._blocked_until = time.monotonic() + self._cooldown_seconds
        self._last_reason = reason
