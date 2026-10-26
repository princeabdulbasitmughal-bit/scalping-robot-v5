# wave366_lob_top_of_book_persistence_guard.py
# LOB Top-of-Book Persistence Guard
# Blocks when the best bid/ask remains unchanged for too many consecutive ticks.
# ASCII-only content. No live server calls.

import threading
import time


class Wave366LobTopOfBookPersistenceGuard:
    """
    LOB Top-of-Book Persistence Guard (Wave 366).

    Tracks consecutive ticks where the top-of-book (best bid, best ask)
    remains UNCHANGED.  When persistence_count reaches max_persistence_ticks
    the guard blocks, indicating a stale top-of-book / lack of liquidity update.

    Blocking reasons:
        TOP_OF_BOOK_STALENESS   -- persistence_count >= max_persistence_ticks
        INPUT_VALIDATION_ERROR  -- any invalid argument supplied to update()

    Thread-safe via threading.RLock().
    """

    REASON_STALENESS = "TOP_OF_BOOK_STALENESS"
    REASON_INPUT_ERROR = "INPUT_VALIDATION_ERROR"

    def __init__(self, max_persistence_ticks: int = 20, cooldown_seconds: float = 45.0):
        if isinstance(max_persistence_ticks, bool) or not isinstance(max_persistence_ticks, int):
            raise TypeError("max_persistence_ticks must be a positive int")
        if max_persistence_ticks < 1:
            raise ValueError("max_persistence_ticks must be >= 1")
        if isinstance(cooldown_seconds, bool) or not isinstance(cooldown_seconds, (int, float)):
            raise TypeError("cooldown_seconds must be a positive number")
        if cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be > 0")

        self._max_persistence_ticks = max_persistence_ticks
        self._cooldown_seconds = float(cooldown_seconds)
        self._lock = threading.RLock()

        # State
        self._prev_bid = None
        self._prev_ask = None
        self._persistence_count = 0
        self._blocked_until = 0.0          # monotonic deadline
        self._last_reason = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, bid, ask, timestamp=None):
        """
        Process one top-of-book tick.

        Parameters
        ----------
        bid : float-like  -- current best bid price (must be finite positive number)
        ask : float-like  -- current best ask price (must be finite positive number,
                             and ask > bid)
        timestamp         -- ignored internally; kept for interface uniformity
        """
        with self._lock:
            # --- input validation (fail-closed) ---
            if isinstance(bid, bool) or not isinstance(bid, (int, float)):
                self._trigger_block(self.REASON_INPUT_ERROR)
                return
            if isinstance(ask, bool) or not isinstance(ask, (int, float)):
                self._trigger_block(self.REASON_INPUT_ERROR)
                return
            bid = float(bid)
            ask = float(ask)
            import math
            if not math.isfinite(bid) or bid <= 0:
                self._trigger_block(self.REASON_INPUT_ERROR)
                return
            if not math.isfinite(ask) or ask <= 0:
                self._trigger_block(self.REASON_INPUT_ERROR)
                return
            if ask <= bid:
                self._trigger_block(self.REASON_INPUT_ERROR)
                return

            # --- first tick: just record ---
            if self._prev_bid is None:
                self._prev_bid = bid
                self._prev_ask = ask
                self._persistence_count = 0
                return

            # --- persistence logic ---
            if bid == self._prev_bid and ask == self._prev_ask:
                self._persistence_count += 1
            else:
                self._persistence_count = 0
                self._prev_bid = bid
                self._prev_ask = ask

            # --- threshold check ---
            if self._persistence_count >= self._max_persistence_ticks:
                self._trigger_block(self.REASON_STALENESS)

    def is_blocked(self, current_time=None):
        """Return True if the guard is currently blocking."""
        t = current_time if current_time is not None else time.monotonic()
        with self._lock:
            return t < self._blocked_until

    def is_entry_blocked(self, bid, ask, ts=None):
        """
        Convenience entry-check: validates inputs and delegates to is_blocked().
        Returns True (block) on invalid inputs or if guard is active.
        """
        with self._lock:
            if isinstance(bid, bool) or not isinstance(bid, (int, float)):
                return True
            if isinstance(ask, bool) or not isinstance(ask, (int, float)):
                return True
            return self.is_blocked()

    def reset(self):
        """Clear all state; guard returns to open (non-blocking) state."""
        with self._lock:
            self._prev_bid = None
            self._prev_ask = None
            self._persistence_count = 0
            self._blocked_until = 0.0
            self._last_reason = None

    @property
    def last_reason(self):
        """Last blocking reason string, or None if never blocked."""
        with self._lock:
            return self._last_reason

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _trigger_block(self, reason: str):
        """Arm the cooldown window (monotonic) and record reason."""
        self._blocked_until = time.monotonic() + self._cooldown_seconds
        self._last_reason = reason
