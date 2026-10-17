"""
tests/test_batch65.py
=====================
Hermetic unit tests for Batch 65:
1. GapGuard: Abnormal tick gap detection, lockout timer & cooldown recovery
2. ReversalDetector: OHLC bar validation (dict/tuple formats) & invalid filtering
3. ReversalDetector: Cutler's RSI computation & cold-start handling
4. SessionLotBooster: Overlap window, vol index, win rate confluence & lot boost
5. AdaptiveTp: Volatility ATR proxy, extend/shrink multipliers & reward-to-risk ratio
6. MomentumConfirmation: Directional tick alignment, BUY/SELL confirmation & rejection
7. CorrelationGuard: Pearson correlation calculation, zero-variance & non-finite handling
8. CorrelationGuard: Signal cluster density spike trigger & cooldown release
9. TimeFilter: High-impact economic release window blocking & safe trading zones
10. TimeFilter: Multi-format datetime normalization & custom release schedule
"""

import math
import time
from datetime import datetime, timezone
import pytest

from wave32_gap_guard import GapGuard
from wave31_reversal_detector import ReversalDetector
from wave30_session_lot_booster import SessionLotBooster
from wave29_adaptive_tp import AdaptiveTp
from wave28_momentum_confirmation import MomentumConfirmation
from wave27_correlation_guard import CorrelationGuard, compute_pearson_correlation
from wave26_time_filter import TimeFilter


def test_wave32_gap_guard_gap_detection_and_lockout():
    """Verify GapGuard detects abnormal tick gaps and applies a timed lockout."""
    gg = GapGuard(gap_threshold_pips=5.0, block_duration_sec=120.0, pip_size=0.1)

    # 1. First tick establishes baseline price
    gg.update_price(2650.0, now_ts=100.0)
    assert gg.is_entry_blocked(now_ts=100.0) is False

    # 2. Normal move of 3.0 pips (0.3 / 0.1 = 3.0 < 5.0) -> not blocked
    gg.update_price(2650.3, now_ts=101.0)
    assert gg.is_entry_blocked(now_ts=101.0) is False

    # 3. Abnormal gap of 6.0 pips (0.6 / 0.1 = 6.0 >= 5.0) -> trips 120s lockout
    gg.update_price(2650.9, now_ts=102.0)
    assert gg.is_entry_blocked(now_ts=102.0) is True
    allowed, reason = gg.is_trading_allowed(now_ts=102.0)
    assert not allowed
    assert "6.0p gap active" in reason

    # 4. Lockout active at t=150.0
    assert gg.is_entry_blocked(now_ts=150.0) is True

    # 5. Lockout expires at t=225.0 (> 120s from gap at 102.0)
    assert gg.is_entry_blocked(now_ts=225.0) is False


def test_wave31_reversal_detector_bar_validation():
    """Verify ReversalDetector validates OHLC bar formats and filters corrupt data."""
    # 1. Valid Dict Bar
    d_bar = {"open": 2650.0, "high": 2655.0, "low": 2648.0, "close": 2652.0}
    res_d = ReversalDetector.validate_bar(d_bar)
    assert res_d == (2650.0, 2655.0, 2648.0, 2652.0)

    # 2. Valid Tuple Bar (4 elements)
    t_bar = (2650.0, 2655.0, 2648.0, 2652.0)
    assert ReversalDetector.validate_bar(t_bar) == (2650.0, 2655.0, 2648.0, 2652.0)

    # 3. Valid Tuple Bar with timestamp prefix (5 elements)
    ts_bar = (1700000000.0, 2650.0, 2655.0, 2648.0, 2652.0)
    assert ReversalDetector.validate_bar(ts_bar) == (2650.0, 2655.0, 2648.0, 2652.0)

    # 4. Invalid inverted bar (high < low)
    inv_bar = {"open": 2650.0, "high": 2640.0, "low": 2655.0, "close": 2650.0}
    assert ReversalDetector.validate_bar(inv_bar) is None

    # 5. Invalid NaN bar
    nan_bar = (2650.0, float("nan"), 2648.0, 2652.0)
    assert ReversalDetector.validate_bar(nan_bar) is None

    # 6. Bulk validate_bars filtering
    bars = [d_bar, inv_bar, t_bar, nan_bar]
    valid_list = ReversalDetector.validate_bars(bars)
    assert len(valid_list) == 2


