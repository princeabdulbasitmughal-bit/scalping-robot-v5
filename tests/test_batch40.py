"""
tests/test_batch40.py - Comprehensive Unit Tests for Batch 40 Components:
1. wave41_session_spread_limiter (SessionSpreadLimiter): Tokyo/London_pre/Default spread gates, fail-closed
2. wave42_tick_volume_filter (TickVolumeFilter): dead market (<4 ticks) & volume spike (>50 ticks/surge)
3. wave43_win_rate_guard (WinRateGuard): low rolling win rate (<30%) 20-min pause, post-pause reset
4. wave44_price_velocity_filter (PriceVelocityFilter): rapid price velocity chase block & recovery
5. wave45_london_open_booster (LondonOpenBooster): London open (07:00-08:00 UTC) 10% min_score discount
6. wave46_lot_recovery_ladder (LotRecoveryLadder): consecutive loss lot scaling & win reset
7. wave47_atr_position_sizer (ATRPositionSizer): 14-period ATR dynamic SL/TP scaling & lot sizer
8. wave48_equity_high_watermark (EquityHighWatermark): 2% drop from peak watermark 30-min pause
9. wave49_spread_cost_tracker (SpreadCostTracker): daily spread accumulation & $50 daily cap
10. wave50_candle_pattern_filter (CandlePatternFilter): DOJI indecision block, HAMMER/INV_HAMMER direction
"""

import math
import time
from datetime import datetime, timezone
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


def test_wave41_session_spread_limiter():
    """Verify SessionSpreadLimiter limits spreads by session and fails closed on invalid inputs."""
    ssl = SessionSpreadLimiter()

    # Tokyo session (03:00 UTC) -> max 1.5 pips
    dt_tokyo = datetime(2026, 10, 20, 3, 0, tzinfo=timezone.utc)
    assert ssl.is_entry_blocked(spread_pips=1.2, now_dt=dt_tokyo) is False
    assert ssl.is_entry_blocked(spread_pips=1.8, now_dt=dt_tokyo) is True

    # London pre-open (06:30 UTC) -> max 2.0 pips
    dt_london_pre = datetime(2026, 10, 20, 6, 30, tzinfo=timezone.utc)
    assert ssl.is_entry_blocked(spread_pips=1.8, now_dt=dt_london_pre) is False
    assert ssl.is_entry_blocked(spread_pips=2.5, now_dt=dt_london_pre) is True

    # Default / regular London/NY hours (14:00 UTC) -> max 3.0 pips
    dt_ny = datetime(2026, 10, 20, 14, 0, tzinfo=timezone.utc)
    assert ssl.is_entry_blocked(spread_pips=2.8, now_dt=dt_ny) is False
    assert ssl.is_entry_blocked(spread_pips=3.2, now_dt=dt_ny) is True

    # Fail closed on negative or non-finite inputs
    assert ssl.is_entry_blocked(spread_pips=-1.0, now_dt=dt_ny) is True
    assert ssl.is_entry_blocked(spread_pips=float("nan"), now_dt=dt_ny) is True


def test_wave42_tick_volume_filter():
    """Verify TickVolumeFilter blocks on dead markets and volume surges with cooldown."""
    tvf = TickVolumeFilter(window_sec=10.0, min_ticks=4, max_ticks=20, spike_cooldown_sec=30.0)
    tvf.reset()

    # 1. Dead market: only 2 ticks in 10s window (< 4 min_ticks) -> blocked
    tvf.update(now_ts=100.0)
    tvf.update(now_ts=102.0)
    assert tvf.is_entry_blocked(now_ts=105.0) is True

    # 2. Healthy market: 6 ticks in 10s window (between 4 and 20) -> allowed
    for t in range(4):
        tvf.update(now_ts=103.0 + t)
    assert tvf.is_entry_blocked(now_ts=107.0) is False

    # 3. Volume spike: inject 25 ticks rapidly (> 20 max_ticks) -> spike cooldown triggered
    for t in range(25):
        tvf.update(now_ts=108.0 + t * 0.05)
    assert tvf.is_entry_blocked(now_ts=110.0) is True

    # Reset clears buffers and unblocks
    tvf.reset()
    assert tvf.info()["blocked_count_total"] == 0


