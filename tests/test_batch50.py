"""
Test Suite: Batch 50 — Wave 51 through Wave 60 Verification
============================================================
Hermetic unit test suite verifying:
  1. Wave 51: Session PnL Tracker (Tokyo/London/NY session loss limits)
  2. Wave 52: RSI Overbought/Oversold Filter (Wilder RSI calculation & BUY/SELL blocks)
  3. Wave 53: Tick Reversal Guard (N-consecutive adverse tick momentum detection & cooldown)
  4. Wave 54: Max Spread Per Trade (Single-trade live spread cap & fail-closed validation)
  5. Wave 55: Balance Floor Guard (Hard floor halt, intraday hysteresis & new UTC day recovery)
  6. Wave 56: Consecutive Loss Guard (Anti-revenge 30-min pause after N consecutive losses)
  7. Wave 57: Hourly PnL Map (UTC hour loss tracking & 0.5x advisory lot multiplier)
  8. Wave 58: Price Range Filter (Intraday high/low tracking & flat market lockout)
  9. Wave 59: MA Trend Filter (EMA trend alignment & subscriptable BlockResult)
 10. Wave 60: Profit Streak Booster (Confidence mode TP multiplier after win streak)
"""

import datetime
from datetime import timezone
import math
import pytest

from wave51_session_pnl_tracker import SessionPnLTracker
from wave52_rsi_ob_os_filter import RSIOverboughtOversold
from wave53_tick_reversal_guard import TickReversalGuard
from wave54_max_spread_per_trade import MaxSpreadPerTrade
from wave55_balance_floor_guard import BalanceFloorGuard
from wave56_consecutive_loss_guard import ConsecutiveLossGuard
from wave57_hourly_pnl_map import HourlyPnLMap
from wave58_price_range_filter import PriceRangeFilter
from wave59_ma_trend_filter import MATrendFilter, BlockResult
from wave60_profit_streak_booster import ProfitStreakBooster


# ── Test 1: Wave 51 Session PnL Tracker ───────────────────────────────────────
def test_wave51_session_pnl_tracker():
    """Verify SessionPnLTracker blocks entries when session losses exceed limit."""
    tracker = SessionPnLTracker(loss_limit=-100.0)

    # Tokyo session: 04:00 UTC
    dt_tokyo = datetime.datetime(2026, 10, 17, 4, 0, tzinfo=timezone.utc)
    assert tracker.is_entry_blocked(now_dt=dt_tokyo) is False

    # Record first loss of -$40.0 in Tokyo
    tracker.record_trade(-40.0, now_dt=dt_tokyo)
    assert tracker.is_entry_blocked(now_dt=dt_tokyo) is False

    # Record second loss of -$70.0 in Tokyo -> total Tokyo PnL = -$110 < -$100
    tracker.record_trade(-70.0, now_dt=dt_tokyo)
    assert tracker.is_entry_blocked(now_dt=dt_tokyo) is True

    allowed, reason = tracker.is_trading_allowed(now_dt=dt_tokyo)
    assert allowed is False
    assert "SESSION_LOSS_LIMIT" in reason

    # London session (09:00 UTC) has separate clean bucket -> not blocked
    dt_london = datetime.datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)
    assert tracker.is_entry_blocked(now_dt=dt_london) is False

    # Manual unblock clears blocked status
    tracker.unblock_session(session="Tokyo", now_dt=dt_tokyo)
    assert tracker.is_entry_blocked(now_dt=dt_tokyo) is False


# ── Test 2: Wave 52 RSI OB/OS Filter ──────────────────────────────────────────
def test_wave52_rsi_ob_os_filter():
    """Verify RSIOverboughtOversold blocks BUY at overbought and SELL at oversold extremes."""
    filter_rsi = RSIOverboughtOversold(period=14, ob_block=75.0, os_block=25.0)

    # During warmup (< 15 ticks), signals are not blocked
    for p in range(10):
        filter_rsi.update(2400.0 + p)
    assert filter_rsi.is_signal_blocked("BUY") is False
    assert filter_rsi.is_signal_blocked("SELL") is False

    # Feed rising price trend to drive RSI into overbought territory (> 75)
    for p in range(10, 50):
        filter_rsi.update(2400.0 + p * 2.0)
    assert filter_rsi.get_rsi() > 75.0
    assert filter_rsi.is_signal_blocked("BUY") is True
    assert filter_rsi.is_signal_blocked("SELL") is False

    # Reset and feed falling trend to drive RSI into oversold territory (< 25)
    filter_rsi.reset()
    for p in range(50):
        filter_rsi.update(2500.0 - p * 2.0)
    assert filter_rsi.get_rsi() < 25.0
    assert filter_rsi.is_signal_blocked("SELL") is True
    assert filter_rsi.is_signal_blocked("BUY") is False