def test_wave31_reversal_detector_rsi_and_cold_start():
    """Verify ReversalDetector Cutler RSI calculation and cold-start defaults."""
    rd = ReversalDetector(rsi_period=5, overbought=75.0, oversold=25.0)

    # Cold start (< 5 ticks) defaults to neutral 50.0
    for p in [2650.0, 2651.0, 2652.0]:
        rd.update_price(p)

    info = rd.info()
    assert info["overbought_threshold"] == 75.0
    assert info["total_reversals"] == 0

    # Feed rising ticks to establish RSI
    for p in [2653.0, 2654.0, 2655.0, 2656.0]:
        rd.update_price(p)

    # After rising prices, RSI exceeds neutral
    assert rd._compute_rsi() > 50.0


def test_wave30_session_lot_booster_overlap_and_confluence():
    """Verify SessionLotBooster enforces triple confluence (window, volatility, win rate)."""
    slb = SessionLotBooster(
        overlap_start_utc=12,
        overlap_end_utc=15,
        boost_multiplier=1.2,
        min_vol_index=1.3,
        min_win_rate=55.0,
    )

    t_outside = datetime(2026, 10, 17, 10, 0, 0, tzinfo=timezone.utc)
    t_inside = datetime(2026, 10, 17, 13, 30, 0, tzinfo=timezone.utc)

    # 1. Outside window -> unchanged lot
    assert slb.apply_boost(0.10, vol_index=1.5, win_rate_pct=60.0, now_dt=t_outside) == 0.10

    # 2. Inside window but vol_index insufficient (1.1 < 1.3) -> unchanged lot
    assert slb.apply_boost(0.10, vol_index=1.1, win_rate_pct=60.0, now_dt=t_inside) == 0.10

    # 3. Inside window but win_rate insufficient (50.0 < 55.0) -> unchanged lot
    assert slb.apply_boost(0.10, vol_index=1.5, win_rate_pct=50.0, now_dt=t_inside) == 0.10

    # 4. Triple confluence satisfied -> 1.2x boost (0.10 * 1.2 = 0.12)
    assert slb.apply_boost(0.10, vol_index=1.5, win_rate_pct=60.0, now_dt=t_inside) == 0.12

    # 5. Invalid inputs return safely
    assert slb.apply_boost(-0.05) == -0.05
    assert slb.apply_boost(None) is None


def test_wave29_adaptive_tp_atr_extension_and_shrinkage():
    """Verify AdaptiveTp scales TP based on rolling tick volatility."""
    atp = AdaptiveTp(
        window=5,
        extend_ratio=1.5,
        shrink_ratio=0.7,
        atr_high_threshold=0.15,
        atr_low_threshold=0.04,
    )

    # Cold start (< 5 ticks) -> neutral 1.0x
    for p in [2650.0, 2650.1, 2650.2]:
        atp.update_price(p)
    assert atp.get_tp_multiplier() == 1.0

    # High volatility series (tick deltas >= 0.20 > 0.15 high threshold)
    for p in [2650.5, 2650.1, 2650.6, 2650.2, 2650.7]:
        atp.update_price(p)
    assert atp.get_tp_multiplier() == 1.5

    # Reward to risk helper
    assert atp.calculate_reward_to_risk(tp_pips=45.0, sl_pips=30.0) == 1.50
    assert atp.calculate_reward_to_risk(tp_pips=0.0, sl_pips=30.0) == 0.0


def test_wave28_momentum_confirmation_buy_and_sell():
    """Verify MomentumConfirmation verifies multi-tick direction before entry."""
    mc = MomentumConfirmation(lookback=5, min_ticks_in_dir=3)

    # Insufficient ticks defaults to allowing entry
    mc.update_price(2650.0)
    confirmed, reason = mc.is_momentum_confirmed("BUY")
    assert confirmed is True
    assert "insufficient tick data" in reason

    # Feed strictly ascending series
    for p in [2650.2, 2650.4, 2650.6, 2650.8, 2651.0]:
        mc.update_price(p)

    # BUY is confirmed
    buy_ok, _ = mc.is_momentum_confirmed("BUY")
    assert buy_ok is True

    # SELL is rejected in ascending momentum
    sell_ok, sell_reason = mc.is_momentum_confirmed("SELL")
    assert sell_ok is False
    assert "MOMENTUM" in sell_reason

    # Feed strictly descending series
    for p in [2650.8, 2650.6, 2650.4, 2650.2, 2650.0]:
        mc.update_price(p)

    sell_ok2, _ = mc.is_momentum_confirmed("SELL")
    assert sell_ok2 is True

    buy_ok2, _ = mc.is_momentum_confirmed("BUY")
    assert buy_ok2 is False


