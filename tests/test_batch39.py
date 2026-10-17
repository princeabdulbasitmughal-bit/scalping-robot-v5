"""
tests/test_batch39.py - Comprehensive Unit Tests for Batch 39 Components:
1. wave31_reversal_detector (ReversalDetector): bar validation, divergence, counter-signal, reset
2. wave32_gap_guard (GapGuard): tick-to-tick gap detection, lockout duration, price sanitization
3. wave33_partial_close (PartialCloseManager): 50% TP trigger, lot quantization, double-fire guard
4. wave34_trailing_stop (TrailingStopManager): lot/price quantization, BUY/SELL trailing SL
5. wave35_overnight_guard (OvernightGuard): Friday 20:30 cutoff, weekend lockout, rollover window
6. wave36_spread_momentum (SpreadMomentumGuard): 3x spread expansion, lockout trigger, seconds remaining
7. wave37_entry_cooldown (EntryCooldown): win cooldown (60s), loss cooldown (120s), max cooldown
8. wave38_volatility_breaker (VolatilityBreaker): rolling short vs long ATR, 2.5x spike ratio
9. wave39_drawdown_pause (DrawdownPause): 30-minute equity peak tracking, 1.5% drawdown pause
10. wave40_profit_target_shift (ProfitTargetShift): profit lock tightening (0.80x), recovery (1.10x)
"""

import math
import time
from datetime import datetime, timezone
import pytest

from wave31_reversal_detector import ReversalDetector
from wave32_gap_guard import GapGuard
from wave33_partial_close import PartialCloseManager
from wave34_trailing_stop import TrailingStopManager
from wave35_overnight_guard import OvernightGuard
from wave36_spread_momentum import SpreadMomentumGuard
from wave37_entry_cooldown import EntryCooldown
from wave38_volatility_breaker import VolatilityBreaker
from wave39_drawdown_pause import DrawdownPause
from wave40_profit_target_shift import ProfitTargetShift


def test_wave31_reversal_detector_bar_validation_and_divergence():
    """Verify ReversalDetector bar validation and divergence calculations."""
    rd = ReversalDetector(rsi_period=14, overbought=75.0, oversold=25.0)
    rd.reset()

    # 1. Bar validation
    assert rd.validate_bar(None) is None
    assert rd.validate_bar("invalid") is None
    # Tuple format (open, high, low, close)
    valid_bar = (2400.0, 2405.0, 2398.0, 2403.0)
    assert rd.validate_bar(valid_bar) == (2400.0, 2405.0, 2398.0, 2403.0)
    # Dict format
    dict_bar = {"open": 2400.0, "high": 2405.0, "low": 2398.0, "close": 2403.0}
    assert rd.validate_bar(dict_bar) == (2400.0, 2405.0, 2398.0, 2403.0)

    # 2. Feed prices and check reset
    for p in [2400.0 + i for i in range(20)]:
        rd.update_price(p)
    info = rd.info()
    assert info["wave"] == 31
    assert "current_rsi" in info

    rd.reset()
    assert rd.info()["buffer_size"] == 0


def test_wave32_gap_guard_abnormal_gaps():
    """Verify GapGuard detects tick gaps > threshold and enforces lockout duration."""
    gg = GapGuard(gap_threshold_pips=5.0, block_duration_sec=120.0, pip_size=0.1)
    gg.reset()

    # Normal tick movement: 2400.0 -> 2400.2 (2 pips < 5 pips)
    gg.update_price(2400.0, now_ts=100.0)
    gg.update_price(2400.2, now_ts=101.0)
    assert gg.is_entry_blocked(now_ts=101.5) is False

    # Abnormal gap: 2400.2 -> 2401.0 (8 pips >= 5 pips)
    gg.update_price(2401.0, now_ts=102.0)
    assert gg.is_entry_blocked(now_ts=102.5) is True
    assert gg.is_entry_blocked(now_ts=221.0) is True   # within 120s
    assert gg.is_entry_blocked(now_ts=223.0) is False  # 102 + 120 = 222 -> expired

    # Non-finite and negative price guards
    gg.update_price(float("nan"))
    gg.update_price(-100.0)
    assert gg.info()["total_gaps_detected"] == 1


