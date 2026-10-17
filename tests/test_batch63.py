"""
tests/test_batch63.py
=====================
Hermetic unit tests for Batch 63:
1. CandlePatternFilter: Pattern detection (DOJI, HAMMER, INV_HAMMER) & direction bias
2. SpreadCostTracker: Daily spread accumulation, $50 threshold trip-wire & midnight rollover
3. EquityHighWatermark: All-time high tracking, 2% drawdown trip-wire & cooldown
4. ATRPositionSizer: Rolling ATR computation, dynamic SL/TP scaling & lot size quantization
5. LotRecoveryLadder: Mild martingale scaling, step clamping & reset on win
6. LondonOpenBooster: Liquidity window detection, discount multiplier & telemetry
7. PriceVelocityFilter: Chasing market protection, velocity calculation & expiration
8. WinRateGuard: Sample size gate, low win rate pause & streak clearance
9. TickVolumeFilter: Dead-market detection, volume spike trigger & cooldown release
10. SessionSpreadLimiter: Session-specific pip ceilings (Tokyo, London-pre, Default) & fail-closed safety
"""

import math
import time
from datetime import datetime, timezone, timedelta
import pytest

from wave50_candle_pattern_filter import CandlePatternFilter
from wave49_spread_cost_tracker import SpreadCostTracker
from wave48_equity_high_watermark import EquityHighWatermark
from wave47_atr_position_sizer import ATRPositionSizer
from wave46_lot_recovery_ladder import LotRecoveryLadder
from wave45_london_open_booster import LondonOpenBooster
from wave44_price_velocity_filter import PriceVelocityFilter
from wave43_win_rate_guard import WinRateGuard
from wave42_tick_volume_filter import TickVolumeFilter
from wave41_session_spread_limiter import SessionSpreadLimiter


def test_wave50_candle_pattern_filter_patterns_and_indecision():
    """Verify CandlePatternFilter classifies DOJI, HAMMER, and INV_HAMMER and gates signals."""
    cpf = CandlePatternFilter()

    # 1. DOJI: body < 10% of range -> INDECISION bias blocks both BUY and SELL
    # Open: 2650.0, High: 2651.0, Low: 2649.0, Close: 2650.05 (body = 0.05, range = 2.0 -> 2.5% body)
    cpf.update_candle(2650.0, 2651.0, 2649.0, 2650.05)
    assert cpf.get_bias() == "INDECISION"
    assert cpf.is_signal_blocked("BUY") is True
    assert cpf.is_signal_blocked("SELL") is True

    # 2. HAMMER: lower wick > 2x body, upper wick small -> BULLISH bias blocks SELL, allows BUY
    # Open: 2650.0, High: 2650.2, Low: 2647.0, Close: 2650.5 (body = 0.5, lower_wick = 3.0 > 1.0, upper_wick = 0.2 < 0.5)
    cpf.update_candle(2650.0, 2650.2, 2647.0, 2650.5)
    assert cpf.get_bias() == "BULLISH"
    assert cpf.is_signal_blocked("SELL") is True
    assert cpf.is_signal_blocked("BUY") is False

    # 3. INV_HAMMER: upper wick > 2x body, lower wick small -> BEARISH bias blocks BUY, allows SELL
    # Open: 2650.0, High: 2653.0, Low: 2649.8, Close: 2649.5 (body = 0.5, upper_wick = 3.0 > 1.0, lower_wick = 0.3 < 0.5)
    cpf.update_candle(2650.0, 2653.0, 2649.8, 2649.5)
    assert cpf.get_bias() == "BEARISH"
    assert cpf.is_signal_blocked("BUY") is True
    assert cpf.is_signal_blocked("SELL") is False


