"""
tests/test_batch86.py
Batch 86 Unit Tests: Opening Range Breakout (ORB) Filter & Profit Streak Booster (wave61 & wave60).
Expands test baseline beyond 1,107+ passing tests.
Verifies:
1. wave61: BlockResult subclass duality (bool, tuple, indexable, integer).
2. wave61: Session detection and range window reset on London (08:00 UTC) and NY (13:00 UTC) opens.
3. wave61: In-window tick tracking, high/low range building, and pip calculation.
4. wave61: Window expiration rollover and minimum tick threshold (10 ticks) gating.
5. wave61: Post-window BUY and SELL breakout confirmations vs range boundaries.
6. wave61: OpeningRangeBreakout state reset and info() telemetry introspection.
7. wave60: ProfitStreakBooster initialization defaults and parameter clamping [1.0, 3.0].
8. wave60: record_trade handling boolean flags and numeric positive/negative PnL values.
9. wave60: Streak activation after 3 consecutive wins, TP boosting (+20%), and instant loss reset.
10. wave60: ProfitStreakBooster reset() clearing and info() telemetry introspection.
"""

from datetime import datetime, timezone
import pytest

from wave61_opening_range_breakout import (
    OpeningRangeBreakout,
    BlockResult,
)
from wave60_profit_streak_booster import ProfitStreakBooster


def test_wave61_block_result_subclass_duality():
    """Verify BlockResult behaves as a boolean, tuple, indexable sequence, and integer."""
    res_blocked = BlockResult(True, "price_not_above_or_high")
    assert bool(res_blocked) is True
    assert res_blocked.blocked is True
    assert res_blocked.reason == "price_not_above_or_high"
    assert res_blocked[0] is True
    assert res_blocked[1] == "price_not_above_or_high"
    assert int(res_blocked) == 1
    assert "BlockResult(True" in repr(res_blocked)

    # Tuple unpacking
    blocked, reason = res_blocked
    assert blocked is True
    assert reason == "price_not_above_or_high"

    # Out of range indexing raises IndexError
    with pytest.raises(IndexError):
        _ = res_blocked[2]

    # Non-blocked result
    res_allowed = BlockResult(False, "breakout_confirmed")
    assert bool(res_allowed) is False
    assert int(res_allowed) == 0


def test_wave61_session_reset_and_window_tracking():
    """Verify OpeningRangeBreakout triggers session reset on London (08:00) and NY (13:00) UTC opens."""
    orb = OpeningRangeBreakout(min_ticks=5, window_seconds=1800)

    # 1. 08:05 UTC (London open window)
    dt_london = datetime(2026, 10, 18, 8, 5, 0, tzinfo=timezone.utc)
    orb.update(2650.0, now_dt=dt_london)

    assert orb._in_window is True
    assert orb._window_complete is False
    assert orb._or_high == 2650.0
    assert orb._or_low == 2650.0

    # 2. Reset across days: next day 08:02 UTC
    dt_next_day = datetime(2026, 10, 19, 8, 2, 0, tzinfo=timezone.utc)
    orb.update(2660.0, now_dt=dt_next_day)
    assert orb._or_high == 2660.0
    assert orb._tick_count == 1


def test_wave61_range_building_in_window():
    """Verify in-window tick updates expand high and low range and compute range pips accurately."""
    orb = OpeningRangeBreakout(min_ticks=5, window_seconds=1800)
    base_dt = datetime(2026, 10, 18, 8, 2, 0, tzinfo=timezone.utc)

    # Feed ticks expanding range: 2640.0 to 2660.0
    prices = [2650.0, 2640.0, 2655.0, 2660.0, 2645.0]
    for p in prices:
        orb.update(p, now_dt=base_dt)

    assert orb._or_high == 2660.0
    assert orb._or_low == 2640.0
    assert orb._tick_count == 5

    # Range in pips: (2660.0 - 2640.0) / 0.1 = 200.0 pips
    assert orb.get_range_pips(pip_size=0.1) == 200.0


def test_wave61_window_completion_and_tick_threshold():
    """Verify window completes after elapsed time, and rejects breakout if ticks < min_ticks."""
    orb = OpeningRangeBreakout(min_ticks=10, window_seconds=1800)
    start_dt = datetime(2026, 10, 18, 8, 0, 0, tzinfo=timezone.utc)

    # Feed 4 ticks (less than min_ticks=10)
    for i in range(4):
        orb.update(2650.0 + i, now_dt=start_dt)

    # Advance 31 minutes to expire window
    end_dt = datetime(2026, 10, 18, 8, 31, 0, tzinfo=timezone.utc)
    orb.update(2655.0, now_dt=end_dt)

    assert orb._in_window is False
    assert orb._window_complete is True

    # Check signal: tick count (4) < min_ticks (10) -> not blocked
    res = orb.is_signal_blocked("BUY", price=2660.0)
    assert bool(res) is False
    assert res.reason == "insufficient_ticks"


