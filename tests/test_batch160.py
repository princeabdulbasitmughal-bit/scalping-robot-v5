"""
tests/test_batch160.py
-----------------------
Unit tests for:
  wave86_trade_duration_guard  (max open trade hold duration)
  wave87_profit_factor_guard   (rolling profit factor regime filter)

5 tests per module = 10 total.
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave86_trade_duration_guard as w86
import wave87_profit_factor_guard as w87


# ---------------------------------------------------------------------------
# wave86 tests
# ---------------------------------------------------------------------------

class TestWave86TradeDurationGuard:

    def setup_method(self):
        w86.reset()

    def test_no_trades_not_blocked(self):
        """No open trades -> NOT blocked."""
        assert w86.is_entry_blocked() is False
        assert w86.get_oldest_duration_sec() == 0.0

    def test_fresh_trade_not_blocked(self):
        """A trade just opened is well under 4-hour threshold."""
        w86.open_trade(1001)
        assert w86.is_entry_blocked() is False
        assert w86.get_oldest_duration_sec() < 1.0

    def test_closed_trade_not_counted(self):
        """Closing a trade removes it from tracking."""
        w86.open_trade(2001)
        w86.close_trade(2001)
        assert w86.is_entry_blocked() is False
        assert w86.get_oldest_duration_sec() == 0.0

    def test_stale_trade_triggers_block(self):
        """Manually backdating a trade to simulate 5-hour-old trade -> block."""
        w86.open_trade(3001)
        # Backdate the open time by 5 hours
        with w86._lock:
            w86._open_trades["3001"] = time.monotonic() - (5 * 3600)
        assert w86.is_entry_blocked() is True
        assert w86.get_oldest_duration_sec() >= 5 * 3600

    def test_invalid_ticket_ignored(self):
        """bool, list, float, None tickets must be silently ignored."""
        w86.open_trade(True)
        w86.open_trade([1001])
        w86.open_trade(3.14)
        w86.open_trade(None)
        assert w86.is_entry_blocked() is False


# ---------------------------------------------------------------------------
# wave87 tests
# ---------------------------------------------------------------------------

class TestWave87ProfitFactorGuard:

    def setup_method(self):
        w87.reset()

    def test_warmup_fail_closed(self):
        """Fewer than min_trades (10) -> fail-closed (blocked)."""
        for _ in range(5):
            w87.record_trade_pnl(10.0)
        assert w87.is_entry_blocked() is True
        assert w87.get_profit_factor() == -1.0

    def test_healthy_profit_factor_not_blocked(self):
        """PF well above 0.8 -> NOT blocked after min_trades."""
        # 10 wins of $20, 0 losses -> PF = inf
        for _ in range(10):
            w87.record_trade_pnl(20.0)
        assert w87.is_entry_blocked() is False
        assert w87.get_profit_factor() == float("inf")

    def test_low_profit_factor_triggers_block(self):
        """PF below threshold: 10 losses of $10, 2 wins of $5 -> PF = 10/100 = 0.1."""
        w87.reset()
        for _ in range(10):
            w87.record_trade_pnl(-10.0)
        for _ in range(2):
            w87.record_trade_pnl(5.0)
        pf = w87.get_profit_factor()
        assert pf < 0.8
        assert w87.is_entry_blocked() is True

    def test_recovery_above_threshold_unblocks(self):
        """After cooldown expires a reset + healthy trades must unblock."""
        w87.reset()
        # Feed 10 mixed trades with healthy PF > 0.8
        for _ in range(8):
            w87.record_trade_pnl(15.0)
        for _ in range(2):
            w87.record_trade_pnl(-5.0)
        # PF = 120 / 10 = 12.0 -> healthy -> not blocked
        assert w87.get_profit_factor() >= 0.8
        assert w87.is_entry_blocked() is False

    def test_invalid_pnl_ignored(self):
        """bool, NaN, Inf, string PnL must be silently ignored."""
        w87.update(True)
        w87.update(float("nan"))
        w87.update(float("inf"))
        w87.update("bad")
        # No valid trades -> warmup -> fail-closed
        assert w87.is_entry_blocked() is True
        assert w87.get_profit_factor() == -1.0