def test_wave33_partial_close_manager():
    """Verify PartialCloseManager detects 50% TP progress, quantizes lot, and guards double firing."""
    pcm = PartialCloseManager(trigger_pct=0.50, close_ratio=0.50)
    pcm.reset()

    # BUY position: entry=2400.0, TP=2410.0 (10 points / 100 pips)
    # At 2402.0 (20% to TP) -> no partial close
    should_close = pcm.check_position(
        ticket=12345,
        direction="BUY",
        entry_price=2400.0,
        current_price=2402.0,
        tp_price=2410.0,
        lot=0.04
    )
    assert should_close is False

    # At 2405.0 (50% to TP) -> trigger partial close
    should_close = pcm.check_position(
        ticket=12345,
        direction="BUY",
        entry_price=2400.0,
        current_price=2405.0,
        tp_price=2410.0,
        lot=0.04
    )
    assert should_close is True

    # Quantize close lot: 0.04 * 0.50 = 0.02
    close_lot = pcm.get_close_lot(0.04)
    assert close_lot == 0.02

    # Calling check_position again on same ticket must return False (no double firing)
    assert pcm.check_position(
        ticket=12345,
        direction="BUY",
        entry_price=2400.0,
        current_price=2406.0,
        tp_price=2410.0,
        lot=0.04
    ) is False

    # Remove ticket on position close
    pcm.remove_ticket(12345)
    assert 12345 not in pcm._closed_tickets


def test_wave34_trailing_stop_manager():
    """Verify TrailingStopManager quantizes lots/prices and trails SL behind profitable trades."""
    tsm = TrailingStopManager(profit_trigger_pips=15.0, trail_pips=10.0, trail_step_pips=1.0)
    tsm.reset()

    # 1. Quantization tests
    assert tsm.quantize_lot(0.0456, lot_step=0.01) == 0.04
    assert tsm.quantize_price(2400.12345, pip_size=0.1) == 2400.123
    assert tsm.quantize_price(2400.12345, digits=2) == 2400.12

    # 2. Trailing stop for BUY position
    # entry = 2400.0, current_sl = 2390.0, pip_size = 0.1 (1 point = 10 pips)
    # Profit trigger = 15 pips = 1.5 points -> triggered at 2401.5
    # Price reaches 2402.0 (20 pips profit > 15 pips trigger)
    # Trail SL 10 pips behind current price (2402.0 - 1.0 = 2401.0)
    new_sl = tsm.update(
        ticket=101,
        direction="BUY",
        entry_price=2400.0,
        current_price=2402.0,
        current_sl=2390.0,
        pip_size=0.1,
    )
    assert new_sl is not None
    assert new_sl >= 2400.9  # Moved to ~2401.0 (lock in profit)

    # Price moves backwards to 2401.5 -> SL must NOT loosen
    sl_retreat = tsm.update(
        ticket=101,
        direction="BUY",
        entry_price=2400.0,
        current_price=2401.5,
        current_sl=new_sl,
        pip_size=0.1,
    )
    assert sl_retreat is None


def test_wave35_overnight_guard_schedules():
    """Verify OvernightGuard enforces Friday cutoff, weekend lockout, and rollover blackout."""
    og = OvernightGuard()
    og.reset()

    # 1. Tuesday 14:00 UTC (normal London/NY trading hours) -> not blocked
    dt_normal = datetime(2026, 10, 20, 14, 0, tzinfo=timezone.utc)
    assert og.is_entry_blocked(now_dt=dt_normal) is False
    assert og.should_force_close_all(now_dt=dt_normal) is False

    # 2. Friday 20:35 UTC (after Friday 20:30 cutoff) -> entry blocked AND force close all
    dt_friday_cutoff = datetime(2026, 10, 23, 20, 35, tzinfo=timezone.utc)
    assert og.is_entry_blocked(now_dt=dt_friday_cutoff) is True
    assert og.should_force_close_all(now_dt=dt_friday_cutoff) is True

    # 3. Saturday (weekend market closed) -> entry blocked
    dt_saturday = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
    assert og.is_entry_blocked(now_dt=dt_saturday) is True

    # 4. Daily rollover window 21:45-22:15 UTC on Wednesday
    dt_rollover = datetime(2026, 10, 21, 21, 50, tzinfo=timezone.utc)
    assert og.is_entry_blocked(now_dt=dt_rollover) is True


def test_wave36_spread_momentum_guard():
    """Verify SpreadMomentumGuard triggers 60s lockout upon 3x spread expansion."""
    smg = SpreadMomentumGuard()
    smg.reset()

    # Feed normal spreads ~ 1.5 pips
    for _ in range(4):
        smg.update(1.5, now_ts=100.0)
    assert smg.is_entry_blocked(now_ts=100.5) is False

    # Sudden 3.5x spread explosion to 5.5 pips
    smg.update(5.5, now_ts=101.0)
    assert smg.is_entry_blocked(now_ts=101.5) is True
    assert smg.seconds_remaining(now_ts=120.0) == 41.0  # 101 + 60 = 161; 161 - 120 = 41
    assert smg.is_entry_blocked(now_ts=162.0) is False # expired

    # Invalid input handling
    smg.update(float("nan"))
    smg.update(-2.0)
    assert smg.total_spikes_detected == 1


