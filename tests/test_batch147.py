"""
Unit tests for Batch 147:
- wave60_profit_streak_booster.py (Profit Streak Confidence Booster)
- wave61_opening_range_breakout.py (Opening Range Breakout ORB Filter)
"""

import math
from datetime import datetime, timezone, timedelta
import pytest

from wave60_profit_streak_booster import (
    ProfitStreakBooster,
    profit_streak_booster,
    record_trade,
    get_tp_multiplier,
    adjust_tp,
    is_in_streak,
    is_entry_blocked as w60_is_entry_blocked,
    is_blocked as w60_is_blocked,
    reset as w60_reset,
    info as w60_info,
)

from wave61_opening_range_breakout import (
    OpeningRangeBreakout,
    BlockResult,
    opening_range_breakout,
    is_signal_blocked,
    is_entry_blocked as w61_is_entry_blocked,
    is_blocked as w61_is_blocked,
    update as w61_update,
    get_range_pips,
    reset as w61_reset,
    info as w61_info,
)


# ======================================================================
# Wave 60: Profit Streak Booster Tests
# ======================================================================

def test_wave60_initial_state():
    """Verify default initialization, properties, and initial multipliers."""
    booster = ProfitStreakBooster()
    assert booster.streak_length == 3
    assert booster.tp_multiplier == 1.2
    assert not booster.is_in_streak()
    assert booster.get_tp_multiplier() == 1.0
    assert booster.adjust_tp(25.0) == 25.0

    inf = booster.info()
    assert inf["wave"] == 60
    assert inf["in_confidence_mode"] is False
    assert inf["tp_multiplier"] == 1.0
    assert inf["current_consecutive_wins"] == 0
    assert inf["recent_trades_count"] == 0


def test_wave60_invalid_and_edge_inputs():
    """Verify constructor with bad params, bad inputs to record_trade and adjust_tp."""
    # Bad constructor values fallback gracefully
    b_bad = ProfitStreakBooster(streak_length="invalid", tp_multiplier="bad")  # type: ignore
    assert b_bad.streak_length == 3
    assert b_bad.tp_multiplier == 1.2

    b_clamp = ProfitStreakBooster(streak_length=0, tp_multiplier=10.0)
    assert b_clamp.streak_length == 1
    assert b_clamp.tp_multiplier == 3.0

    # Bad record_trade inputs should be ignored
    b_bad.record_trade(None)
    b_bad.record_trade("not_a_bool_or_num")
    b_bad.record_trade(float("nan"))
    b_bad.record_trade(float("inf"))
    assert b_bad.info()["recent_trades_count"] == 0

    # Bad adjust_tp inputs
    assert b_bad.adjust_tp(None) == 0.0
    assert b_bad.adjust_tp(True) == 0.0
    assert b_bad.adjust_tp(False) == 0.0
    assert b_bad.adjust_tp(-10.0) == 0.0
    assert b_bad.adjust_tp(0.0) == 0.0
    assert b_bad.adjust_tp("invalid") == 0.0
    assert b_bad.adjust_tp(float("nan")) == 0.0


def test_wave60_consecutive_wins_activates_streak():
    """Verify consecutive winning trades activate confidence mode with boosted TP."""
    booster = ProfitStreakBooster(streak_length=3, tp_multiplier=1.25)
    
    # Trade 1: Win (boolean True)
    booster.record_trade(True)
    assert not booster.is_in_streak()
    assert booster.get_tp_multiplier() == 1.0
    assert booster.adjust_tp(20.0) == 20.0

    # Trade 2: Win (numeric PnL > 0)
    booster.record_trade(15.50)
    assert not booster.is_in_streak()
    assert booster.get_tp_multiplier() == 1.0

    # Trade 3: Win (numeric PnL > 0) -> Activates streak!
    booster.record_trade(5.0)
    assert booster.is_in_streak()
    assert booster.get_tp_multiplier() == 1.25
    # 20.0 * 1.25 = 25.0
    assert booster.adjust_tp(20.0) == 25.0

    inf = booster.info()
    assert inf["in_confidence_mode"] is True
    assert inf["tp_multiplier"] == 1.25
    assert inf["current_consecutive_wins"] == 3
    assert inf["total_boost_activations"] == 1