def test_wave43_win_rate_guard():
    """Verify WinRateGuard pauses trading when rolling win rate drops below 30%."""
    wrg = WinRateGuard(min_trades=5, win_rate_threshold=0.30, pause_duration_sec=600.0)
    wrg.reset()

    # 1. First 4 trades: 4 losses -> insufficient sample (< 5) -> not blocked
    for _ in range(4):
        wrg.record_trade(won=False, now_ts=100.0)
    assert wrg.is_entry_blocked(now_ts=100.5) is False

    # 2. 5th trade: 5th loss (0/5 = 0% < 30%) -> triggers 600s pause (until t=700)
    wrg.record_trade(won=False, now_ts=100.0)
    assert wrg.is_entry_blocked(now_ts=150.0) is True
    assert wrg.seconds_remaining(now_ts=150.0) == 550.0
    assert wrg.is_entry_blocked(now_ts=701.0) is False  # expired

    # Reset clears guard
    wrg.reset()
    assert wrg.is_entry_blocked(now_ts=150.0) is False


def test_wave44_price_velocity_filter():
    """Verify PriceVelocityFilter prevents chasing rapid price runs and recovers."""
    pvf = PriceVelocityFilter(pip_limit=5.0, window_sec=3.0)
    pvf.reset()

    # Normal tick movement: 2400.0 to 2400.3 over 3.0s (1.0 pip/s < 5.0) -> allowed
    pvf.update(price=2400.0, now_ts=100.0)
    pvf.update(price=2400.3, now_ts=103.0)
    assert pvf.is_entry_blocked(now_ts=103.0) is False

    # Rapid price spike: 2400.3 to 2403.0 over 0.5s (27 pips in 0.5s = 54 pips/s > 5.0) -> blocked
    pvf.update(price=2403.0, now_ts=103.5)
    assert pvf.is_entry_blocked(now_ts=103.5) is True

    # Cooldown recovery after 3 seconds without extreme velocity
    pvf.update(price=2403.1, now_ts=107.0)
    assert pvf.is_entry_blocked(now_ts=107.5) is False


def test_wave45_london_open_booster():
    """Verify LondonOpenBooster applies 10% min_score discount during London Open (07:00-08:00 UTC)."""
    lob = LondonOpenBooster(start_hour_utc=7, end_hour_utc=8, score_discount=0.10)
    lob.reset()

    # London Open (07:30 UTC): 10% discount -> 55 min_score becomes 49.5
    dt_open = datetime(2026, 10, 20, 7, 30, tzinfo=timezone.utc)
    assert lob.is_active(now_dt=dt_open) is True
    assert lob.adjust_min_score(min_score=55.0, now_dt=dt_open) == 49.5

    # Outside London Open (10:00 UTC): no discount -> 55 min_score unchanged
    dt_outside = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)
    assert lob.is_active(now_dt=dt_outside) is False
    assert lob.adjust_min_score(min_score=55.0, now_dt=dt_outside) == 55.0

    info = lob.info(now_dt=dt_open)
    assert info["london_open_active"] is True
    assert info["score_multiplier"] == 0.90


def test_wave46_lot_recovery_ladder():
    """Verify LotRecoveryLadder scales lot size after consecutive losses and resets on win."""
    lrl = LotRecoveryLadder(
        base_lot=0.02,
        max_lot=0.10,
        multiplier=1.5,
        consecutive_trigger=2,
    )
    lrl.reset()

    assert lrl.current_lot == 0.02

    # 1 loss: below trigger (2) -> still base_lot 0.02
    lrl.record_trade(won=False)
    assert lrl.current_lot == 0.02

    # 2 losses: trigger reached -> scales by 1.5x (0.02 * 1.5 = 0.03)
    lrl.record_trade(won=False)
    assert lrl.current_lot == 0.03

    # 3 losses: 0.03 * 1.5 = 0.045 -> banker's rounded to even 0.04
    lrl.record_trade(won=False)
    assert lrl.current_lot == 0.04

    # Win: resets immediately to base_lot 0.02
    lrl.record_trade(won=True)
    assert lrl.current_lot == 0.02