def test_wave49_spread_cost_tracker_daily_cap_and_rollover():
    """Verify SpreadCostTracker sums spread cost, trips at $50 cap, and resets at UTC midnight."""
    tracker = SpreadCostTracker(max_daily_usd=50.0)
    day1 = datetime(2026, 10, 17, 10, 0, 0, tzinfo=timezone.utc)

    # Trade 1: 2.0 pips on 0.10 lot -> 2.0 * (0.10/0.01) * $1.0 = $20.00
    tracker.record_trade(2.0, 0.10, now_dt=day1)
    assert tracker.get_daily_cost(now_dt=day1) == 20.0
    assert tracker.is_entry_blocked(now_dt=day1) is False

    # Trade 2: 2.5 pips on 0.10 lot -> $25.00 -> total $45.00 < $50.00
    tracker.record_trade(2.5, 0.10, now_dt=day1)
    assert tracker.get_daily_cost(now_dt=day1) == 45.0
    assert tracker.is_entry_blocked(now_dt=day1) is False

    # Trade 3: 1.0 pip on 0.10 lot -> $10.00 -> total $55.00 >= $50.00 -> BLOCKED
    tracker.record_trade(1.0, 0.10, now_dt=day1)
    assert tracker.get_daily_cost(now_dt=day1) == 55.0
    assert tracker.is_entry_blocked(now_dt=day1) is True

    # Rollover to Day 2: 00:05 UTC -> daily cost resets to 0.0, entries unblocked
    day2 = datetime(2026, 10, 18, 0, 5, 0, tzinfo=timezone.utc)
    assert tracker.is_entry_blocked(now_dt=day2) is False
    assert tracker.get_daily_cost(now_dt=day2) == 0.0
    # Total all-time spread cost is preserved
    assert tracker.total_cost_usd == 55.0


def test_wave48_equity_high_watermark_drawdown_block():
    """Verify EquityHighWatermark detects 2% drawdown and blocks entries for 30 minutes."""
    ehw = EquityHighWatermark(threshold_pct=2.0, block_sec=1800.0)

    # Establish initial watermark at $10,000.0
    ehw.update(10000.0, now_ts=1000.0)
    assert ehw.is_entry_blocked(now_ts=1000.0) is False

    # Equity dips 1% to $9,900.0 -> not blocked
    ehw.update(9900.0, now_ts=1010.0)
    assert ehw.is_entry_blocked(now_ts=1010.0) is False

    # Equity drops 2.5% to $9,750.0 -> trips 30m block (1800s until 2820.0)
    ehw.update(9750.0, now_ts=1020.0)
    assert ehw.is_entry_blocked(now_ts=1020.0) is True
    assert ehw.is_entry_blocked(now_ts=2000.0) is True

    # Pause expires at t=2825.0
    assert ehw.is_entry_blocked(now_ts=2825.0) is False


def test_wave47_atr_position_sizer_sl_tp_scaling_and_lot_quantization():
    """Verify ATRPositionSizer scales SL/TP by ATR ratio and quantizes lot size."""
    sizer = ATRPositionSizer(period=5)

    # Feed 6 bars with high/low/close: High=105, Low=95, Close=100 (TR=10.0)
    for _ in range(6):
        sizer.update(105.0, 95.0, 100.0)

    assert sizer.get_atr() > 0.0
    sl, tp = sizer.get_sl_tp(base_sl=30.0, base_tp=45.0)
    assert 15.0 <= sl <= 60.0
    assert 22.0 <= tp <= 90.0

    # Lot size calculation:
    # Balance: $10,000, risk_pct: 1% ($100 risk), SL: 30 pips, pip_value: $10/pip
    # Risk per lot: 30 * 10 = $300 -> Raw lot: 100 / 300 = 0.3333... -> quantized: 0.33
    lot = sizer.get_lot_size(account_balance=10000.0, risk_pct=0.01, sl_pips=30.0, pip_value=10.0)
    assert lot == 0.33

    # Invalid balance defaults safely to min_lot
    assert sizer.get_lot_size(account_balance=-500.0) == 0.01
    assert sizer.get_lot_size(account_balance=None) == 0.01