def test_wave60_loss_deactivates_streak_and_reset():
    """Verify a loss immediately deactivates confidence mode and reset() works."""
    booster = ProfitStreakBooster(streak_length=2, tp_multiplier=1.5)
    booster.record_trade(True)
    booster.record_trade(True)
    assert booster.is_in_streak()
    assert booster.get_tp_multiplier() == 1.5

    # Breakeven (0.0) or loss (False / negative) deactivates
    booster.record_trade(-2.50)
    assert not booster.is_in_streak()
    assert booster.get_tp_multiplier() == 1.0
    assert booster.adjust_tp(20.0) == 20.0

    # Win 2 in a row again
    booster.record_trade(True)
    booster.record_trade(True)
    assert booster.is_in_streak()

    # Reset clears everything
    booster.reset()
    assert not booster.is_in_streak()
    assert booster.info()["current_consecutive_wins"] == 0
    assert booster.info()["total_boost_activations"] == 0


def test_wave60_module_aliases():
    """Verify wave60 module-level singletons, aliases, and entry gate bypass."""
    w60_reset()
    assert not is_in_streak()
    assert get_tp_multiplier() == 1.0
    assert w60_is_entry_blocked("BUY") is False
    assert w60_is_blocked("SELL") is False

    record_trade(True)
    record_trade(True)
    record_trade(True)
    assert is_in_streak()
    assert get_tp_multiplier() == 1.2
    assert adjust_tp(10.0) == 12.0

    inf = w60_info()
    assert inf["wave"] == 60
    assert inf["in_confidence_mode"] is True

    w60_reset()
    assert not is_in_streak()


# ======================================================================
# Wave 61: Opening Range Breakout (ORB) Tests
# ======================================================================

def test_wave61_initial_state_and_edge_inputs():
    """Verify ORB initial state, edge inputs, and range calculation."""
    orb = OpeningRangeBreakout()
    assert orb.get_range_pips() == 0.0
    inf = orb.info()
    assert inf["wave"] == 61
    assert inf["in_window"] is False
    assert inf["window_complete"] is False
    assert inf["tick_count"] == 0

    # Bad constructor values fallback gracefully
    orb_bad = OpeningRangeBreakout(min_ticks="bad", window_seconds="bad")  # type: ignore
    assert orb_bad._min_ticks == 10
    assert orb_bad._window_seconds == 1800

    # Bad update prices are ignored
    orb.update(None)
    orb.update(True)
    orb.update(False)
    orb.update(-100.0)
    orb.update(0.0)
    orb.update("invalid_price")
    orb.update(float("nan"))
    assert orb.info()["last_price"] == 0.0


def test_wave61_session_reset_and_window_building():
    """Verify session detection at London open and range accumulation during window."""
    orb = OpeningRangeBreakout(min_ticks=5, window_seconds=1800)
    # London Open: 08:05 UTC
    t0 = datetime(2026, 10, 18, 8, 5, 0, tzinfo=timezone.utc)
    
    # Feed first tick at 08:05
    orb.update(2650.0, now_dt=t0)
    inf = orb.info()
    assert inf["in_window"] is True
    assert inf["window_complete"] is False
    assert inf["tick_count"] == 1
    assert inf["or_high"] == 2650.0
    assert inf["or_low"] == 2650.0

    # Signal check while window is still building should not block
    assert not orb.is_signal_blocked("BUY", price=2650.0)
    assert not orb.is_entry_blocked("SELL", price=2650.0)

    # Feed more ticks within window
    orb.update(2655.0, now_dt=t0 + timedelta(minutes=5))
    orb.update(2645.0, now_dt=t0 + timedelta(minutes=10))
    orb.update(2652.0, now_dt=t0 + timedelta(minutes=15))
    orb.update(2648.0, now_dt=t0 + timedelta(minutes=20))

    inf2 = orb.info()
    assert inf2["or_high"] == 2655.0
    assert inf2["or_low"] == 2645.0
    assert inf2["tick_count"] == 5
    # (2655.0 - 2645.0) / 0.1 = 100.0 pips
    assert orb.get_range_pips() == 100.0


