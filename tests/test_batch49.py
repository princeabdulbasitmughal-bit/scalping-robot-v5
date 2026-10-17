"""
Batch 49 Test Suite:
1. wave41_session_spread_limiter.py session limits (Tokyo, London pre-open, default) & input rejection
2. wave42_tick_volume_filter.py dead market detection and volume spike cooldown
3. wave43_win_rate_guard.py rolling win rate degradation pause & expiry reset
4. wave44_price_velocity_filter.py price velocity limit & chasing suppression
5. wave45_london_open_booster.py London open window score discount & multiplier
6. wave46_lot_recovery_ladder.py mild martingale scaling on loss streaks & win reset
7. wave47_atr_position_sizer.py dynamic SL/TP scaling and risk-based lot sizing
8. wave48_equity_high_watermark.py all-time watermark tracking & drawdown block
9. wave49_spread_cost_tracker.py cumulative spread tracking & daily dollar ceiling block
10. wave50_candle_pattern_filter.py candle pattern bias (Doji, Bull/Bear Engulfing) signal filter
"""
import datetime
from datetime import timezone
import math
import time

import pytest

from wave41_session_spread_limiter import SessionSpreadLimiter
from wave42_tick_volume_filter import TickVolumeFilter
from wave43_win_rate_guard import WinRateGuard
from wave44_price_velocity_filter import PriceVelocityFilter
from wave45_london_open_booster import LondonOpenBooster
from wave46_lot_recovery_ladder import LotRecoveryLadder
from wave47_atr_position_sizer import ATRPositionSizer
from wave48_equity_high_watermark import EquityHighWatermark
from wave49_spread_cost_tracker import SpreadCostTracker
from wave50_candle_pattern_filter import CandlePatternFilter


# ── Test 1: Wave 41 Session Spread Limiter ────────────────────────────────────
def test_wave41_session_spread_limiter():
    """Verify SessionSpreadLimiter enforces session thresholds and rejects bad inputs."""
    ssl = SessionSpreadLimiter()

    # Tokyo session (03:00 UTC) -> limit 1.5 pips
    dt_tokyo = datetime.datetime(2026, 10, 17, 3, 0, tzinfo=timezone.utc)
    assert ssl.is_entry_blocked(1.2, now_dt=dt_tokyo) is False
    assert ssl.is_entry_blocked(1.8, now_dt=dt_tokyo) is True

    # London pre-open (06:30 UTC) -> limit 2.0 pips
    dt_london_pre = datetime.datetime(2026, 10, 17, 6, 30, tzinfo=timezone.utc)
    assert ssl.is_entry_blocked(1.8, now_dt=dt_london_pre) is False
    assert ssl.is_entry_blocked(2.2, now_dt=dt_london_pre) is True

    # Default session (14:00 UTC) -> limit 3.0 pips
    dt_default = datetime.datetime(2026, 10, 17, 14, 0, tzinfo=timezone.utc)
    assert ssl.is_entry_blocked(2.8, now_dt=dt_default) is False
    assert ssl.is_entry_blocked(3.5, now_dt=dt_default) is True

    # Bad input rejection (non-finite, negative, None, bool)
    assert ssl.is_entry_blocked(-1.0) is True
    assert ssl.is_entry_blocked(float("nan")) is True
    assert ssl.is_entry_blocked(None) is True
    assert ssl.is_entry_blocked(True) is True


# ── Test 2: Wave 42 Tick Volume Filter ────────────────────────────────────────
def test_wave42_tick_volume_filter():
    """Verify TickVolumeFilter detects dead markets and volume surges."""
    tvf = TickVolumeFilter(window_sec=10.0, min_ticks=4, max_ticks=20, spike_cooldown_sec=30.0)

    t0 = 10000.0
    # Dead market: only 2 ticks in 10s window (< 4 min_ticks)
    tvf.update(now_ts=t0)
    tvf.update(now_ts=t0 + 2)
    assert tvf.is_entry_blocked(now_ts=t0 + 5) is True

    # Healthy volume: 6 ticks in window (4 <= 6 <= 20)
    for i in range(4):
        tvf.update(now_ts=t0 + 3 + i)
    assert tvf.is_entry_blocked(now_ts=t0 + 7) is False

    # Volume surge: feed 25 rapid ticks exceeding max_ticks=20
    for i in range(25):
        tvf.update(now_ts=t0 + 8)
    assert tvf.is_entry_blocked(now_ts=t0 + 8) is True
    # In cooldown at t0 + 15 (cooldown expires at t0 + 8 + 30 = t0 + 38)
    assert tvf.info(now_ts=t0 + 15)["spike_cooldown_remaining_sec"] > 0
    assert tvf.is_entry_blocked(now_ts=t0 + 15) is True
    assert "SPIKE_COOLDOWN" in tvf.get_block_reason()

    # Cooldown expires after 30s (at t0 + 40)
    assert tvf.info(now_ts=t0 + 40)["spike_cooldown_remaining_sec"] == 0.0


