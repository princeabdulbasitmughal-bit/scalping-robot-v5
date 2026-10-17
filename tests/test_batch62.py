"""
tests/test_batch62.py
=====================
Hermetic unit tests for Batch 62:
1. OpeningRangeBreakout: Session detection & 30-min range building
2. OpeningRangeBreakout: Post-window breakout confirmation & BlockResult protocol
3. ProfitStreakBooster: Streak detection, confidence mode TP multiplier & loss reset
4. MATrendFilter: EMA warm-up, trend alignment gating & fail-closed safety
5. PriceRangeFilter: Intraday high/low tracking, dead-market block & UTC midnight reset
6. ConsecutiveLossGuard: Streak trip-wire, cooldown period & win streak reset
7. BalanceFloorGuard: Hard floor breach, hysteresis recovery & catastrophic halt
8. MaxSpreadPerTrade: Live spread ceiling, explicit parameter validation & fail-closed safety
9. TickReversalGuard: Momentum reversal detection, adverse tick blocking & cooldown expiration
10. SessionPnLTracker: Session bucket tracking, loss limit trip-wire & session rollover
"""

import math
import time
from datetime import datetime, timezone, timedelta
import pytest

from wave61_opening_range_breakout import OpeningRangeBreakout, BlockResult as Wave61BlockResult
from wave60_profit_streak_booster import ProfitStreakBooster
from wave59_ma_trend_filter import MATrendFilter, BlockResult as Wave59BlockResult
from wave58_price_range_filter import PriceRangeFilter
from wave56_consecutive_loss_guard import ConsecutiveLossGuard
from wave55_balance_floor_guard import BalanceFloorGuard
from wave54_max_spread_per_trade import MaxSpreadPerTrade
from wave53_tick_reversal_guard import TickReversalGuard
from wave52_rsi_ob_os_filter import RSIOverboughtOversold
from wave51_session_pnl_tracker import SessionPnLTracker


def test_wave61_orb_session_detection_and_building():
    """Verify ORB detects session open and accumulates range ticks during the 30-min window."""
    orb = OpeningRangeBreakout(min_ticks=5, window_seconds=1800)
    base_dt = datetime(2026, 10, 17, 8, 5, 0, tzinfo=timezone.utc)

    # Feed ticks within the first 30 minutes of London session
    prices = [2650.0, 2652.5, 2648.0, 2655.0, 2651.0]
    for idx, p in enumerate(prices):
        t = base_dt + timedelta(minutes=idx)
        orb.update(p, now_dt=t)

    info = orb.info()
    assert info["in_window"] is True
    assert info["window_complete"] is False
    assert info["or_high"] == 2655.0
    assert info["or_low"] == 2648.0
    assert info["tick_count"] == 5

    # During the 30-min window, signals should not be blocked (window not complete)
    res = orb.is_signal_blocked("BUY", price=2650.0, now_dt=base_dt)
    assert not bool(res)
    assert res[1] == "window_not_complete"


def test_wave61_orb_breakout_confirmation_and_block_result():
    """Verify ORB breakout filtering after 30-min window and BlockResult protocol."""
    orb = OpeningRangeBreakout(min_ticks=5, window_seconds=1800)
    start_dt = datetime(2026, 10, 17, 13, 2, 0, tzinfo=timezone.utc)

    # Feed 6 ticks in NY session range [2640.0, 2660.0]
    prices = [2650.0, 2660.0, 2645.0, 2640.0, 2655.0, 2652.0]
    for idx, p in enumerate(prices):
        t = start_dt + timedelta(minutes=idx * 2)
        orb.update(p, now_dt=t)

    # Tick at 13:35 UTC (35 mins after 13:00 open -> window expired)
    post_dt = datetime(2026, 10, 17, 13, 35, 0, tzinfo=timezone.utc)
    orb.update(2655.0, now_dt=post_dt)

    assert orb.info()["window_complete"] is True

    # BUY at 2655.0 (below or_high 2660.0) -> BLOCKED
    res_buy_blocked = orb.is_signal_blocked("BUY", price=2655.0)
    assert bool(res_buy_blocked) is True
    assert res_buy_blocked[0] is True
    assert res_buy_blocked[1] == "price_not_above_or_high"

    # BlockResult iteration and tuple unpacking
    blocked, reason = res_buy_blocked
    assert blocked is True
    assert reason == "price_not_above_or_high"

    # BUY at 2662.0 (above or_high 2660.0) -> ALLOWED
    res_buy_allowed = orb.is_signal_blocked("BUY", price=2662.0)
    assert bool(res_buy_allowed) is False
    assert res_buy_allowed[1] == "breakout_confirmed"

    # SELL at 2645.0 (above or_low 2640.0) -> BLOCKED
    res_sell_blocked = orb.is_signal_blocked("SELL", price=2645.0)
    assert bool(res_sell_blocked) is True
    assert res_sell_blocked[1] == "price_not_below_or_low"

    # SELL at 2638.0 (below or_low 2640.0) -> ALLOWED
    res_sell_allowed = orb.is_signal_blocked("SELL", price=2638.0)
    assert bool(res_sell_allowed) is False


