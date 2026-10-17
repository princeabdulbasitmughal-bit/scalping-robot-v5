"""
tests/test_batch41.py - Comprehensive Unit Tests for Batch 41 Components:
1. wave51_session_pnl_tracker (SessionPnLTracker): Tokyo/London/NY session PnL & -$100 loss limit
2. wave52_rsi_ob_os_filter (RSIOverboughtOversold): Wilder's RSI, overbought BUY block, oversold SELL block
3. wave53_tick_reversal_guard (TickReversalGuard): 5 adverse tick momentum reversal & 30s cooldown
4. wave54_max_spread_per_trade (MaxSpreadPerTrade): single-trade 2.5-pip spread cap & fail-closed validation
5. wave55_balance_floor_guard (BalanceFloorGuard): $9,500 balance floor halt & $50 hysteresis recovery
6. wave56_consecutive_loss_guard (ConsecutiveLossGuard): 3 consecutive losses 30-min pause & win reset
7. wave57_hourly_pnl_map (HourlyPnLMap): hourly bucketed PnL, advisory 0.5x lot scaling, rollover
8. wave58_price_range_filter (PriceRangeFilter): flat daily range (<5.0 pips) block & midnight reset
9. wave59_ma_trend_filter (MATrendFilter): EMA-50 trend alignment, subscriptable BlockResult, warm-up
10. wave60_profit_streak_booster (ProfitStreakBooster): 3 consecutive wins 1.2x TP boost & loss reset
"""

import math
import time
from datetime import datetime, timezone
import pytest

from wave51_session_pnl_tracker import SessionPnLTracker
from wave52_rsi_ob_os_filter import RSIOverboughtOversold
from wave53_tick_reversal_guard import TickReversalGuard
from wave54_max_spread_per_trade import MaxSpreadPerTrade
from wave55_balance_floor_guard import BalanceFloorGuard
from wave56_consecutive_loss_guard import ConsecutiveLossGuard
from wave57_hourly_pnl_map import HourlyPnLMap
from wave58_price_range_filter import PriceRangeFilter
from wave59_ma_trend_filter import MATrendFilter
from wave60_profit_streak_booster import ProfitStreakBooster


def test_wave51_session_pnl_tracker():
    """Verify SessionPnLTracker tracks PnL by session and blocks entry when loss limit hit."""
    tracker = SessionPnLTracker(loss_limit=-100.0)
    tracker.reset()

    # Tokyo session (04:00 UTC)
    dt_tokyo = datetime(2026, 10, 20, 4, 0, tzinfo=timezone.utc)
    # Trade 1: -$60.0 loss -> session PnL = -$60.0 > -$100.0 -> allowed
    tracker.record_trade(-60.0, now_dt=dt_tokyo)
    assert tracker.is_entry_blocked(now_dt=dt_tokyo) is False

    # Trade 2: -$50.0 loss -> session PnL = -$110.0 <= -$100.0 -> blocked
    tracker.record_trade(-50.0, now_dt=dt_tokyo)
    assert tracker.is_entry_blocked(now_dt=dt_tokyo) is True

    # London session (10:00 UTC) -> new session not blocked
    dt_london = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)
    assert tracker.is_entry_blocked(now_dt=dt_london) is False

    tracker.reset()
    assert tracker.is_entry_blocked(now_dt=dt_tokyo) is False


def test_wave52_rsi_ob_os_filter():
    """Verify RSIOverboughtOversold computes Wilder's RSI and blocks extreme counter-trades."""
    rsi_filter = RSIOverboughtOversold(period=14, ob_block=75.0, os_block=25.0)
    rsi_filter.reset()

    # Feed rising prices (strong bull run -> RSI rises above 75)
    for p in range(25):
        rsi_filter.update(2400.0 + p * 2.0)

    rsi_val = rsi_filter.rsi
    assert rsi_val >= 75.0
    # Overbought: BUY is blocked, SELL is allowed
    assert rsi_filter.is_entry_blocked("BUY") is True
    assert rsi_filter.is_entry_blocked("SELL") is False

    # Feed falling prices (sharp plunge -> RSI drops below 25)
    rsi_filter.reset()
    for p in range(25):
        rsi_filter.update(2450.0 - p * 2.0)

    assert rsi_filter.rsi <= 25.0
    # Oversold: SELL is blocked, BUY is allowed
    assert rsi_filter.is_entry_blocked("SELL") is True
    assert rsi_filter.is_entry_blocked("BUY") is False


