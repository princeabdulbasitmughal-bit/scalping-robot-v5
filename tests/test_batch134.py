import pytest
import datetime
from datetime import timezone
import math
from wave34_trailing_stop import TrailingStopManager, trailing_stop_manager, is_entry_blocked as w34_is_entry_blocked, is_blocked as w34_is_blocked, update as w34_update
from wave35_overnight_guard import OvernightGuard, overnight_guard, is_entry_blocked as w35_is_entry_blocked, is_blocked as w35_is_blocked, is_trading_allowed as w35_is_trading_allowed, should_force_close_all as w35_should_force_close_all


class TestBatch134:
    """Batch 134 Test Suite: wave34 Trailing Stop Manager & wave35 Overnight Guard."""

    def test_wave34_risk_guard_aliases(self):
        tsm = TrailingStopManager()
        assert tsm.is_blocked() is False
        assert tsm.is_entry_blocked() is False

        # Module-level aliases
        trailing_stop_manager.reset()
        assert w34_is_blocked() is False
        assert w34_is_entry_blocked() is False

    def test_wave34_trailing_stop_buy_trigger_and_trail(self):
        tsm = TrailingStopManager(profit_trigger_pips=15.0, trail_pips=10.0, trail_step_pips=1.0)
        # BUY: entry=2000.0, pip_size=0.1
        # At current_price=2001.0 (profit=10 pips < 15 pips) -> no move (None)
        assert tsm.update(ticket=101, direction="BUY", entry_price=2000.0, current_price=2001.0, current_sl=1995.0, pip_size=0.1) is None

        # At current_price=2002.0 (profit=20 pips >= 15 pips)
        # New SL = best_price (2002.0) - trail (10 pips = 1.0) = 2001.0
        new_sl = tsm.update(ticket=101, direction="BUY", entry_price=2000.0, current_price=2002.0, current_sl=1995.0, pip_size=0.1)
        assert new_sl == 2001.0
        assert 101 in tsm._trailing_active

        # Price advances to 2003.5 -> SL moves to 2002.5
        new_sl_2 = tsm.update(ticket=101, direction="BUY", entry_price=2000.0, current_price=2003.5, current_sl=2001.0, pip_size=0.1)
        assert new_sl_2 == 2002.5

        # Price pulls back to 2003.0 -> SL should NOT move down
        assert tsm.update(ticket=101, direction="BUY", entry_price=2000.0, current_price=2003.0, current_sl=2002.5, pip_size=0.1) is None

    def test_wave34_trailing_stop_sell_trigger_and_trail(self):
        tsm = TrailingStopManager(profit_trigger_pips=15.0, trail_pips=10.0, trail_step_pips=1.0)
        # SELL: entry=2000.0, pip_size=0.1
        # At current_price=1998.0 (profit=20 pips >= 15 pips)
        # New SL = best_price (1998.0) + trail (10 pips = 1.0) = 1999.0
        new_sl = tsm.update(ticket=202, direction="SELL", entry_price=2000.0, current_price=1998.0, current_sl=2005.0, pip_size=0.1)
        assert new_sl == 1999.0

        # Price drops further to 1996.0 -> SL moves down to 1997.0
        new_sl_2 = tsm.update(ticket=202, direction="SELL", entry_price=2000.0, current_price=1996.0, current_sl=1999.0, pip_size=0.1)
        assert new_sl_2 == 1997.0

    def test_wave34_quantize_lot_and_price(self):
        tsm = TrailingStopManager()
        # Quantize lot
        assert tsm.quantize_lot(0.045, min_lot=0.01, lot_step=0.01) == 0.04
        assert tsm.quantize_lot(0.005, min_lot=0.01, lot_step=0.01) == 0.01
        assert tsm.quantize_lot(-1.0) == 0.0

        # Quantize price
        assert tsm.quantize_price(2000.12345, pip_size=0.1) == 2000.123
        assert tsm.quantize_price(2000.12345, digits=2) == 2000.12

    def test_wave34_ticket_cleanup_and_reset(self):
        tsm = TrailingStopManager()
        tsm._trailing_active.add(101)
        tsm._best_prices[101] = 2002.0
        tsm.close_ticket(101)
        assert 101 not in tsm._trailing_active
        assert 101 not in tsm._best_prices

        tsm._total_trails = 5
        tsm.reset()
        assert tsm._total_trails == 0
        assert len(tsm._trailing_active) == 0

    def test_wave35_risk_guard_aliases(self):
        og = OvernightGuard()
        # Wednesday 12:00 UTC -> clear
        dt_wed = datetime.datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
        assert og.is_blocked(dt_wed) is False
        assert og.is_entry_blocked(dt_wed) is False

        # Module-level aliases
        overnight_guard.reset()
        assert w35_is_blocked(dt_wed) is False
        assert w35_is_entry_blocked(dt_wed) is False
        allowed, _ = w35_is_trading_allowed(dt_wed)
        assert allowed is True

    def test_wave35_friday_afternoon_block(self):
        og = OvernightGuard()
        # Friday 18:00 UTC -> clear
        dt_fri_early = datetime.datetime(2026, 10, 16, 18, 0, tzinfo=timezone.utc)
        assert og.is_entry_blocked(dt_fri_early) is False

        # Friday 20:30 UTC -> blocked
        dt_fri_late = datetime.datetime(2026, 10, 16, 20, 30, tzinfo=timezone.utc)
        assert og.is_entry_blocked(dt_fri_late) is True
        allowed, reason = og.is_trading_allowed(dt_fri_late)
        assert allowed is False
        assert "weekend" in reason

    def test_wave35_weekend_block(self):
        og = OvernightGuard()
        # Saturday 12:00 UTC
        dt_sat = datetime.datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
        assert og.is_entry_blocked(dt_sat) is True

        # Sunday 15:00 UTC
        dt_sun = datetime.datetime(2026, 10, 18, 15, 0, tzinfo=timezone.utc)
        assert og.is_entry_blocked(dt_sun) is True

    def test_wave35_daily_rollover_block(self):
        og = OvernightGuard()
        # Tuesday 21:50 UTC (in 21:45-22:15 window)
        dt_rollover = datetime.datetime(2026, 10, 13, 21, 50, tzinfo=timezone.utc)
        assert og.is_entry_blocked(dt_rollover) is True
        allowed, reason = og.is_trading_allowed(dt_rollover)
        assert allowed is False
        assert "rollover" in reason

        # Tuesday 22:20 UTC (after rollover) -> clear
        dt_after = datetime.datetime(2026, 10, 13, 22, 20, tzinfo=timezone.utc)
        assert og.is_entry_blocked(dt_after) is False

    def test_wave35_should_force_close_all_and_reset(self):
        og = OvernightGuard()
        # Wednesday -> no force close
        dt_wed = datetime.datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
        assert og.should_force_close_all(dt_wed) is False

        # Friday 20:35 UTC -> triggers force close
        dt_fri = datetime.datetime(2026, 10, 16, 20, 35, tzinfo=timezone.utc)
        assert og.should_force_close_all(dt_fri) is True
        assert og.total_force_closes == 1

        # Reset
        og.reset()
        assert og.total_force_closes == 0
        assert og.friday_block_active is False