def test_wave60_profit_streak_confidence_mode():
    """Verify ProfitStreakBooster tracks consecutive wins and modifies TP multiplier."""
    booster = ProfitStreakBooster(streak_length=3, tp_multiplier=1.25)
    assert not booster.is_in_streak()
    assert booster.get_tp_multiplier() == 1.0

    # Record 2 wins
    booster.record_trade(True)
    booster.record_trade(15.5)  # numeric positive = win
    assert not booster.is_in_streak()
    assert booster.get_tp_multiplier() == 1.0

    # Record 3rd win -> streak active
    booster.record_trade(True)
    assert booster.is_in_streak()
    assert booster.get_tp_multiplier() == 1.25
    assert booster.adjust_tp(20.0) == 25.0

    # Record losing trade -> streak breaks immediately
    booster.record_trade(False)
    assert not booster.is_in_streak()
    assert booster.get_tp_multiplier() == 1.0
    assert booster.adjust_tp(20.0) == 20.0

    # Non-finite and invalid inputs
    assert booster.adjust_tp(-10.0) == 0.0
    assert booster.adjust_tp(float("nan")) == 0.0
    assert booster.adjust_tp(None) == 0.0


def test_wave59_ma_trend_filter_warmup_and_signals():
    """Verify MATrendFilter warm-up SMA seeding and trend direction gating."""
    filt = MATrendFilter(period=5)
    assert not filt.is_warmed_up

    # Warmup ticks: 4 ticks (period=5)
    for p in [100.0, 102.0, 104.0, 106.0]:
        filt.update(p)
        assert not filt.is_warmed_up
        # Never blocks during warmup
        res = filt.is_signal_blocked("BUY", price=p)
        assert bool(res) is False

    # 5th tick -> initializes EMA with SMA(100, 102, 104, 106, 108) = 104.0
    filt.update(108.0)
    assert filt.is_warmed_up
    assert filt.get_ema() == 104.0

    # Price 101.0 < EMA 104.0: BUY should be blocked
    res_buy = filt.is_signal_blocked("BUY", price=101.0)
    assert bool(res_buy) is True
    assert res_buy[1] == "price_below_ema"

    # Price 101.0 < EMA 104.0: SELL should be allowed
    res_sell = filt.is_signal_blocked("SELL", price=101.0)
    assert bool(res_sell) is False
    assert res_sell[1] == "trend_aligned"

    # Price 107.0 > EMA 104.0: SELL should be blocked
    res_sell_blocked = filt.is_signal_blocked("SELL", price=107.0)
    assert bool(res_sell_blocked) is True
    assert res_sell_blocked[1] == "price_above_ema"


def test_wave58_price_range_filter_dead_market_and_midnight_reset():
    """Verify PriceRangeFilter blocks flat sessions and resets at UTC midnight."""
    prf = PriceRangeFilter(min_range_pips=5.0, pip_value=0.1, min_ticks=10)
    day1 = datetime(2026, 10, 17, 10, 0, 0, tzinfo=timezone.utc)

    # Feed 10 ticks in a flat market [2650.00, 2650.20] (range = 0.20 / 0.1 = 2.0 pips)
    for i in range(10):
        prf.update(2650.00 + (i % 3) * 0.10, now_dt=day1)

    assert prf.get_range_pips(now_dt=day1) == 2.0
    assert prf.is_entry_blocked(now_dt=day1) is True

    # Expand range above 5.0 pips (e.g. 2650.80 -> range = 0.80 / 0.1 = 8.0 pips)
    prf.update(2650.80, now_dt=day1)
    assert prf.get_range_pips(now_dt=day1) == 8.0
    assert prf.is_entry_blocked(now_dt=day1) is False

    # Rollover to Day 2 at 00:01 UTC
    day2 = datetime(2026, 10, 18, 0, 1, 0, tzinfo=timezone.utc)
    prf.update(2652.00, now_dt=day2)
    info2 = prf.info(now_dt=day2)
    assert info2["ticks_today"] == 1
    assert info2["day_high"] == 2652.00
    assert info2["day_low"] == 2652.00
    assert prf.is_entry_blocked(now_dt=day2) is False  # ticks_today < min_ticks