def test_wave61_window_completion_and_breakout_blocks():
    """Verify window expires after 30 min and non-breakout signals are blocked."""
    orb = OpeningRangeBreakout(min_ticks=3, window_seconds=1800)
    t_open = datetime(2026, 10, 18, 8, 2, 0, tzinfo=timezone.utc)

    # Build range (high=2655.0, low=2645.0)
    orb.update(2650.0, now_dt=t_open)
    orb.update(2655.0, now_dt=t_open + timedelta(minutes=5))
    orb.update(2645.0, now_dt=t_open + timedelta(minutes=10))

    # Advance time to 08:31 UTC (window expired: session_start was 08:00, 31 min elapsed)
    t_post = datetime(2026, 10, 18, 8, 31, 0, tzinfo=timezone.utc)
    orb.update(2650.0, now_dt=t_post)

    inf = orb.info()
    assert inf["window_complete"] is True
    assert inf["in_window"] is False

    # Inside range: BUY blocked because price (2650.0) <= OR_high (2655.0)
    res_buy = orb.is_signal_blocked("BUY", price=2650.0)
    assert res_buy.blocked is True
    assert res_buy.reason == "price_not_above_or_high"

    # Exactly at boundary: BUY blocked
    assert orb.is_entry_blocked("BUY", price=2655.0) is True

    # Inside range: SELL blocked because price (2650.0) >= OR_low (2645.0)
    res_sell = orb.is_signal_blocked("SELL", price=2650.0)
    assert res_sell.blocked is True
    assert res_sell.reason == "price_not_below_or_low"

    # Exactly at boundary: SELL blocked
    assert orb.is_entry_blocked("SELL", price=2645.0) is True


def test_wave61_confirmed_breakout_allowed():
    """Verify valid breakouts above OR_high (for BUY) and below OR_low (for SELL) are allowed."""
    orb = OpeningRangeBreakout(min_ticks=3, window_seconds=1800)
    t_open = datetime(2026, 10, 18, 8, 0, 0, tzinfo=timezone.utc)

    # Establish range: high=2660.0, low=2640.0
    orb.update(2650.0, now_dt=t_open)
    orb.update(2660.0, now_dt=t_open + timedelta(minutes=5))
    orb.update(2640.0, now_dt=t_open + timedelta(minutes=10))

    # Window completes at 08:35
    t_post = datetime(2026, 10, 18, 8, 35, 0, tzinfo=timezone.utc)
    orb.update(2655.0, now_dt=t_post)

    # Bullish Breakout: BUY at 2661.0 > 2660.0 is ALLOWED
    res_buy = orb.is_signal_blocked("BUY", price=2661.0)
    assert not res_buy.blocked
    assert res_buy.reason == "breakout_confirmed"

    # Bearish Breakout: SELL at 2639.0 < 2640.0 is ALLOWED
    res_sell = orb.is_signal_blocked("SELL", price=2639.0)
    assert not res_sell.blocked
    assert res_sell.reason == "breakout_confirmed"

    # Non-directional signal
    assert not orb.is_signal_blocked("HOLD")
    assert not orb.is_signal_blocked("")


def test_wave61_block_result_and_module_aliases():
    """Verify BlockResult polymorphism and module-level functions."""
    # Test BlockResult features
    br_true = BlockResult(True, "test_blocked")
    assert bool(br_true) is True
    assert int(br_true) == 1
    assert br_true[0] is True
    assert br_true[1] == "test_blocked"
    b_val, reason_val = br_true
    assert b_val is True
    assert reason_val == "test_blocked"
    assert "BlockResult(True, 'test_blocked')" in repr(br_true)

    br_false = BlockResult(False, "test_allowed")
    assert bool(br_false) is False
    assert int(br_false) == 0
    assert br_false[0] is False
    assert br_false[1] == "test_allowed"

    # Test module-level functions
    w61_reset()
    assert not w61_is_entry_blocked("BUY")
    assert not w61_is_blocked("SELL")
    assert get_range_pips() == 0.0

    t_ny = datetime(2026, 10, 18, 13, 5, 0, tzinfo=timezone.utc)
    w61_update(2650.0, now_dt=t_ny)
    w61_update(2660.0, now_dt=t_ny + timedelta(minutes=5))
    w61_update(2640.0, now_dt=t_ny + timedelta(minutes=10))

    inf = w61_info()
    assert inf["wave"] == 61
    assert inf["name"] == "OpeningRangeBreakout"

    w61_reset()
    assert get_range_pips() == 0.0