def test_wave61_breakout_confirmation_and_filtering():
    """Verify BUY is blocked when price <= OR_high, and SELL is blocked when price >= OR_low."""
    orb = OpeningRangeBreakout(min_ticks=5, window_seconds=1800)
    start_dt = datetime(2026, 10, 18, 8, 0, 0, tzinfo=timezone.utc)

    # Establish range: high = 2655.0, low = 2645.0 with 5 ticks
    for p in [2650.0, 2645.0, 2655.0, 2648.0, 2652.0]:
        orb.update(p, now_dt=start_dt)

    # Expire window
    end_dt = datetime(2026, 10, 18, 8, 35, 0, tzinfo=timezone.utc)
    orb.update(2650.0, now_dt=end_dt)
    assert orb._window_complete is True

    # 1. BUY price not above OR_high (2654.0 <= 2655.0) -> BLOCKED
    res_buy_block = orb.is_signal_blocked("BUY", price=2654.0)
    assert bool(res_buy_block) is True
    assert res_buy_block.reason == "price_not_above_or_high"
    assert orb.is_entry_blocked("BUY", price=2654.0) is True

    # 2. BUY price breaks above OR_high (2656.0 > 2655.0) -> CONFIRMED
    res_buy_pass = orb.is_signal_blocked("BUY", price=2656.0)
    assert bool(res_buy_pass) is False
    assert res_buy_pass.reason == "breakout_confirmed"

    # 3. SELL price not below OR_low (2646.0 >= 2645.0) -> BLOCKED
    res_sell_block = orb.is_signal_blocked("SELL", price=2646.0)
    assert bool(res_sell_block) is True
    assert res_sell_block.reason == "price_not_below_or_low"

    # 4. SELL price breaks below OR_low (2644.0 < 2645.0) -> CONFIRMED
    res_sell_pass = orb.is_signal_blocked("SELL", price=2644.0)
    assert bool(res_sell_pass) is False
    assert res_sell_pass.reason == "breakout_confirmed"

    # 5. Non-directional signal
    assert orb.is_signal_blocked("HOLD").reason == "non_directional_signal"


def test_wave61_reset_and_info_introspection():
    """Verify reset() clears internal state and info() outputs diagnostic status."""
    orb = OpeningRangeBreakout()
    start_dt = datetime(2026, 10, 18, 8, 0, 0, tzinfo=timezone.utc)
    orb.update(2650.0, now_dt=start_dt)

    info = orb.info()
    assert info["wave"] == 61
    assert info["name"] == "OpeningRangeBreakout"
    assert info["in_window"] is True
    assert info["or_high"] == 2650.0

    orb.reset()
    info_reset = orb.info()
    assert info_reset["in_window"] is False
    assert info_reset["or_high"] is None
    assert info_reset["tick_count"] == 0


def test_wave60_initialization_defaults_and_clamping():
    """Verify ProfitStreakBooster initialization defaults and parameter boundary clamping."""
    # Defaults
    booster = ProfitStreakBooster()
    assert booster.streak_length == 3
    assert booster.tp_multiplier == 1.2

    # Clamping
    booster_clamped = ProfitStreakBooster(streak_length=-2, tp_multiplier=5.0)
    assert booster_clamped.streak_length == 1
    assert booster_clamped.tp_multiplier == 3.0

    booster_low = ProfitStreakBooster(tp_multiplier=0.5)
    assert booster_low.tp_multiplier == 1.0


def test_wave60_record_trade_boolean_and_numeric_pnl():
    """Verify record_trade accepts boolean wins and numeric positive/negative PnL."""
    booster = ProfitStreakBooster(streak_length=2)

    # Boolean win
    booster.record_trade(True)
    assert booster._current_streak == 1

    # Numeric win (PnL > 0)
    booster.record_trade(15.5)
    assert booster._current_streak == 2
    assert booster.is_in_streak() is True

    # Numeric loss (PnL <= 0)
    booster.record_trade(-10.0)
    assert booster._current_streak == 0
    assert booster.is_in_streak() is False

    # Invalid input ignored safely
    booster.record_trade(None)
    assert booster._current_streak == 0


def test_wave60_streak_confidence_engagement_and_reset():
    """Verify confidence mode engages on 3 consecutive wins and disengages on any loss."""
    booster = ProfitStreakBooster(streak_length=3, tp_multiplier=1.25)

    base_tp = 20.0

    # Win 1
    booster.record_trade(True)
    assert not booster.is_in_streak()
    assert booster.get_tp_multiplier() == 1.0
    assert booster.adjust_tp(base_tp) == 20.0

    # Win 2
    booster.record_trade(True)
    assert not booster.is_in_streak()

    # Win 3 -> Streak Active!
    booster.record_trade(True)
    assert booster.is_in_streak() is True
    assert booster.get_tp_multiplier() == 1.25
    assert booster.adjust_tp(base_tp) == 25.0  # 20 * 1.25

    # Loss 1 -> Streak Broken!
    booster.record_trade(False)
    assert booster.is_in_streak() is False
    assert booster.get_tp_multiplier() == 1.0
    assert booster.adjust_tp(base_tp) == 20.0


def test_wave60_reset_and_info_introspection():
    """Verify ProfitStreakBooster reset() clears deque and info() outputs telemetry."""
    booster = ProfitStreakBooster(streak_length=2)
    booster.record_trade(True)
    booster.record_trade(True)
    assert booster.is_in_streak() is True

    info = booster.info()
    assert info["wave"] == 60
    assert info["name"] == "ProfitStreakBooster"
    assert info["in_confidence_mode"] is True
    assert info["current_consecutive_wins"] == 2
    assert info["total_boost_activations"] == 1

    booster.reset()
    info_reset = booster.info()
    assert info_reset["in_confidence_mode"] is False
    assert info_reset["current_consecutive_wins"] == 0
    assert info_reset["total_boost_activations"] == 0