def test_wave46_lot_recovery_ladder_scaling_and_martingale_bounds():
    """Verify LotRecoveryLadder scales lot after consecutive losses and clamps to max_lot."""
    ladder = LotRecoveryLadder(
        base_lot=0.02,
        max_lot=0.10,
        multiplier=1.5,
        consecutive_trigger=2,
        max_recovery_steps=5,
    )
    assert ladder.current_lot == 0.02

    # 1st Loss: below trigger (2) -> remains 0.02
    ladder.record_trade(False)
    assert ladder.current_lot == 0.02

    # 2nd Loss: reaches trigger -> 0.02 * 1.5 = 0.03
    ladder.record_trade(False)
    assert ladder.current_lot == 0.03

    # 3rd Loss: 0.03 * 1.5 = 0.045 -> round-to-even 0.04
    ladder.record_trade(False)
    assert ladder.current_lot == 0.04

    # 4th Loss: 0.04 * 1.5 = 0.06
    ladder.record_trade(False)
    assert ladder.current_lot == 0.06

    # 5th Loss: 0.06 * 1.5 = 0.09
    ladder.record_trade(False)
    assert ladder.current_lot == 0.09

    # 6th Loss: 0.09 * 1.5 = 0.135 -> clamped to max_lot 0.10
    ladder.record_trade(False)
    assert ladder.current_lot == 0.10

    # Win resets back to base_lot
    ladder.record_trade(True)
    assert ladder.current_lot == 0.02


def test_wave45_london_open_booster_window_discount_and_multiplier():
    """Verify LondonOpenBooster discounts min_score during 07:00-08:00 UTC."""
    booster = LondonOpenBooster(start_hour_utc=7, end_hour_utc=8, score_discount=0.10)

    # 06:30 UTC: Outside London open window
    t_outside = datetime(2026, 10, 17, 6, 30, 0, tzinfo=timezone.utc)
    assert booster.is_active(now_dt=t_outside) is False
    assert booster.adjust_min_score(70.0, now_dt=t_outside) == 70.0

    # 07:20 UTC: Inside London open window -> 10% discount (70.0 * 0.90 = 63.0)
    t_inside = datetime(2026, 10, 17, 7, 20, 0, tzinfo=timezone.utc)
    assert booster.is_active(now_dt=t_inside) is True
    assert booster.adjust_min_score(70.0, now_dt=t_inside) == 63.0

    # 08:05 UTC: Window closed -> back to 70.0
    t_closed = datetime(2026, 10, 17, 8, 5, 0, tzinfo=timezone.utc)
    assert booster.adjust_min_score(70.0, now_dt=t_closed) == 70.0


def test_wave44_price_velocity_filter_fast_market_blocking():
    """Verify PriceVelocityFilter prevents chasing rapid market price movements."""
    pvf = PriceVelocityFilter(pip_limit=5.0, window_sec=3.0, pip_size=0.1)

    # Initial tick
    pvf.update(2650.0, now_ts=100.0)

    # Moderate move: 2.0 pips over 1s (0.2 / 0.1 = 2.0 pips < 5.0) -> allowed
    pvf.update(2650.2, now_ts=101.0)
    assert pvf.is_entry_blocked(now_ts=101.0) is False

    # Violent spike: jumps to 2650.8 at t=102.0 (range = 0.8 / 0.1 = 8.0 pips > 5.0) -> BLOCKED
    pvf.update(2650.8, now_ts=102.0)
    assert pvf.is_entry_blocked(now_ts=102.0) is True

    # 4 seconds later (t=106.0), older ticks fall out of 3.0s window -> unblocked
    assert pvf.is_entry_blocked(now_ts=106.0) is False


