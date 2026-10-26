# wave367_trade_flow_bulk_trade_accumulation_guard.py
# Trade Flow Bulk Trade Accumulation Guard
# Blocks when consecutive same-direction large trades signal institutional accumulation.
# ASCII-only content. No live server calls.

import math
import threading
import time


_VALID_SIDES = frozenset(("buy", "sell"))


class Wave367TradeFlowBulkTradeAccumulationGuard:
    """
    Trade Flow Bulk Trade Accumulation Guard (Wave 367).

    Detects consecutive trades in the SAME direction where EACH trade
    volume >= large_trade_threshold.  When bulk_count reaches max_bulk_count
    the guard blocks, indicating potential institutional accumulation / ramping.

    Blocking reasons:
        BULK_ACCUMULATION_DETECTED  -- bulk_count >= max_bulk_count
        INPUT_VALIDATION_ERROR      -- any invalid argument supplied to update()

    Thread-safe via threading.RLock().
    """

    REASON_BULK = "BULK_ACCUMULATION_DETECTED"
    REASON_INPUT_ERROR = "INPUT_VALIDATION_ERROR"

    def __init__(
        self,
        large_trade_threshold: float = 100.0,
        max_bulk_count: int = 5,
        cooldown_seconds: float = 60.0,
    ):
        # --- constructor validation ---
        if isinstance(large_trade_threshold, bool) or not isinstance(
            large_trade_threshold, (int, float)
        ):
            raise TypeError("large_trade_threshold must be a positive number")
        if not math.isfinite(large_trade_threshold) or large_trade_threshold <= 0:
            raise ValueError("large_trade_threshold must be a finite positive number")

        if isinstance(max_bulk_count, bool) or not isinstance(max_bulk_count, int):
            raise TypeError("max_bulk_count must be a positive int")
        if max_bulk_count < 1:
            raise ValueError("max_bulk_count must be >= 1")

        if isinstance(cooldown_seconds, bool) or not isinstance(cooldown_seconds, (int, float)):
            raise TypeError("cooldown_seconds must be a positive number")
        if not math.isfinite(cooldown_seconds) or cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be a finite positive number")

        self._large_trade_threshold = float(large_trade_threshold)
        self._max_bulk_count = max_bulk_count
        self._cooldown_seconds = float(cooldown_seconds)
        self._lock = threading.RLock()

        # State
        self._bulk_count = 0
        self._current_side = None         # "buy" or "sell" for the ongoing streak
        self._blocked_until = 0.0         # monotonic deadline
        self._last_reason = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, volume, side, timestamp=None):
        """
        Process one trade event.

        Parameters
        ----------
        volume    : numeric  -- trade size (must be finite positive number)
        side      : str      -- "buy" or "sell" (case-sensitive)
        timestamp            -- ignored internally; kept for interface uniformity
        """
        with self._lock:
            # --- input validation (fail-closed) ---
            if isinstance(volume, bool) or not isinstance(volume, (int, float)):
                self._trigger_block(self.REASON_INPUT_ERROR)
                return
            volume = float(volume)
            if not math.isfinite(volume) or volume <= 0:
                self._trigger_block(self.REASON_INPUT_ERROR)
                return

            if not isinstance(side, str) or side not in _VALID_SIDES:
                self._trigger_block(self.REASON_INPUT_ERROR)
                return

            # --- bulk accumulation logic ---
            is_large = volume >= self._large_trade_threshold

            if is_large:
                if self._current_side == side:
                    # Continuation of same-direction large-trade streak
                    self._bulk_count += 1
                else:
                    # New direction or first large trade: start fresh streak at 1
                    self._current_side = side
                    self._bulk_count = 1
            else:
                # Small trade breaks any existing streak
                self._bulk_count = 0
                self._current_side = None

            # --- threshold check ---
            if self._bulk_count >= self._max_bulk_count:
                self._trigger_block(self.REASON_BULK)

    def is_blocked(self, current_time=None):
        """Return True if the guard is currently blocking."""
        t = current_time if current_time is not None else time.monotonic()
        with self._lock:
            return t < self._blocked_until

    def is_entry_blocked(self, bid, ask, ts=None):
        """
        Convenience entry-check: validates bid/ask inputs and delegates
        to is_blocked().  Returns True (block) on invalid inputs or if
        the guard cooldown is active.
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
            self._bulk_count = 0
            self._current_side = None
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