def test_wave27_pearson_correlation_computation():
    """Verify compute_pearson_correlation handles perfect, inverse, and zero-variance series."""
    # Perfect positive correlation (r = 1.0)
    s1 = [1.0, 2.0, 3.0, 4.0, 5.0]
    s2 = [2.0, 4.0, 6.0, 8.0, 10.0]
    assert compute_pearson_correlation(s1, s2) == pytest.approx(1.0, abs=1e-5)

    # Perfect inverse correlation (r = -1.0)
    s3 = [5.0, 4.0, 3.0, 2.0, 1.0]
    assert compute_pearson_correlation(s1, s3) == pytest.approx(-1.0, abs=1e-5)

    # Zero-variance flat series returns 0.0 without ZeroDivisionError
    flat = [3.0, 3.0, 3.0, 3.0, 3.0]
    assert compute_pearson_correlation(s1, flat) == 0.0

    # Non-finite or mismatched series
    assert compute_pearson_correlation([1.0, 2.0], [1.0, 2.0, 3.0]) == 0.0
    assert compute_pearson_correlation([1.0, float("nan")], [2.0, 3.0]) == 0.0


def test_wave27_correlation_guard_signal_density_block():
    """Verify CorrelationGuard blocks trading when signal density exceeds limit."""
    cg = CorrelationGuard(window_sec=30.0, max_signals_in_window=3, cooldown_sec=60.0)

    # 3 signals in 30s -> allowed (up to max_signals=3)
    cg.record_signal(now_ts=100.0)
    cg.record_signal(now_ts=105.0)
    cg.record_signal(now_ts=110.0)
    allowed, _ = cg.is_trading_allowed(now_ts=110.0)
    assert allowed is True

    # 4th signal within 30s exceeds max_signals (len > 3) -> trips 60s cooldown (until 112.0 + 60.0 = 172.0)
    cg.record_signal(now_ts=112.0)
    allowed_blocked, reason = cg.is_trading_allowed(now_ts=112.0)
    assert not allowed_blocked
    assert "CORR_GUARD" in reason

    # In cooldown at t=140.0
    assert not cg.is_trading_allowed(now_ts=140.0)[0]

    # Cooldown expires at t=175.0
    assert cg.is_trading_allowed(now_ts=175.0)[0] is True


def test_wave26_time_filter_release_windows_and_safe_zones():
    """Verify TimeFilter blocks 30m before and after major releases and allows safe sessions."""
    tf = TimeFilter()

    # 12:15 UTC: Inside pre-release window for 12:30 release (starts at 12:00) -> BLOCKED
    t_1215 = datetime(2026, 10, 17, 12, 15, 0, tzinfo=timezone.utc)
    assert tf.is_entry_blocked(t_1215) is True

    # 12:30 UTC: Exact release time -> BLOCKED
    t_1230 = datetime(2026, 10, 17, 12, 30, 0, tzinfo=timezone.utc)
    assert tf.is_entry_blocked(t_1230) is True

    # 12:50 UTC: Inside post-release window (until 13:00) -> BLOCKED
    t_1250 = datetime(2026, 10, 17, 12, 50, 0, tzinfo=timezone.utc)
    assert tf.is_entry_blocked(t_1250) is True

    # 15:00 UTC: Mid-afternoon safe zone (well clear of 13:30 and 17:00 releases) -> ALLOWED
    t_1500 = datetime(2026, 10, 17, 15, 0, 0, tzinfo=timezone.utc)
    assert tf.is_entry_blocked(t_1500) is False


def test_wave26_time_filter_datetime_normalization_and_custom_schedule():
    """Verify TimeFilter normalizes datetime types and supports custom schedules."""
    custom_tf = TimeFilter(release_times=[(14, 0)], block_before=15, block_after=15)

    # 1. Datetime object at 14:05 UTC (inside 13:45-14:15 window) -> blocked
    dt_inside = datetime(2026, 10, 17, 14, 5, 0, tzinfo=timezone.utc)
    allowed, reason = custom_tf.is_trading_allowed(dt_inside)
    assert not allowed
    assert "TIME_FILTER" in reason

    # 2. ISO string input
    assert custom_tf.is_entry_blocked("2026-10-17T14:10:00+00:00") is True

    # 3. Unix epoch timestamp input
    ts_outside = datetime(2026, 10, 17, 14, 30, 0, tzinfo=timezone.utc).timestamp()
    assert custom_tf.is_entry_blocked(ts_outside) is False
