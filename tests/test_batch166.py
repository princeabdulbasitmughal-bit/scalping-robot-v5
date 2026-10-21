"""
tests/test_batch166.py
-----------------------
Unit tests for Batch 166 wave modules:
  - wave98_session_volatility_guard  (5 tests)
  - wave99_max_trade_count_guard     (5 tests)

Baseline before this batch: 1,903 passed, 1 skipped
Expected after: 1,913 passed, 1 skipped
"""

import math
import time
import threading
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave98_session_volatility_guard as w98
import wave99_max_trade_count_guard as w99


# ===========================================================================
# wave98 — Session Volatility Guard (5 tests)
# ===========================================================================

class TestWave98SessionVolatilityGuard:

    def setup_method(self):
        w98.reset()

    # -- T1: Not blocked before MIN_SAMPLES warmup --
    def test_not_blocked_before_warmup(self):
        """Fewer than MIN_SAMPLES prices must never trigger a block."""
        for i in range(w98.MIN_SAMPLES - 1):
            # Large swing prices, but below warmup count
            w98.update(1.1000 + i * 0.01)
        assert w98.is_entry_blocked() is False

    # -- T2: Blocked when std-dev of returns exceeds MAX_VOLATILITY --
    def test_blocked_on_high_volatility(self):
        """Prices that alternate up/down 1.5% produce high std-dev -> block."""
        # Alternating +1.5% / -1.5% swings produce std-dev >> 0.2% threshold
        price = 1.0
        direction = 1
        for _ in range(w98.WINDOW_SIZE):
            w98.update(price)
            price *= (1.0 + direction * 0.015)   # +1.5% then -1.5% alternating
            direction *= -1
        assert w98.is_entry_blocked() is True

    # -- T3: Not blocked when price is stable (near-zero volatility) --
    def test_not_blocked_on_stable_prices(self):
        """Flat/near-flat prices produce near-zero std-dev — must not block."""
        for _ in range(w98.WINDOW_SIZE):
            w98.update(1.10000)   # constant price → zero log-returns
        assert w98.is_entry_blocked() is False

    # -- T4: Invalid inputs are silently ignored --
    def test_invalid_inputs_ignored(self):
        """Booleans, NaN, Inf, zero, negative prices must be rejected."""
        w98.update(True)
        w98.update(False)
        w98.update(float("nan"))
        w98.update(float("inf"))
        w98.update(float("-inf"))
        w98.update(0.0)
        w98.update(-1.5)
        w98.update("1.10")   # type: ignore
        w98.update(None)     # type: ignore
        assert w98.is_entry_blocked() is False

    # -- T5: reset() clears block and price history --
    def test_reset_clears_state(self):
        """After reset(), guard is unblocked and prices deque is cleared."""
        with w98._lock:
            w98._blocked_until = time.monotonic() + 999.0
        assert w98.is_entry_blocked() is True
        w98.reset()
        assert w98.is_entry_blocked() is False
        with w98._lock:
            assert len(w98._prices) == 0


# ===========================================================================
# wave99 — Max Trade Count Guard (5 tests)
# ===========================================================================

class TestWave99MaxTradeCountGuard:

    def setup_method(self):
        w99.reset()

    # -- T1: Not blocked below MAX_TRADES --
    def test_not_blocked_below_max(self):
        """Opening fewer than MAX_TRADES trades must not block."""
        for ticket in range(1, w99.MAX_TRADES):   # MAX_TRADES - 1 trades
            w99.open_trade(ticket)
        assert w99.is_entry_blocked() is False

    # -- T2: Blocked exactly at MAX_TRADES --
    def test_blocked_at_max_trades(self):
        """Opening exactly MAX_TRADES trades must trigger block."""
        for ticket in range(1, w99.MAX_TRADES + 1):
            w99.open_trade(ticket)
        assert w99.is_entry_blocked() is True

    # -- T3: Block lifts immediately after closing a trade --
    def test_block_lifts_on_close(self):
        """After closing one trade from a full set, guard must unblock."""
        for ticket in range(1, w99.MAX_TRADES + 1):
            w99.open_trade(ticket)
        assert w99.is_entry_blocked() is True
        w99.close_trade(1)   # close one → count drops to MAX_TRADES - 1
        assert w99.is_entry_blocked() is False

    # -- T4: update() open/close interface works correctly --
    def test_update_interface(self):
        """update(ticket, True) opens; update(ticket, False) closes."""
        for ticket in range(10, 10 + w99.MAX_TRADES):
            w99.update(ticket, True)
        assert w99.is_entry_blocked() is True
        w99.update(10, False)
        assert w99.is_entry_blocked() is False

    # -- T5: Invalid inputs (bool ticket, empty string) are rejected; reset works --
    def test_invalid_ticket_and_reset(self):
        """Boolean tickets and empty strings must be silently rejected."""
        w99.open_trade(True)    # bool → rejected
        w99.open_trade(False)   # bool → rejected
        w99.open_trade("")      # empty string → rejected
        w99.open_trade(None)    # type: ignore → rejected
        assert w99.is_entry_blocked() is False

        # Fill to max, then reset
        for ticket in range(100, 100 + w99.MAX_TRADES):
            w99.open_trade(ticket)
        assert w99.is_entry_blocked() is True
        w99.reset()
        assert w99.is_entry_blocked() is False
        with w99._lock:
            assert len(w99._open_tickets) == 0
