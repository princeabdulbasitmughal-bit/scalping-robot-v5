"""
wave364_lob_quote_update_entropy_guard.py
LOB Quote Update Entropy Guard -- Batch 303, Wave 364

Algorithm:
  - Accepts LOB update events typed as one of four labels:
    INSERT_BID, CANCEL_BID, INSERT_ASK, CANCEL_ASK
  - Maintains a rolling deque of the last window_size event-type labels
  - Computes Shannon entropy H = -sum(p_i * log2(p_i)) over the 4 buckets
    from the current window's frequency counts
  - Blocks when H <= low_entropy_threshold (overly concentrated event stream
    signals potential spoofing / quote-stuffing manipulation)
  - Blocking reasons: LOW_QUOTE_ENTROPY, INPUT_VALIDATION_ERROR
  - Thread-safe via threading.RLock; cooldown is monotonic
"""

import math
import threading
import time
from collections import deque

VALID_EVENT_TYPES = frozenset(
    {"INSERT_BID", "CANCEL_BID", "INSERT_ASK", "CANCEL_ASK"}
)

REASON_LOW_ENTROPY = "LOW_QUOTE_ENTROPY"
REASON_VALIDATION = "INPUT_VALIDATION_ERROR"


class Wave364LOBQuoteUpdateEntropyGuard:
    """LOB Quote Update Entropy Guard.

    Parameters
    ----------
    window_size : int
        Number of recent LOB events kept in the rolling window.
    low_entropy_threshold : float
        Shannon-entropy threshold (bits).  Block when H <= this value.
    cooldown_seconds : float
        Minimum duration (monotonic seconds) the guard stays blocked
        after a trigger.
    """

    def __init__(
        self,
        window_size: int = 30,
        low_entropy_threshold: float = 1.0,
        cooldown_seconds: float = 45.0,
    ):
        # --- validate constructor args ---
        if isinstance(window_size, bool) or not isinstance(window_size, int):
            raise TypeError("window_size must be a positive int")
        if window_size < 1:
            raise ValueError("window_size must be >= 1")
        if isinstance(low_entropy_threshold, bool) or not isinstance(
            low_entropy_threshold, (int, float)
        ):
            raise TypeError("low_entropy_threshold must be numeric")
        if isinstance(cooldown_seconds, bool) or not isinstance(
            cooldown_seconds, (int, float)
        ):
            raise TypeError("cooldown_seconds must be numeric")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be >= 0")

        self._window_size = window_size
        self._low_entropy_threshold = float(low_entropy_threshold)
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._events: deque = deque(maxlen=window_size)
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    def reset(self) -> None:
        """Clear all state; guard returns to unblocked."""
        with self._lock:
            self._events.clear()
            self._blocked_until = 0.0
            self._last_reason = ""

    def update(self, event_type: str, timestamp) -> None:
        """Record one LOB update event.

        Parameters
        ----------
        event_type : str
            One of INSERT_BID, CANCEL_BID, INSERT_ASK, CANCEL_ASK.
        timestamp :
            Opaque timestamp (stored but not used for internal logic).
        """
        with self._lock:
            # --- input validation (fail-closed) ---
            if isinstance(event_type, bool) or not isinstance(event_type, str):
                self._trigger(REASON_VALIDATION)
                return
            if event_type not in VALID_EVENT_TYPES:
                self._trigger(REASON_VALIDATION)
                return
            if isinstance(timestamp, bool):
                self._trigger(REASON_VALIDATION)
                return
            if timestamp is None:
                self._trigger(REASON_VALIDATION)
                return

            self._events.append(event_type)
            self._evaluate()

    def is_blocked(self, current_time: float = None) -> bool:
        """Return True if the guard is currently blocking trade entry."""
        with self._lock:
            t = current_time if current_time is not None else time.monotonic()
            return t < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts) -> bool:
        """Convenience wrapper used by the execution layer.

        Delegates to is_blocked(); bid/ask/ts are accepted for API
        compatibility but not evaluated here.
        """
        return self.is_blocked()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _shannon_entropy(self) -> float:
        """Compute Shannon entropy (bits) over the 4 event-type buckets."""
        counts: dict = {}
        for ev in self._events:
            counts[ev] = counts.get(ev, 0) + 1
        n = len(self._events)
        if n == 0:
            return 2.0  # full entropy for empty window -> never block
        entropy = 0.0
        for bucket in VALID_EVENT_TYPES:
            c = counts.get(bucket, 0)
            if c > 0:
                p = c / n
                entropy -= p * math.log2(p)
        return entropy

    def _evaluate(self) -> None:
        """Check entropy and trigger block if threshold is breached."""
        if len(self._events) < self._window_size:
            return  # window not yet full -- no-block until warm
        h = self._shannon_entropy()
        if h <= self._low_entropy_threshold:
            self._trigger(REASON_LOW_ENTROPY)

    def _trigger(self, reason: str) -> None:
        """Set blocked-until and record reason (monotonic cooldown)."""
        self._blocked_until = time.monotonic() + self._cooldown_seconds
        self._last_reason = reason