def test_wave43_win_rate_guard_losing_streak_pause_and_expiration():
    """Verify WinRateGuard evaluates sample size, triggers pause on poor win rate, and clears streak."""
    wrg = WinRateGuard(min_trades=5, win_rate_threshold=0.30, pause_duration_sec=1200.0)

    # 4 consecutive losses at t=1000.0 -> sample size 4 < 5, not paused yet
    for _ in range(4):
        wrg.record_trade(False, now_ts=1000.0)
    assert wrg.is_entry_blocked(now_ts=1000.0) is False

    # 5th loss -> sample size 5, win rate 0.0% < 30% -> pauses for 1200s (until 2205.0)
    wrg.record_trade(False, now_ts=1005.0)
    assert wrg.is_entry_blocked(now_ts=1005.0) is True
    assert wrg.seconds_remaining(now_ts=2000.0) == 205.0

    # Pause expires at t=2210.0 -> unblocks and clears stale loss results
    assert wrg.is_entry_blocked(now_ts=2210.0) is False
    assert wrg.info()["sample_size"] == 0


def test_wave42_tick_volume_filter_dead_market_and_volume_surge():
    """Verify TickVolumeFilter catches dead markets and excessive volume surges."""
    tvf = TickVolumeFilter(window_sec=10.0, min_ticks=4, max_ticks=50, spike_cooldown_sec=30.0)

    # Only 2 ticks in 10s -> DEAD_MARKET block
    tvf.update(now_ts=95.0)
    tvf.update(now_ts=98.0)
    assert tvf.is_entry_blocked(now_ts=100.0) is True

    # Add 5 more ticks at t=100.0 -> 7 ticks total in 10s (>= 4 and < 50) -> clear
    for _ in range(5):
        tvf.update(now_ts=100.0)
    assert tvf.is_entry_blocked(now_ts=100.0) is False

    # Surge: 55 ticks arrive at t=101.0 (>= max 50) -> VOLUME_SPIKE block with 30s cooldown
    for _ in range(55):
        tvf.update(now_ts=101.0)
    assert tvf.is_entry_blocked(now_ts=101.0) is True

    # In cooldown at t=115.0 -> blocked
    assert tvf.is_entry_blocked(now_ts=115.0) is True

    # Cooldown expires at t=132.0 (with sufficient healthy ticks)
    for _ in range(5):
        tvf.update(now_ts=131.5)
    assert tvf.is_entry_blocked(now_ts=132.0) is False


def test_wave41_session_spread_limiter_session_thresholds_and_fail_closed():
    """Verify SessionSpreadLimiter applies session limits (Tokyo, London-pre, Default) and fails closed."""
    limiter = SessionSpreadLimiter()

    # Tokyo session: 03:00 UTC (limit 1.5 pips)
    tokyo_dt = datetime(2026, 10, 17, 3, 0, 0, tzinfo=timezone.utc)
    assert limiter.is_entry_blocked(1.2, now_dt=tokyo_dt) is False
    assert limiter.is_entry_blocked(1.8, now_dt=tokyo_dt) is True

    # London pre-open: 06:30 UTC (limit 2.0 pips)
    london_pre_dt = datetime(2026, 10, 17, 6, 30, 0, tzinfo=timezone.utc)
    assert limiter.is_entry_blocked(1.8, now_dt=london_pre_dt) is False
    assert limiter.is_entry_blocked(2.3, now_dt=london_pre_dt) is True

    # Default session: 10:00 UTC (limit 3.0 pips)
    default_dt = datetime(2026, 10, 17, 10, 0, 0, tzinfo=timezone.utc)
    assert limiter.is_entry_blocked(2.5, now_dt=default_dt) is False
    assert limiter.is_entry_blocked(3.5, now_dt=default_dt) is True

    # Fail-closed validation for non-positive or non-finite inputs
    assert limiter.is_entry_blocked(-1.0, now_dt=default_dt) is True
    assert limiter.is_entry_blocked(float("nan"), now_dt=default_dt) is True
    assert limiter.is_entry_blocked("invalid", now_dt=default_dt) is True
    assert limiter.is_entry_blocked(None, now_dt=default_dt) is True
