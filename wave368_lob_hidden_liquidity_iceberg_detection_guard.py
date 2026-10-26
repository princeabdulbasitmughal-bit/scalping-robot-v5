"""
wave368_lob_hidden_liquidity_iceberg_detection_guard.py
WAVE 368 -- LOB Hidden Liquidity Iceberg Detection Guard

Algorithm:
  At each tick, after a trade has occurred, compare current_bid_size with
  prev_bid_size. An iceberg_signal fires when the bid size first decreased
  (trade consumed visible liquidity) and then recovered >= recovery_ratio *
  original size within the same tick pair. Signals are accumulated over a
  rolling deque of window_size ticks. Blocking triggers when the count of
  iceberg signals in the window reaches min_iceberg_count.

Blocking reasons: ICEBERG_PATTERN_DETECTED, INPUT_VALIDATION_ERROR
Thread safety: threading.RLock()
"""

import collections
import threading
import time


class Wave368LobHiddenLiquidityIcebergDetectionGuard:
    """LOB Hidden Liquidity Iceberg Detection Guard (WAVE 368)."""

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        window_size: int = 20,
        recovery_ratio: float = 0.8,
        min_iceberg_count: int = 3,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if not isinstance(window_size, int) or isinstance(window_size, bool):
            raise TypeError("window_size must be int")
        if window_size < 1:
            raise ValueError("window_size must be >= 1")

        if isinstance(recovery_ratio, bool):
            raise TypeError("recovery_ratio must be float or int")
        if not isinstance(recovery_ratio, (int, float)):
            raise TypeError("recovery_ratio must be float or int")
        if recovery_ratio <= 0.0 or recovery_ratio > 1.0:
            raise ValueError("recovery_ratio must be in (0, 1]")

        if not isinstance(min_iceberg_count, int) or isinstance(min_iceberg_count, bool):
            raise TypeError("min_iceberg_count must be int")
        if min_iceberg_count < 1:
            raise ValueError("min_iceberg_count must be >= 1")

        if isinstance(cooldown_seconds, bool):
            raise TypeError("cooldown_seconds must be float or int")
        if not isinstance(cooldown_seconds, (int, float)):
            raise TypeError("cooldown_seconds must be float or int")
        if cooldown_seconds < 0.0:
            raise ValueError("cooldown_seconds must be >= 0")

        self._window_size = window_size
        self._recovery_ratio = float(recovery_ratio)
        self._min_iceberg_count = min_iceberg_count
        self._cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._signals: collections.deque = collections.deque(maxlen=window_size)

        # State tracking across ticks
        self._prev_bid_size: float | None = None
        self._prev_bid_size_before_trade: float | None = None
        self._trade_pending: bool = False

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
        with self._lock:
            self._signals.clear()
            self._prev_bid_size = None
            self._prev_bid_size_before_trade = None
            self._trade_pending = False
            self._blocked_until = 0.0
            self._last_reason = ""

    def update(
        self,
        bid_size: float,
        ask_size: float,
        trade_occurred: bool,
        timestamp: float,
    ) -> None:
        """Ingest one market tick.

        Parameters
        ----------
        bid_size      : visible best-bid quantity (>= 0)
        ask_size      : visible best-ask quantity (>= 0)
        trade_occurred: True when a trade just consumed order-book liquidity
        timestamp     : monotonic tick timestamp (float)
        """
        with self._lock:
            # --- Validate inputs (fail-closed) ---
            if not self._validate(bid_size, ask_size, trade_occurred, timestamp):
                return

            iceberg_signal = 0

            if trade_occurred:
                # Record the pre-trade bid size; recovery will be checked
                # on the NEXT tick (after the book has had a chance to refill).
                self._trade_pending = True
                self._prev_bid_size_before_trade = self._prev_bid_size

            elif self._trade_pending and self._prev_bid_size_before_trade is not None:
                # Post-trade tick: check for iceberg refill
                original = self._prev_bid_size_before_trade
                if original is not None and original > 0:
                    # Mid-tick bid_size must have first dropped (trade_occurred
                    # caused decrease from original to prev_bid_size) then
                    # recovered to >= recovery_ratio * original.
                    dropped = (
                        self._prev_bid_size is not None
                        and self._prev_bid_size < original
                    )
                    recovered = bid_size >= self._recovery_ratio * original
                    if dropped and recovered:
                        iceberg_signal = 1
                self._trade_pending = False
                self._prev_bid_size_before_trade = None

            self._signals.append(iceberg_signal)
            self._prev_bid_size = bid_size

            # Check trigger
            if sum(self._signals) >= self._min_iceberg_count:
                self._blocked_until = time.monotonic() + self._cooldown_seconds
                self._last_reason = "ICEBERG_PATTERN_DETECTED"

    def is_blocked(self, current_time: float | None = None) -> bool:
        with self._lock:
            t = current_time if current_time is not None else time.monotonic()
            return t < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: float) -> bool:
        return self.is_blocked(current_time=ts)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate(
        self,
        bid_size: float,
        ask_size: float,
        trade_occurred: bool,
        timestamp: float,
    ) -> bool:
        """Return True if valid; False and block if invalid."""
        # trade_occurred: must be bool (check bool BEFORE numeric)
        if not isinstance(trade_occurred, bool):
            self._blocked_until = time.monotonic() + self._cooldown_seconds
            self._last_reason = "INPUT_VALIDATION_ERROR"
            return False

        for name, val in [("bid_size", bid_size), ("ask_size", ask_size), ("timestamp", timestamp)]:
            if isinstance(val, bool):
                self._blocked_until = time.monotonic() + self._cooldown_seconds
                self._last_reason = "INPUT_VALIDATION_ERROR"
                return False
            if not isinstance(val, (int, float)):
                self._blocked_until = time.monotonic() + self._cooldown_seconds
                self._last_reason = "INPUT_VALIDATION_ERROR"
                return False
            if val != val:  # NaN check
                self._blocked_until = time.monotonic() + self._cooldown_seconds
                self._last_reason = "INPUT_VALIDATION_ERROR"
                return False

        if bid_size < 0 or ask_size < 0:
            self._blocked_until = time.monotonic() + self._cooldown_seconds
            self._last_reason = "INPUT_VALIDATION_ERROR"
            return False

        return True
