"""
tests/test_batch164.py
-----------------------
Unit tests for:
  wave94_open_pnl_threshold_guard  (aggregate floating PnL block)
  wave95_symbol_exposure_guard     (per-symbol position count limit)

5 tests per module = 10 total.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave94_open_pnl_threshold_guard as w94
import wave95_symbol_exposure_guard as w95


# ---------------------------------------------------------------------------
# wave94 tests
# ---------------------------------------------------------------------------

class TestWave94OpenPnlThresholdGuard:

    def setup_method(self):
        w94.reset()

    def test_no_positions_not_blocked(self):
        """No open positions -> NOT blocked, total PnL == 0."""
        assert w94.is_entry_blocked() is False
        assert w94.get_total_open_pnl() == 0.0

    def test_positive_pnl_not_blocked(self):
        """Profitable open positions must NOT trigger block."""
        w94.update_position(1001, 50.0)
        w94.update_position(1002, 30.0)
        assert w94.is_entry_blocked() is False
        assert w94.get_total_open_pnl() == 80.0

    def test_loss_below_threshold_not_blocked(self):
        """Aggregate loss of -$80 (< -$100 threshold) -> not blocked."""
        w94.update_position(2001, -40.0)
        w94.update_position(2002, -40.0)
        assert w94.get_total_open_pnl() == -80.0
        assert w94.is_entry_blocked() is False

    def test_loss_at_threshold_triggers_block(self):
        """Aggregate loss exactly -$100 -> triggers cooldown block."""
        w94.update_position(3001, -60.0)
        w94.update_position(3002, -40.0)
        assert w94.get_total_open_pnl() == -100.0
        assert w94.is_entry_blocked() is True

    def test_invalid_inputs_ignored(self):
        """bool ticket, NaN pnl, Inf pnl, list ticket must be silently ignored."""
        w94.update_position(True, -200.0)
        w94.update_position(1234, float("nan"))
        w94.update_position(1234, float("inf"))
        w94.update_position([5], -200.0)
        assert w94.get_total_open_pnl() == 0.0
        assert w94.is_entry_blocked() is False


# ---------------------------------------------------------------------------
# wave95 tests
# ---------------------------------------------------------------------------

class TestWave95SymbolExposureGuard:

    def setup_method(self):
        w95.reset()

    def test_no_positions_not_blocked(self):
        """No positions -> not blocked for any symbol."""
        assert w95.is_entry_blocked("EURUSD") is False
        assert w95.get_exposure("EURUSD") == 0

    def test_one_position_not_blocked(self):
        """One position (< max of 2) -> not blocked."""
        w95.open_position("EURUSD", 1001)
        assert w95.is_entry_blocked("EURUSD") is False
        assert w95.get_exposure("EURUSD") == 1

    def test_at_max_triggers_block(self):
        """Two positions (== max of 2) -> blocked for that symbol."""
        w95.open_position("EURUSD", 2001)
        w95.open_position("EURUSD", 2002)
        assert w95.is_entry_blocked("EURUSD") is True
        assert w95.get_exposure("EURUSD") == 2

    def test_different_symbol_not_blocked(self):
        """Reaching max on EURUSD must NOT block entries on GBPUSD."""
        w95.open_position("EURUSD", 3001)
        w95.open_position("EURUSD", 3002)
        assert w95.is_entry_blocked("EURUSD") is True
        assert w95.is_entry_blocked("GBPUSD") is False

    def test_close_position_unblocks(self):
        """Closing one position reduces count and unblocks the symbol."""
        w95.open_position("USDJPY", 4001)
        w95.open_position("USDJPY", 4002)
        assert w95.is_entry_blocked("USDJPY") is True
        w95.close_position("USDJPY", 4001)
        assert w95.is_entry_blocked("USDJPY") is False
        assert w95.get_exposure("USDJPY") == 1
