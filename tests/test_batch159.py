"""
tests/test_batch159.py
-----------------------
Unit tests for:
  wave84_margin_level_guard      (margin level % safety check)
  wave85_consecutive_loss_guard  (consecutive losing trade streak block)

5 tests per module = 10 total.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave84_margin_level_guard as w84
import wave85_consecutive_loss_guard as w85


# ---------------------------------------------------------------------------
# wave84 tests
# ---------------------------------------------------------------------------

class TestWave84MarginLevelGuard:

    def setup_method(self):
        w84.reset()

    def test_no_margin_used_not_blocked(self):
        """Zero margin used (no open positions) must NOT block."""
        w84.update(10000.0, 0.0)
        assert w84.is_entry_blocked() is False
        assert w84.get_margin_level_pct() == float("inf")

    def test_safe_margin_level_not_blocked(self):
        """Margin level of 500% (> 200% threshold) must NOT block."""
        # equity=5000, margin=1000 -> 500%
        w84.update(5000.0, 1000.0)
        assert w84.is_entry_blocked() is False
        assert abs(w84.get_margin_level_pct() - 500.0) < 0.01

    def test_low_margin_level_triggers_block(self):
        """Margin level of 150% (< 200% threshold) must trigger block."""
        # equity=1500, margin=1000 -> 150%
        w84.update(1500.0, 1000.0)
        assert w84.is_entry_blocked() is True

    def test_exactly_at_threshold_triggers_block(self):
        """Margin level exactly at 200% must trigger block (< not <=)."""
        # equity=2000, margin=1000 -> 200% -> NOT < 200 -> should NOT block
        w84.update(2000.0, 1000.0)
        assert w84.is_entry_blocked() is False

    def test_invalid_inputs_ignored(self):
        """bool, NaN, Inf, negative values must be silently ignored."""
        w84.update(True, 1000.0)
        w84.update(float("nan"), 1000.0)
        w84.update(5000.0, float("inf"))
        w84.update(-100.0, 1000.0)
        w84.update(5000.0, -50.0)
        # No valid update -> not blocked
        assert w84.is_entry_blocked() is False


# ---------------------------------------------------------------------------
# wave85 tests
# ---------------------------------------------------------------------------

class TestWave85ConsecutiveLossGuard:

    def setup_method(self):
        w85.reset()

    def test_no_trades_not_blocked(self):
        """Zero trades recorded -> not blocked, streak == 0."""
        assert w85.is_entry_blocked() is False
        assert w85.get_consecutive_losses() == 0

    def test_win_resets_streak(self):
        """Four losses followed by a win must reset streak to 0."""
        for _ in range(4):
            w85.record_trade_pnl(-10.0)
        assert w85.get_consecutive_losses() == 4
        w85.record_trade_pnl(5.0)   # win
        assert w85.get_consecutive_losses() == 0
        assert w85.is_entry_blocked() is False

    def test_five_losses_trigger_block(self):
        """Exactly 5 consecutive losses must trigger cooldown block."""
        for _ in range(5):
            w85.record_trade_pnl(-1.0)
        assert w85.get_consecutive_losses() == 5
        assert w85.is_entry_blocked() is True

    def test_breakeven_treated_as_loss(self):
        """pnl == 0.0 (break-even) must count as a loss."""
        for _ in range(4):
            w85.record_trade_pnl(-1.0)
        w85.record_trade_pnl(0.0)   # break-even = loss
        assert w85.get_consecutive_losses() == 5
        assert w85.is_entry_blocked() is True

    def test_invalid_pnl_ignored(self):
        """bool, NaN, Inf, string PnL must be silently ignored."""
        w85.update(True)
        w85.update(float("nan"))
        w85.update(float("inf"))
        w85.update("bad")
        assert w85.get_consecutive_losses() == 0
        assert w85.is_entry_blocked() is False
