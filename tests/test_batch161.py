"""
tests/test_batch161.py
-----------------------
Unit tests for:
  wave88_sharpe_ratio_guard    (rolling Sharpe ratio regime filter)
  wave89_position_size_guard   (lot size validation guard)

5 tests per module = 10 total.
"""

import sys
import os
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave88_sharpe_ratio_guard as w88
import wave89_position_size_guard as w89


# ---------------------------------------------------------------------------
# wave88 tests
# ---------------------------------------------------------------------------

class TestWave88SharpeRatioGuard:

    def setup_method(self):
        w88.reset()

    def test_warmup_fail_closed(self):
        """Fewer than min_trades (10) -> fail-closed, Sharpe returns -999."""
        for _ in range(5):
            w88.record_trade_pnl(10.0)
        assert w88.is_entry_blocked() is True
        assert w88.get_sharpe() == -999.0

    def test_positive_sharpe_not_blocked(self):
        """Consistent winning trades yield positive Sharpe -> not blocked."""
        w88.reset()
        for _ in range(12):
            w88.record_trade_pnl(10.0)
        # All same PnL -> std=0, mean>0 -> Sharpe=+inf
        assert w88.get_sharpe() == math.inf
        assert w88.is_entry_blocked() is False

    def test_negative_sharpe_triggers_block(self):
        """Heavy losing trades -> Sharpe < -0.5 -> block activated."""
        w88.reset()
        for _ in range(10):
            w88.record_trade_pnl(-20.0)
        # All same negative PnL -> std=0, mean<0 -> Sharpe=-inf
        sharpe = w88.get_sharpe()
        assert sharpe < -0.5
        assert w88.is_entry_blocked() is True

    def test_mixed_trades_healthy_sharpe(self):
        """Predominantly winning trades with small variance -> Sharpe > threshold."""
        w88.reset()
        for _ in range(8):
            w88.record_trade_pnl(15.0)
        for _ in range(2):
            w88.record_trade_pnl(-2.0)
        sharpe = w88.get_sharpe()
        # mean~11.6, std small -> Sharpe should be well above -0.5
        assert sharpe > -0.5
        assert w88.is_entry_blocked() is False

    def test_invalid_pnl_ignored(self):
        """bool, NaN, Inf, string must be silently ignored."""
        w88.update(True)
        w88.update(float("nan"))
        w88.update(float("inf"))
        w88.update("bad")
        assert w88.get_sharpe() == -999.0
        assert w88.is_entry_blocked() is True  # still warmup -> fail-closed


# ---------------------------------------------------------------------------
# wave89 tests
# ---------------------------------------------------------------------------

class TestWave89PositionSizeGuard:

    def setup_method(self):
        w89.reset()

    def test_valid_lot_size_accepted(self):
        """A valid 0.1 lot size must be accepted and not block."""
        result = w89.check_lot_size(0.1)
        assert result is True
        assert w89.is_entry_blocked() is False

    def test_max_lot_size_accepted(self):
        """Exactly 2.0 lots (at the limit) must be accepted."""
        result = w89.check_lot_size(2.0)
        assert result is True
        assert w89.is_entry_blocked() is False

    def test_oversized_lot_triggers_block(self):
        """Lot size above 2.0 must be rejected and trigger cooldown."""
        result = w89.check_lot_size(2.01)
        assert result is False
        assert w89.is_entry_blocked() is True
        assert w89.get_last_rejected_size() == 2.01

    def test_zero_or_negative_lot_triggers_block(self):
        """Zero and negative lot sizes must be rejected."""
        result_zero = w89.check_lot_size(0.0)
        assert result_zero is False
        w89.reset()
        result_neg = w89.check_lot_size(-0.5)
        assert result_neg is False
        assert w89.is_entry_blocked() is True

    def test_invalid_inputs_trigger_block(self):
        """bool, NaN, Inf, string lot sizes must be rejected and block."""
        w89.reset()
        result = w89.check_lot_size(True)
        assert result is False
        w89.reset()
        result = w89.check_lot_size(float("nan"))
        assert result is False
        w89.reset()
        result = w89.check_lot_size(float("inf"))
        assert result is False
        assert w89.is_entry_blocked() is True