def test_wave53_tick_reversal_guard():
    """Verify TickReversalGuard detects 5 consecutive adverse ticks and enforces a 30s block."""
    trg = TickReversalGuard(n_ticks=5, block_duration=30.0)
    trg.reset()

    # 1. Feed 6 consecutive falling ticks: 2405.0 -> 2400.0
    for i in range(6):
        trg.update(2405.0 - i * 1.0)

    # Adverse to BUY: 5 consecutive down ticks -> BUY is blocked
    assert trg.is_signal_blocked("BUY", now_ts=100.0) is True
    # In agreement with SELL -> SELL is not blocked
    assert trg.is_signal_blocked("SELL", now_ts=100.0) is False

    # 30-second cooldown expires at t=131
    assert trg.is_signal_blocked("BUY", now_ts=131.0) is False


def test_wave54_max_spread_per_trade():
    """Verify MaxSpreadPerTrade blocks entry when live spread exceeds 2.5 pips."""
    mspt = MaxSpreadPerTrade(max_spread_pips=2.5)
    mspt.reset()

    # Normal spread: 1.8 pips <= 2.5 -> allowed
    mspt.update(1.8)
    assert mspt.is_entry_blocked() is False

    # High spread: 3.0 pips > 2.5 -> blocked
    mspt.update(3.0)
    assert mspt.is_entry_blocked() is True

    # Direct candidate spread check
    assert mspt.is_entry_blocked(spread_pips=2.2) is False
    assert mspt.is_entry_blocked(spread_pips=2.8) is True

    # Invalid spread fails closed
    assert mspt.is_entry_blocked(spread_pips=-1.0) is True
    assert mspt.is_entry_blocked(spread_pips=float("nan")) is True


def test_wave55_balance_floor_guard():
    """Verify BalanceFloorGuard halts trading when balance drops below floor with hysteresis recovery."""
    bfg = BalanceFloorGuard(floor_usd=9500.0, hysteresis_usd=50.0)
    bfg.reset()

    dt_today = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    # Balance $9,800 > $9,500 floor -> allowed
    bfg.update(9800.0, now_dt=dt_today)
    assert bfg.is_entry_blocked(now_dt=dt_today) is False
    assert bfg.is_halted is False

    # Drop to $9,450 < $9,500 floor -> HALTED
    bfg.update(9450.0, now_dt=dt_today)
    assert bfg.is_entry_blocked(now_dt=dt_today) is True
    assert bfg.is_halted is True

    # Balance rises to $9,520 (above floor but below floor + hysteresis $9,550) -> remains halted
    bfg.update(9520.0, now_dt=dt_today)
    assert bfg.is_entry_blocked(now_dt=dt_today) is True

    # Balance rises to $9,560 (above floor + hysteresis $9,550) -> auto-recovers
    bfg.update(9560.0, now_dt=dt_today)
    assert bfg.is_entry_blocked(now_dt=dt_today) is False
    assert bfg.is_halted is False


def test_wave56_consecutive_loss_guard():
    """Verify ConsecutiveLossGuard blocks entries for 30 minutes after 3 consecutive losses."""
    clg = ConsecutiveLossGuard(max_losses=3, pause_seconds=1800.0)
    clg.reset()

    # 2 losses: below trigger (3) -> not blocked
    clg.record_trade(won=False, now_ts=100.0)
    clg.record_trade(won=False, now_ts=110.0)
    assert clg.is_entry_blocked(now_ts=120.0) is False

    # 3rd loss: trigger reached -> 1800s pause (blocked until t=1920)
    clg.record_trade(won=False, now_ts=120.0)
    assert clg.is_entry_blocked(now_ts=150.0) is True
    assert clg.is_entry_blocked(now_ts=1921.0) is False  # expired

    # Win resets the streak
    clg.record_trade(won=True, now_ts=1922.0)
    clg.record_trade(won=False, now_ts=1930.0)
    assert clg.is_entry_blocked(now_ts=1935.0) is False