# ── Test 3: Wave 43 Win Rate Guard ────────────────────────────────────────────
def test_wave43_win_rate_guard():
    """Verify WinRateGuard pauses trading when rolling win rate drops below 30%."""
    wrg = WinRateGuard(min_trades=5, win_rate_threshold=0.30, pause_duration_sec=600.0)

    t0 = 20000.0
    # 4 consecutive losses (insufficient sample size < 5)
    for _ in range(4):
        wrg.record_trade(won=False, now_ts=t0)
        assert wrg.is_entry_blocked(now_ts=t0) is False

    # 5th trade is a loss -> 0% win rate (< 30%) triggers 600s pause
    wrg.record_trade(won=False, now_ts=t0)
    assert wrg.is_entry_blocked(now_ts=t0) is True
    assert wrg.seconds_remaining(now_ts=t0 + 100) > 0

    # Pause expires after 600s
    assert wrg.is_entry_blocked(now_ts=t0 + 650) is False

    # Reset clears pause
    wrg.record_trade(won=False, now_ts=t0 + 700)
    wrg.reset()
    assert wrg.is_entry_blocked(now_ts=t0 + 700) is False


# ── Test 4: Wave 44 Price Velocity Filter ─────────────────────────────────────
def test_wave44_price_velocity_filter():
    """Verify PriceVelocityFilter blocks entries during aggressive price moves."""
    pvf = PriceVelocityFilter(pip_limit=5.0, window_sec=3.0, pip_size=0.1)

    t0 = 30000.0
    # Normal velocity (move of 0.2 points = 2.0 pips <= 5.0)
    pvf.update(2400.0, now_ts=t0)
    pvf.update(2400.2, now_ts=t0 + 1)
    assert pvf.is_entry_blocked(now_ts=t0 + 1) is False

    # Velocity spike: price jumps by 1.0 point (10.0 pips > 5.0) in 1s
    pvf.update(2401.2, now_ts=t0 + 2)
    assert pvf.is_entry_blocked(now_ts=t0 + 2) is True

    # 4s later, older tick drops out of 3.0s window -> velocity normalizes
    pvf.update(2401.3, now_ts=t0 + 6)
    assert pvf.is_entry_blocked(now_ts=t0 + 6) is False


# ── Test 5: Wave 45 London Open Booster ───────────────────────────────────────
def test_wave45_london_open_booster():
    """Verify LondonOpenBooster discounts entry threshold during London open window."""
    lob = LondonOpenBooster(start_hour_utc=7, end_hour_utc=8, score_discount=0.10)

    # Inside London open window (07:30 UTC)
    dt_open = datetime.datetime(2026, 10, 17, 7, 30, tzinfo=timezone.utc)
    assert lob.is_active(now_dt=dt_open) is True
    assert lob.adjust_min_score(60.0, now_dt=dt_open) == 54.0
    assert lob.multiplier == 0.90

    # Outside London open window (11:00 UTC)
    dt_outside = datetime.datetime(2026, 10, 17, 11, 0, tzinfo=timezone.utc)
    assert lob.is_active(now_dt=dt_outside) is False
    assert lob.adjust_min_score(60.0, now_dt=dt_outside) == 60.0


# ── Test 6: Wave 46 Lot Recovery Ladder ───────────────────────────────────────
def test_wave46_lot_recovery_ladder():
    """Verify LotRecoveryLadder scales position on loss streak and resets on win."""
    ladder = LotRecoveryLadder(
        base_lot=0.02,
        max_lot=0.10,
        multiplier=1.5,
        consecutive_trigger=2,
    )

    assert ladder.get_lot() == 0.02

    # 1st loss: below trigger=2 -> stays at base lot
    ladder.record_trade(won=False)
    assert ladder.get_lot() == 0.02

    # 2nd loss: hits trigger -> 0.02 * 1.5 = 0.03
    ladder.record_trade(won=False)
    assert ladder.get_lot() == 0.03

    # 3rd loss: 0.03 * 1.5 = 0.045 -> rounded to 0.04
    ladder.record_trade(won=False)
    assert ladder.get_lot() == 0.04

    # Win immediately resets lot to base_lot
    ladder.record_trade(won=True)
    assert ladder.get_lot() == 0.02


