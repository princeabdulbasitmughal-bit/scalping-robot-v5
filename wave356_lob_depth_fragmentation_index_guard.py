# wave356_lob_depth_fragmentation_index_guard.py
# Wave 356 - LOB Depth Fragmentation Index Guard
# ASCII-only source file

import threading
import time
from collections import deque

LOB_FRAGMENTATION_BREACH = "LOB_FRAGMENTATION_BREACH"
INPUT_VALIDATION_ERROR = "INPUT_VALIDATION_ERROR"


class Wave356LOBDepthFragmentationIndexGuard:
    """
    Guard that measures LOB depth fragmentation on each tick.

    Fragmentation index = 1 - (max_size / total_size) in [0, 1].
    A value of 1 means fully fragmented (no dominant level).
    Blocks when the rolling mean of the fragmentation index exceeds
    fragmentation_threshold for at least window_size ticks.
    """

    def __init__(
        self,
        window_size: int = 15,
        fragmentation_threshold: float = 0.85,
        cooldown_seconds: float = 45.0,
    ):
        if not isinstance(window_size, int) or window_size < 1:
            raise ValueError("window_size must be a positive integer")
        if not isinstance(fragmentation_threshold, (int, float)) or not (
            0.0 <= fragmentation_threshold <= 1.0
        ):
            raise ValueError("fragmentation_threshold must be a float in [0, 1]")
        if not isinstance(cooldown_seconds, (int, float)) or cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be a non-negative number")

        self._window_size = window_size
        self._fragmentation_threshold = float(fragmentation_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._indices: deque = deque(maxlen=window_size)
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def update(self, levels: list, timestamp) -> None:
        """
        Feed one side of the order book.

        Parameters
        ----------
        levels : list of (price, size) tuples
            At least one level required; sizes must be strictly positive.
        timestamp : numeric (monotonic seconds) or any comparable value
            Used only for external bookkeeping; guard uses time.monotonic()
            for its own cooldown logic.
        """
        with self._lock:
            # --- validate levels container ---------------------------------
            if isinstance(levels, bool) or not isinstance(levels, list):
                self._trigger_block(INPUT_VALIDATION_ERROR)
                return

            if len(levels) == 0:
                self._trigger_block(INPUT_VALIDATION_ERROR)
                return

            # --- validate each (price, size) pair --------------------------
            sizes = []
            for item in levels:
                if (
                    isinstance(item, bool)
                    or not isinstance(item, (tuple, list))
                    or len(item) != 2
                ):
                    self._trigger_block(INPUT_VALIDATION_ERROR)
                    return
                price, size = item
                if isinstance(price, bool) or not isinstance(price, (int, float)):
                    self._trigger_block(INPUT_VALIDATION_ERROR)
                    return
                if isinstance(size, bool) or not isinstance(size, (int, float)):
                    self._trigger_block(INPUT_VALIDATION_ERROR)
                    return
                if size <= 0.0:
                    self._trigger_block(INPUT_VALIDATION_ERROR)
                    return
                sizes.append(float(size))

            # --- compute fragmentation index --------------------------------
            total_size = sum(sizes)
            max_size = max(sizes)
            frag_index = 1.0 - (max_size / total_size)

            self._indices.append(frag_index)

            # --- check threshold only when window is full ------------------
            if len(self._indices) >= self._window_size:
                rolling_mean = sum(self._indices) / len(self._indices)
                if rolling_mean >= self._fragmentation_threshold:
                    self._trigger_block(LOB_FRAGMENTATION_BREACH)

    def is_blocked(self, current_time: float = None) -> bool:
        """Return True if the guard is currently in its cooldown window."""
        with self._lock:
            t = time.monotonic() if current_time is None else current_time
            return t < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts=None) -> bool:
        """
        Convenience wrapper for entry checks.
        Delegates to is_blocked(); bid/ask/ts are unused but validated.
        """
        with self._lock:
            if isinstance(bid, bool) or not isinstance(bid, (int, float)):
                self._trigger_block(INPUT_VALIDATION_ERROR)
                return True
            if isinstance(ask, bool) or not isinstance(ask, (int, float)):
                self._trigger_block(INPUT_VALIDATION_ERROR)
                return True
            return self.is_blocked(current_time=ts)

    def reset(self) -> None:
        """Clear all state: deque, cooldown, and last reason."""
        with self._lock:
            self._indices.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    @property
    def last_reason(self) -> str:
        """The most recent blocking reason string."""
        with self._lock:
            return self._last_reason

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _trigger_block(self, reason: str) -> None:
        """Set cooldown and record reason (must be called with lock held)."""
        self._blocked_until = time.monotonic() + self._cooldown_seconds
        self._last_reason = reason