def test_wave56_consecutive_loss_guard_trip_and_cooldown():
    """Verify ConsecutiveLossGuard triggers pause after N losses and resets on win."""
    guard = ConsecutiveLossGuard(max_losses=3, pause_seconds=1800.0)

    # 2 losses at t=1000.0
    guard.record_trade(False, now_ts=1000.0)
    guard.record_trade(False, now_ts=1005.0)
    assert not guard.is_entry_blocked(now_ts=1010.0)

    # 3rd loss -> trips 30 min (1800s) pause until 2810.0
    guard.record_trade(False, now_ts=1010.0)
    assert guard.is_entry_blocked(now_ts=1015.0) is True
    assert guard.is_entry_blocked(now_ts=2800.0) is True

    # Pause expires at t=2815.0
    assert guard.is_entry_blocked(now_ts=2815.0) is False

    # A winning trade resets the streak
    guard.record_trade(False, now_ts=3000.0)
    guard.record_trade(True, now_ts=3010.0)
    assert guard.info()["consecutive_losses"] == 0


def test_wave55_balance_floor_guard_halt_and_recovery():
    """Verify BalanceFloorGuard halts on breach, recovers with hysteresis, and handles blowout."""
    bfg = BalanceFloorGuard(floor_usd=9500.0, hysteresis_usd=50.0)

    # Normal balance
    bfg.update(9800.0)
    assert not bfg.is_entry_blocked()

    # Breach floor: $9400.0 < $9500.0
    bfg.update(9400.0)
    assert bfg.is_entry_blocked() is True
    assert bfg.is_halted is True

    # Intraday recovery below hysteresis: $9520.0 (< $9550.0) -> still halted
    bfg.update(9520.0)
    assert bfg.is_entry_blocked() is True

    # Intraday recovery above hysteresis: $9555.0 (>= $9550.0) -> halt lifted
    bfg.update(9555.0)
    assert bfg.is_entry_blocked() is False
    assert bfg.is_halted is False

    # Catastrophic blowout: balance <= 0
    bfg.update(-50.0)
    assert bfg.is_entry_blocked() is True
    assert bfg.is_halted is True


def test_wave54_max_spread_per_trade_cap_and_validation():
    """Verify MaxSpreadPerTrade respects cap, explicit parameter, and fails closed."""
    guard = MaxSpreadPerTrade(max_spread_pips=2.5)

    # Live spread updates
    guard.update(1.8)
    assert guard.is_entry_blocked() is False

    guard.update(3.0)
    assert guard.is_entry_blocked() is True

    # Explicit candidate spread parameter
    assert guard.is_entry_blocked(spread_pips=2.0) is False
    assert guard.is_entry_blocked(spread_pips=2.8) is True

    # Fail closed on invalid/negative spread
    assert guard.is_entry_blocked(spread_pips=-0.5) is True
    assert guard.is_entry_blocked(spread_pips=float("nan")) is True
    assert guard.is_entry_blocked(spread_pips="invalid") is True


def test_wave53_tick_reversal_guard_momentum_reversal():
    """Verify TickReversalGuard detects adverse momentum and blocks counter-trend entries."""
    guard = TickReversalGuard(n_ticks=3, block_duration=30.0)

    # Feed 4 prices falling consecutively: 100.0 -> 99.0 -> 98.0 -> 97.0
    for p in [100.0, 99.0, 98.0, 97.0]:
        guard.update(p)

    # Market is falling: BUY should be blocked at t=500.0
    assert guard.is_signal_blocked("BUY", now_ts=500.0) is True

    # SELL signal is with the momentum -> NOT blocked
    assert guard.is_signal_blocked("SELL", now_ts=500.0) is False

    # Cooldown expires at t=531.0
    assert guard.is_signal_blocked("BUY", now_ts=531.0) is False


def test_wave51_session_pnl_tracker_loss_limit_and_rollover():
    """Verify SessionPnLTracker limits loss per session and resets on session rollover."""
    tracker = SessionPnLTracker(loss_limit=-100.0)

    # London session: 10:00 UTC
    london_t = datetime(2026, 10, 17, 10, 0, 0, tzinfo=timezone.utc)
    tracker.record_trade(-40.0, now_dt=london_t)
    assert tracker.is_entry_blocked(now_dt=london_t) is False

    # Exceed session loss limit: -40 + -70 = -110.0 (< -100.0)
    tracker.record_trade(-70.0, now_dt=london_t)
    assert tracker.is_entry_blocked(now_dt=london_t) is True

    # Rollover to NY session: 18:00 UTC on same date -> clean bucket, unblocked
    ny_t = datetime(2026, 10, 17, 18, 0, 0, tzinfo=timezone.utc)
    assert tracker.is_entry_blocked(now_dt=ny_t) is False

    # Trade in NY session records cleanly
    tracker.record_trade(25.0, now_dt=ny_t)
    assert tracker.is_entry_blocked(now_dt=ny_t) is False