# ── Test 7: Wave 47 ATR Position Sizer ────────────────────────────────────────
def test_wave47_atr_position_sizer():
    """Verify ATRPositionSizer dynamically scales SL/TP and quantizes lot size."""
    sizer = ATRPositionSizer(period=5)

    # Feed 10 bars with steady volatility (high=2402.0, low=2400.0 -> range 2.0)
    for i in range(10):
        sizer.update(high=2402.0, low=2400.0, close=2401.0)

    sl, tp = sizer.get_sl_tp(base_sl=30.0, base_tp=45.0)
    assert 15.0 <= sl <= 60.0
    assert 22.0 <= tp <= 90.0

    # Risk-based lot calculation
    # Balance $10,000, 1% risk = $100 risk. SL = 30 pips. $10 per pip -> lot ~ 0.33
    lot = sizer.get_lot_size(account_balance=10000.0, risk_pct=0.01, sl_pips=30.0, pip_value=10.0)
    assert lot == 0.33
    assert sizer.get_lot_size(None) == 0.01


# ── Test 8: Wave 48 Equity High Watermark ──────────────────────────────────────
def test_wave48_equity_high_watermark():
    """Verify EquityHighWatermark blocks entries when drawdown exceeds 2.0%."""
    ehw = EquityHighWatermark(threshold_pct=2.0, block_sec=1800)

    t0 = 40000.0
    ehw.update(10000.0, now_ts=t0)
    assert ehw.is_entry_blocked(now_ts=t0) is False

    # 1.0% drop ($9,900.0) -> allowed
    ehw.update(9900.0, now_ts=t0 + 10)
    assert ehw.is_entry_blocked(now_ts=t0 + 10) is False

    # 2.5% drop ($9,750.0 vs peak $10,000.0) -> triggers 30-min block
    ehw.update(9750.0, now_ts=t0 + 20)
    assert ehw.is_entry_blocked(now_ts=t0 + 20) is True
    assert ehw.is_entry_blocked(now_ts=t0 + 1000) is True

    # 30 minutes later block expires
    assert ehw.is_entry_blocked(now_ts=t0 + 1850) is False


# ── Test 9: Wave 49 Spread Cost Tracker ───────────────────────────────────────
def test_wave49_spread_cost_tracker():
    """Verify SpreadCostTracker accumulates daily spread costs and halts on limit."""
    sct = SpreadCostTracker(max_daily_usd=50.0)

    dt_day1 = datetime.datetime(2026, 10, 17, 10, 0, tzinfo=timezone.utc)
    # Trade 1: 2.0 pips spread on 0.10 lot -> 2.0 * (0.10/0.01) * $1.0 = $20.0
    sct.record_trade(spread_pips=2.0, lot_size=0.10, now_dt=dt_day1)
    assert sct.daily_cost_usd == 20.0
    assert sct.is_entry_blocked(now_dt=dt_day1) is False

    # Trade 2: 3.5 pips spread on 0.10 lot -> $35.0 (total $55.0 >= $50.0 cap)
    sct.record_trade(spread_pips=3.5, lot_size=0.10, now_dt=dt_day1)
    assert sct.daily_cost_usd == 55.0
    assert sct.is_entry_blocked(now_dt=dt_day1) is True

    # Next day: automatic rollover resets daily cost
    dt_day2 = datetime.datetime(2026, 10, 18, 10, 0, tzinfo=timezone.utc)
    assert sct.is_entry_blocked(now_dt=dt_day2) is False
    assert sct.daily_cost_usd == 0.0


# ── Test 10: Wave 50 Candle Pattern Filter ────────────────────────────────────
def test_wave50_candle_pattern_filter():
    """Verify CandlePatternFilter identifies patterns and gates contradicting signals."""
    cpf = CandlePatternFilter()

    # 1. Doji candle (open == close, large range) -> INDECISION blocks all entries
    cpf.update_candle(o=2400.0, h=2405.0, l=2395.0, c=2400.0)
    assert cpf.is_entry_blocked("BUY") is True
    assert cpf.is_entry_blocked("SELL") is True

    # 2. Bullish candle (close >> open, small upper wick) -> blocks SELL, allows BUY
    cpf.update_candle(o=2395.0, h=2405.0, l=2394.0, c=2404.5)
    assert cpf.is_entry_blocked("SELL") is True
    assert cpf.is_entry_blocked("BUY") is False

    # 3. Bearish candle (open >> close, small lower wick) -> blocks BUY, allows SELL
    cpf.update_candle(o=2405.0, h=2406.0, l=2395.0, c=2395.5)
    assert cpf.is_entry_blocked("BUY") is True
    assert cpf.is_entry_blocked("SELL") is False