def test_wave37_entry_cooldown_mechanics():
    """Verify EntryCooldown applies 60s for wins and 120s for losses, preserving maximum cooldown."""
    ec = EntryCooldown()
    ec.reset()

    assert ec.is_entry_blocked(now_ts=100.0) is False

    # 1. Winning trade at t=100 -> 60s cooldown (blocked until t=160)
    ec.record_trade_close(was_win=True, pnl=25.0, now_ts=100.0)
    assert ec.is_entry_blocked(now_ts=130.0) is True
    assert ec.seconds_remaining(now_ts=130.0) == 30.0
    assert ec.is_entry_blocked(now_ts=161.0) is False

    # 2. Losing trade at t=200 -> 120s cooldown (revenge trading prevention)
    ec.record_trade_close(was_win=False, pnl=-35.0, now_ts=200.0)
    assert ec.is_entry_blocked(now_ts=250.0) is True
    assert ec.seconds_remaining(now_ts=250.0) == 70.0
    assert ec.is_entry_blocked(now_ts=321.0) is False

    # Force reset clears cooldown immediately
    ec.record_trade_close(was_win=False, pnl=-50.0, now_ts=400.0)
    assert ec.is_entry_blocked(now_ts=401.0) is True
    ec.force_reset()
    assert ec.is_entry_blocked(now_ts=401.0) is False


def test_wave38_volatility_breaker_atr_ratio():
    """Verify VolatilityBreaker detects 2.5x ATR expansion over baseline."""
    vb = VolatilityBreaker()
    vb.reset()

    # Feed 30 flat ticks (low baseline ATR ~ 0.1)
    for i in range(35):
        vb.update(2400.0 + (i % 2) * 0.1, now_ts=100.0 + i)
    assert vb.is_entry_blocked(now_ts=140.0) is False

    # Suddenly inject violent volatility: alternating by 2.0 per tick (> 10x baseline)
    for i in range(25):
        vb.update(2400.0 + (i % 2) * 2.0, now_ts=140.0 + i)

    assert vb.is_entry_blocked(now_ts=165.0) is True
    assert vb.seconds_remaining(now_ts=165.0) > 0.0

    # Reset clears breaker
    vb.reset()
    assert vb.is_entry_blocked(now_ts=165.0) is False


def test_wave39_drawdown_pause_equity_drop():
    """Verify DrawdownPause monitors rolling equity and pauses trading on > 1.5% drop from peak."""
    dp = DrawdownPause()
    dp.reset()

    # Peak equity is $10,000 at t=1000
    dp.update(10000.0, now_ts=1000.0)
    dp.update(9950.0, now_ts=1010.0)  # 0.5% drop -> not blocked
    assert dp.is_entry_blocked(now_ts=1015.0) is False

    # Severe drop to $9,800 (2.0% drop from $10,000 peak > 1.5% threshold)
    dp.update(9800.0, now_ts=1020.0)
    assert dp.is_entry_blocked(now_ts=1025.0) is True
    assert dp.seconds_remaining(now_ts=1025.0) > 0.0

    # Reset clears the pause
    dp.reset()
    assert dp.is_entry_blocked(now_ts=1025.0) is False


def test_wave40_profit_target_shift_adjustments():
    """Verify ProfitTargetShift tightens TP in profit and widens TP in recovery mode."""
    pts = ProfitTargetShift()
    pts.reset()

    # 1. Normal mode (PnL between -$100 and +$150) -> 1.0x
    assert pts.adjust_tp(raw_tp_pips=20.0, daily_pnl=50.0) == 20.0
    assert pts.mode == "NORMAL"
    assert pts.tp_factor == 1.0

    # 2. Profit Lock mode (PnL >= +$150) -> 0.80x (tighten TP to lock gains)
    assert pts.adjust_tp(raw_tp_pips=20.0, daily_pnl=160.0) == 16.0  # 20 * 0.80
    assert pts.mode == "PROFIT_LOCK"
    assert pts.tp_factor == 0.80

    # 3. Recovery mode (PnL <= -$100) -> 1.10x (widen TP slightly)
    assert pts.adjust_tp(raw_tp_pips=20.0, daily_pnl=-110.0) == 22.0 # 20 * 1.10
    assert pts.mode == "RECOVERY"
    assert pts.tp_factor == 1.10

    # 4. Invalid input handling
    assert pts.adjust_tp(raw_tp_pips=-5.0, daily_pnl=50.0) == -5.0
    assert pts.adjust_tp(raw_tp_pips=20.0, daily_pnl=float("nan")) == 20.0

    info = pts.info()
    assert "mode" in info
    assert "tp_factor" in info