# ── Test 3: Wave 53 Tick Reversal Guard ───────────────────────────────────────
def test_wave53_tick_reversal_guard():
    """Verify TickReversalGuard detects adverse tick momentum and engages cooldown."""
    guard = TickReversalGuard(n_ticks=5, block_duration=30.0)

    t0 = 50000.0
    # Feed 5 consecutive falling ticks: 100 -> 99 -> 98 -> 97 -> 96 -> 95
    prices = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0]
    for p in prices:
        guard.update(p)

    # Buying into consecutive down-ticks is blocked
    assert guard.is_signal_blocked("BUY", now_ts=t0) is True
    assert guard.is_signal_blocked("SELL", now_ts=t0) is False

    # During cooldown (t0 + 15 < t0 + 30), BUY remains blocked
    assert guard.is_signal_blocked("BUY", now_ts=t0 + 15) is True

    # After cooldown expires (t0 + 35 > t0 + 30), BUY is allowed
    assert guard.is_signal_blocked("BUY", now_ts=t0 + 35) is False


# ── Test 4: Wave 54 Max Spread Per Trade ──────────────────────────────────────
def test_wave54_max_spread_per_trade():
    """Verify MaxSpreadPerTrade blocks entry when live spread exceeds threshold."""
    guard = MaxSpreadPerTrade(max_spread_pips=2.5)

    # Spread within acceptable boundary (1.8 pips <= 2.5)
    guard.update(1.8)
    assert guard.is_entry_blocked() is False

    # Spread exceeds threshold (3.2 pips > 2.5)
    guard.update(3.2)
    assert guard.is_entry_blocked() is True

    # Direct query with explicit argument
    assert guard.is_entry_blocked(spread_pips=2.0) is False
    assert guard.is_entry_blocked(spread_pips=2.9) is True

    # Non-finite or negative input fails closed (blocks entry)
    assert guard.is_entry_blocked(spread_pips=float('nan')) is True
    assert guard.is_entry_blocked(spread_pips=-1.0) is True


# ── Test 5: Wave 55 Balance Floor Guard ───────────────────────────────────────
def test_wave55_balance_floor_guard():
    """Verify BalanceFloorGuard halts trading below floor and recovers with hysteresis."""
    guard = BalanceFloorGuard(floor_usd=9500.0, hysteresis_usd=50.0)

    dt1 = datetime.datetime(2026, 10, 17, 10, 0, tzinfo=timezone.utc)
    # Healthy balance above floor
    guard.update(9800.0, now_dt=dt1)
    assert guard.is_entry_blocked(now_dt=dt1) is False
    assert guard.is_halted is False

    # Balance drops below floor -> halt triggered
    guard.update(9400.0, now_dt=dt1)
    assert guard.is_entry_blocked(now_dt=dt1) is True
    assert guard.is_halted is True

    # Minor bounce below hysteresis (9520 < 9500 + 50) -> remains halted
    guard.update(9520.0, now_dt=dt1)
    assert guard.is_entry_blocked(now_dt=dt1) is True

    # Recovery above floor + hysteresis (9560 >= 9550) -> halt lifted
    guard.update(9560.0, now_dt=dt1)
    assert guard.is_entry_blocked(now_dt=dt1) is False
    assert guard.is_halted is False

    # Catastrophic blowout (balance <= 0) halts immediately
    guard.update(0.0, now_dt=dt1)
    assert guard.is_entry_blocked(now_dt=dt1) is True


# ── Test 6: Wave 56 Consecutive Loss Guard ────────────────────────────────────
def test_wave56_consecutive_loss_guard():
    """Verify ConsecutiveLossGuard blocks entry for cooldown period after N losses."""
    guard = ConsecutiveLossGuard(max_losses=3, pause_seconds=1800.0)

    t0 = 60000.0
    # 2 consecutive losses -> below threshold of 3
    guard.record_trade(won=False, now_ts=t0)
    guard.record_trade(won=False, now_ts=t0 + 10)
    assert guard.is_entry_blocked(now_ts=t0 + 10) is False

    # 3rd consecutive loss -> triggers 1800s pause
    guard.record_trade(won=False, now_ts=t0 + 20)
    assert guard.is_entry_blocked(now_ts=t0 + 20) is True
    assert guard.is_entry_blocked(now_ts=t0 + 1000) is True

    # Pause expires after 1800s (at t0 + 1850)
    assert guard.is_entry_blocked(now_ts=t0 + 1850) is False

    # Win resets streak
    guard.record_trade(won=True, now_ts=t0 + 1900)
    assert guard.is_entry_blocked(now_ts=t0 + 1900) is False


