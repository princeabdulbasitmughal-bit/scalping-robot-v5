"""
tests/test_batch156.py
-----------------------
Unit tests for:
  wave78_rsi_extreme_guard  (RSI extreme overbought/oversold guard)
  wave79_daily_loss_limit_guard  (Daily loss limit block)

5 tests per module = 10 total.
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave78_rsi_extreme_guard as w78
import wave79_daily_loss_limit_guard as w79


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_and_feed_prices(prices):
    """Reset wave78 state then feed a sequence of close prices."""
    w78.reset()
    for p in prices:
        w78.update(p)


def _gen_rising_prices(n=50, start=1.1000, step=0.0001):
    return [round(start + i * step, 5) for i in range(n)]


def _gen_falling_prices(n=50, start=1.1500, step=0.0001):
    return [round(start - i * step, 5) for i in range(n)]


# ---------------------------------------------------------------------------
# wave78 tests
# ---------------------------------------------------------------------------

class TestWave78RSIExtremeGuard:

    def test_warmup_fail_closed(self):
        """Before period+1 prices are fed, guard must be blocked (fail-closed)."""
        w78.reset()
        # Feed only 5 prices (need 15)
        for p in _gen_rising_prices(5):
            w78.update(p)
        assert w78.is_entry_blocked() is True

    def test_neutral_rsi_not_blocked(self):
        """Alternating gains/losses should keep RSI near 50 -> not blocked."""
        w78.reset()
        # Alternate up/down ticks to keep RSI mid-range
        prices = []
        base = 1.1000
        for i in range(30):
            if i % 2 == 0:
                base += 0.0001
            else:
                base -= 0.00009
            prices.append(round(base, 5))
        _reset_and_feed_prices(prices)
        # RSI should be near 50 — no cooldown triggered
        assert w78.is_entry_blocked() is False

    def test_overbought_triggers_block(self):
        """Continuous strong gains push RSI > 80 -> entry blocked."""
        prices = _gen_rising_prices(n=30, step=0.0005)
        _reset_and_feed_prices(prices)
        assert w78.is_entry_blocked() is True

    def test_oversold_triggers_block(self):
        """Continuous strong losses push RSI < 20 -> entry blocked."""
        prices = _gen_falling_prices(n=30, step=0.0005)
        _reset_and_feed_prices(prices)
        assert w78.is_entry_blocked() is True

    def test_invalid_inputs_ignored(self):
        """bool, NaN, Inf inputs must be silently ignored."""
        w78.reset()
        w78.update(True)
        w78.update(float("nan"))
        w78.update(float("inf"))
        w78.update("1.1")
        # State should still be warmup-blocked, not crash
        assert w78.is_entry_blocked() is True


# ---------------------------------------------------------------------------
# wave79 tests
# ---------------------------------------------------------------------------

class TestWave79DailyLossLimitGuard:

    def setup_method(self):
        w79.reset()

    def test_no_trades_not_blocked(self):
        """With no trades recorded, guard must NOT block."""
        assert w79.is_entry_blocked() is False

    def test_profit_trades_not_blocked(self):
        """Recording profitable trades must never trigger the limit."""
        for _ in range(10):
            w79.record_trade_pnl(20.0)
        assert w79.is_entry_blocked() is False
        assert w79.get_daily_pnl() == 200.0

    def test_loss_below_limit_not_blocked(self):
        """Losses less than -200 must NOT trigger the block."""
        w79.record_trade_pnl(-50.0)
        w79.record_trade_pnl(-80.0)
        assert w79.is_entry_blocked() is False
        assert w79.get_daily_pnl() == -130.0

    def test_loss_at_limit_triggers_block(self):
        """Exactly hitting -200 must trigger the daily block."""
        w79.record_trade_pnl(-100.0)
        w79.record_trade_pnl(-100.0)
        assert w79.get_daily_pnl() == -200.0
        assert w79.is_entry_blocked() is True

    def test_invalid_pnl_ignored(self):
        """bool, NaN, Inf, string must be silently ignored."""
        w79.record_trade_pnl(True)
        w79.record_trade_pnl(float("nan"))
        w79.record_trade_pnl(float("inf"))
        w79.update("bad")
        # No valid PnL recorded -> not blocked, PnL == 0
        assert w79.get_daily_pnl() == 0.0
        assert w79.is_entry_blocked() is False