def test_wave47_atr_position_sizer():
    """Verify ATRPositionSizer maintains rolling ATR and adjusts SL/TP proportionally."""
    aps = ATRPositionSizer(period=5)
    aps.reset()

    # Feed 10 bars with range ~ 1.0 (10 pips)
    for i in range(10):
        aps.update(high=2401.0 + i, low=2400.0 + i, close=2400.5 + i)

    info = aps.info()
    assert info["atr"] > 0.0

    # Retrieve SL/TP adjusted by ATR
    sl, tp = aps.get_sl_tp(base_sl=30.0, base_tp=45.0)
    assert 15.0 <= sl <= 60.0
    assert 22.0 <= tp <= 90.0

    # Lot size calculation based on account balance and risk %
    lot = aps.get_lot_size(account_balance=10000.0, risk_pct=1.0, sl_pips=30.0, pip_value=1.0)
    assert lot >= 0.01

    aps.reset()
    assert aps.info()["buffer_len"] == 0


def test_wave48_equity_high_watermark():
    """Verify EquityHighWatermark detects 2% drop from peak watermark and blocks entries."""
    ehw = EquityHighWatermark(threshold_pct=2.0, block_sec=1800.0)
    ehw.reset()

    # Establish $10,000 watermark at t=1000
    ehw.update(10000.0, now_ts=1000.0)
    ehw.update(9900.0, now_ts=1010.0)  # 1.0% drop < 2.0% -> not blocked
    assert ehw.is_entry_blocked(now_ts=1015.0) is False

    # Drop to $9,750 (2.5% drop from $10,000 peak >= 2.0% threshold) -> blocked for 1800s
    ehw.update(9750.0, now_ts=1020.0)
    assert ehw.is_entry_blocked(now_ts=1025.0) is True
    assert ehw.is_entry_blocked(now_ts=2819.0) is True   # within 1800s
    assert ehw.is_entry_blocked(now_ts=2821.0) is False  # 1020 + 1800 = 2820 -> expired

    # Reset clears watermark and blocks
    ehw.reset()
    assert ehw.is_entry_blocked(now_ts=1025.0) is False


def test_wave49_spread_cost_tracker():
    """Verify SpreadCostTracker accumulates daily spread costs and blocks when >= $50 cap."""
    sct = SpreadCostTracker(max_daily_usd=50.0)
    sct.reset()

    dt_today = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)
    # Trade 1: spread=2.0 pips, lot=0.05 -> cost = 2.0 * (0.05 / 0.01) * $1.0 = $10.0
    sct.record_trade(spread_pips=2.0, lot_size=0.05, now_dt=dt_today)
    assert sct.is_entry_blocked(now_dt=dt_today) is False
    assert sct.daily_cost_usd == 10.0

    # Trade 2: spread=4.0 pips, lot=0.10 -> cost = 4.0 * 10 * $1.0 = $40.0 -> total = $50.0
    sct.record_trade(spread_pips=4.0, lot_size=0.10, now_dt=dt_today)
    assert sct.daily_cost_usd == 50.0
    assert sct.is_entry_blocked(now_dt=dt_today) is True

    # Next day: automatic daily reset
    dt_next_day = datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc)
    assert sct.is_entry_blocked(now_dt=dt_next_day) is False
    assert sct.daily_cost_usd == 0.0


def test_wave50_candle_pattern_filter():
    """Verify CandlePatternFilter blocks opposing or indecisive candle patterns."""
    cpf = CandlePatternFilter()
    cpf.reset()

    # 1. Doji candle (body < 10% range): open=2400.0, high=2405.0, low=2395.0, close=2400.1
    cpf.update_candle(o=2400.0, h=2405.0, l=2395.0, c=2400.1)
    assert cpf.is_signal_blocked("BUY") is True
    assert cpf.is_signal_blocked("SELL") is True

    # 2. Bullish Hammer (body >= 10% range, lower_wick > 2*body, upper_wick < body):
    # open=2408.0, high=2410.0, low=2400.0, close=2410.0
    # Hammer is BULLISH -> blocks SELL, allows BUY
    cpf.update_candle(o=2408.0, h=2410.0, l=2400.0, c=2410.0)
    assert cpf.is_signal_blocked("SELL") is True
    assert cpf.is_signal_blocked("BUY") is False

    # 3. Inverted Hammer / Shooting star (body >= 10% range, upper_wick > 2*body, lower_wick < body):
    # open=2400.0, high=2410.0, low=2400.0, close=2402.0
    # Inverted Hammer is BEARISH -> blocks BUY, allows SELL
    cpf.update_candle(o=2400.0, h=2410.0, l=2400.0, c=2402.0)
    assert cpf.is_signal_blocked("BUY") is True
    assert cpf.is_signal_blocked("SELL") is False

    cpf.reset()
    assert cpf.info()["last_pattern"] == "NONE"