# ── Test 7: Wave 57 Hourly PnL Map ────────────────────────────────────────────
def test_wave57_hourly_pnl_map():
    """Verify HourlyPnLMap tracks hourly PnL and reduces lot multiplier after losses."""
    hourly_map = HourlyPnLMap(loss_threshold_usd=-30.0)

    # 14:00 UTC
    dt_14 = datetime.datetime(2026, 10, 17, 14, 15, tzinfo=timezone.utc)
    assert hourly_map.get_lot_multiplier(now_dt=dt_14) == 1.0

    # First small loss: -$10
    hourly_map.record_trade(-10.0, now_dt=dt_14)
    assert hourly_map.get_lot_multiplier(now_dt=dt_14) == 1.0

    # Second loss of -$25 -> total hour 14 PnL = -$35 < -$30 -> lot scaled to 0.5x
    hourly_map.record_trade(-25.0, now_dt=dt_14)
    assert hourly_map.get_lot_multiplier(now_dt=dt_14) == 0.5

    # Hour 15:00 UTC has separate clean bucket -> multiplier 1.0
    dt_15 = datetime.datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc)
    assert hourly_map.get_lot_multiplier(now_dt=dt_15) == 1.0


# ── Test 8: Wave 58 Price Range Filter ────────────────────────────────────────
def test_wave58_price_range_filter():
    """Verify PriceRangeFilter blocks entries during dead/flat daily ranges."""
    filt = PriceRangeFilter(min_range_pips=5.0, pip_value=0.1, min_ticks=10)

    dt = datetime.datetime(2026, 10, 17, 11, 0, tzinfo=timezone.utc)
    # Feed 15 ticks within flat range: 2400.0 to 2400.2 (0.2 points = 2.0 pips < 5.0)
    for i in range(15):
        filt.update(2400.0 + (i % 3) * 0.1, now_dt=dt)

    assert filt.get_range_pips(now_dt=dt) == 2.0
    assert filt.is_entry_blocked(now_dt=dt) is True

    # Expand range by feeding 2401.0 (range becomes 2400.0 - 2401.0 = 1.0 pt = 10.0 pips)
    filt.update(2401.0, now_dt=dt)
    assert filt.get_range_pips(now_dt=dt) == 10.0
    assert filt.is_entry_blocked(now_dt=dt) is False


# ── Test 9: Wave 59 MA Trend Filter ───────────────────────────────────────────
def test_wave59_ma_trend_filter():
    """Verify MATrendFilter validates trend alignment against EMA-50."""
    trend = MATrendFilter(period=10)

    # Seed EMA with 10 ticks at 2400.0
    for _ in range(10):
        trend.update(2400.0)
    assert trend.is_warmed_up is True
    assert trend.get_ema() == 2400.0

    # Trend filter evaluates BUY when price is above EMA
    res_buy_good = trend.is_signal_blocked("BUY", price=2405.0)
    assert bool(res_buy_good) is False
    assert res_buy_good.reason == "trend_aligned"

    # Counter-trend BUY (price below EMA) is blocked
    res_buy_bad = trend.is_signal_blocked("BUY", price=2395.0)
    assert bool(res_buy_bad) is True
    assert res_buy_bad.reason == "price_below_ema"

    # Counter-trend SELL (price above EMA) is blocked
    res_sell_bad = trend.is_signal_blocked("SELL", price=2405.0)
    assert bool(res_sell_bad) is True
    assert res_sell_bad.reason == "price_above_ema"


# ── Test 10: Wave 60 Profit Streak Booster ────────────────────────────────────
def test_wave60_profit_streak_booster():
    """Verify ProfitStreakBooster engages confidence mode TP boost after win streak."""
    booster = ProfitStreakBooster(streak_length=3, tp_multiplier=1.2)

    assert booster.is_in_streak() is False
    assert booster.get_tp_multiplier() == 1.0

    # 2 consecutive wins -> below target streak of 3
    booster.record_trade(won=True)
    booster.record_trade(won=True)
    assert booster.is_in_streak() is False
    assert booster.get_tp_multiplier() == 1.0

    # 3rd consecutive win -> confidence mode engaged!
    booster.record_trade(won=True)
    assert booster.is_in_streak() is True
    assert booster.get_tp_multiplier() == 1.2
    assert booster.adjust_tp(10.0) == 12.0

    # A losing trade immediately deactivates confidence mode
    booster.record_trade(won=False)
    assert booster.is_in_streak() is False
    assert booster.get_tp_multiplier() == 1.0
    assert booster.adjust_tp(10.0) == 10.0