def test_wave57_hourly_pnl_map():
    """Verify HourlyPnLMap tracks PnL by UTC hour and applies 0.5x advisory lot scaling on losses."""
    hpm = HourlyPnLMap(loss_threshold_usd=-30.0)
    hpm.reset()

    dt_h14 = datetime(2026, 10, 20, 14, 30, tzinfo=timezone.utc)
    # Trade 1: -$15.0 at 14:00 UTC -> PnL = -$15.0 > -$30.0 -> normal 1.0x multiplier
    hpm.record_trade(-15.0, now_dt=dt_h14)
    assert hpm.get_lot_multiplier(now_dt=dt_h14) == 1.0

    # Trade 2: -$20.0 at 14:00 UTC -> total hour PnL = -$35.0 <= -$30.0 -> 0.5x multiplier
    hpm.record_trade(-20.0, now_dt=dt_h14)
    assert hpm.get_lot_multiplier(now_dt=dt_h14) == 0.5

    # 15:00 UTC hour is unaffected -> 1.0x
    dt_h15 = datetime(2026, 10, 20, 15, 10, tzinfo=timezone.utc)
    assert hpm.get_lot_multiplier(now_dt=dt_h15) == 1.0


def test_wave58_price_range_filter():
    """Verify PriceRangeFilter blocks entry when daily price range is too narrow (< 5 pips)."""
    prf = PriceRangeFilter(min_range_pips=5.0, pip_value=0.1, min_ticks=10)
    prf.reset()

    dt_today = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)
    # Feed 15 flat ticks between 2400.0 and 2400.2 (range = 0.2 points = 2 pips < 5 pips)
    for i in range(15):
        prf.update(2400.0 + (i % 3) * 0.1, now_dt=dt_today)

    # Range = 2 pips < 5 pips -> market too flat -> blocked
    assert prf.is_entry_blocked(now_dt=dt_today) is True
    assert prf.get_range_pips(now_dt=dt_today) == 2.0

    # Wide tick expanding range to 2401.0 (range = 1.0 point = 10 pips >= 5 pips) -> allowed
    prf.update(2401.0, now_dt=dt_today)
    assert prf.get_range_pips(now_dt=dt_today) == 10.0
    assert prf.is_entry_blocked(now_dt=dt_today) is False


def test_wave59_ma_trend_filter():
    """Verify MATrendFilter enforces EMA trend alignment and yields subscriptable BlockResult."""
    mtf = MATrendFilter(period=10)
    mtf.reset()

    # Warm-up phase: first 10 ticks seed SMA (no blocks)
    for p in range(10):
        mtf.update(2400.0 + p * 0.5)

    assert mtf.is_warmed_up is True
    ema = mtf.get_ema()
    assert 2400.0 < ema < 2405.0

    # Current price 2410.0 > EMA (~2403.0) -> Uptrend: BUY allowed, SELL blocked
    mtf.update(2410.0)
    res_buy = mtf.is_signal_blocked("BUY")
    assert bool(res_buy) is False
    assert res_buy[0] is False

    res_sell = mtf.is_signal_blocked("SELL")
    assert bool(res_sell) is True
    assert res_sell[0] is True
    assert "above_ema" in res_sell[1]


def test_wave60_profit_streak_booster():
    """Verify ProfitStreakBooster raises TP multiplier to 1.2x on 3 consecutive wins and resets on loss."""
    psb = ProfitStreakBooster(streak_length=3, tp_multiplier=1.2)
    psb.reset()

    assert psb.is_in_streak() is False
    assert psb.get_tp_multiplier() == 1.0
    assert psb.adjust_tp(20.0) == 20.0

    # 1st and 2nd win: not yet in streak
    psb.record_trade(won=True)
    psb.record_trade(won=True)
    assert psb.is_in_streak() is False
    assert psb.get_tp_multiplier() == 1.0

    # 3rd win: triggers confidence streak
    psb.record_trade(won=True)
    assert psb.is_in_streak() is True
    assert psb.get_tp_multiplier() == 1.2
    assert psb.adjust_tp(20.0) == 24.0  # 20 * 1.2

    # Losing trade resets streak
    psb.record_trade(won=False)
    assert psb.is_in_streak() is False
    assert psb.get_tp_multiplier() == 1.0
    assert psb.adjust_tp(20.0) == 20.0
