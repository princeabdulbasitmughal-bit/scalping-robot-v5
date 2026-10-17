"""
tests/test_batch38.py - Comprehensive Unit Tests for Batch 38 Components:
1. wave21_news_guard (NewsGuard): status loading, manual override, set_override, reset
2. wave22_equity_curve_halt (EquityCurveHalt): drawdown halt, win streak recovery, cooldown
3. wave23_spread_optimizer (SpreadOptimizer): session spread limits, vol index scaling, bounds
4. wave24_daily_profit_lock (DailyProfitLock): protect mode activation, lot reduction, score floor
5. wave25_drawdown_accelerator (DrawdownAccelerator): consecutive loss scaling, win reset, mode
6. wave26_time_filter (TimeFilter): economic release windows, time normalization, block gates
7. wave27_correlation_guard (CorrelationGuard & compute_pearson_correlation): zero-variance, cluster
8. wave28_momentum_confirmation (MomentumConfirmation): tick direction validation, RLock, reset
9. wave29_adaptive_tp (AdaptiveTp): ATR proxy calculation, high/low multipliers, cold-start
10. wave30_session_lot_booster (SessionLotBooster): overlap window boost, vol/win_rate conditions
"""

import json
import math
import os
import tempfile
import time
from datetime import datetime, timezone
import pytest

from wave21_news_guard import NewsGuard
from wave22_equity_curve_halt import EquityCurveHalt
from wave23_spread_optimizer import SpreadOptimizer
from wave24_daily_profit_lock import DailyProfitLock
from wave25_drawdown_accelerator import DrawdownAccelerator
from wave26_time_filter import TimeFilter
from wave27_correlation_guard import CorrelationGuard, compute_pearson_correlation
from wave28_momentum_confirmation import MomentumConfirmation
from wave29_adaptive_tp import AdaptiveTp
from wave30_session_lot_booster import SessionLotBooster


def test_wave21_news_guard_status_and_override():
    """Verify NewsGuard loads status, handles manual overrides, and set_override API."""
    with tempfile.TemporaryDirectory() as tmpdir:
        status_path = os.path.join(tmpdir, "news_status.json")
        override_path = os.path.join(tmpdir, "news_override.json")

        guard = NewsGuard(status_file=status_path, override_file=override_path)
        guard.reset()

        # 1. No files exist -> fail-open (allow trading)
        allowed, reason = guard.is_trading_allowed()
        assert allowed is True
        assert "not found" in reason

        # 2. Status file says avoid_trading: true
        with open(status_path, "w", encoding="utf-8") as f:
            json.dump({
                "avoid_trading": True,
                "last_headlines": ["US CPI spikes higher than expected"],
                "last_checked": "2026-10-17 12:30:00"
            }, f)
        guard.reset()
        allowed, reason = guard.is_trading_allowed()
        assert allowed is False
        assert "US CPI spikes" in reason

        # 3. Manual override active: override: true forces allow
        with open(override_path, "w", encoding="utf-8") as f:
            json.dump({"override": True}, f)
        guard.reset()
        allowed, reason = guard.is_trading_allowed()
        assert allowed is True
        assert "manual override" in reason

        # 4. In-memory set_override
        guard.set_override(avoid=True, reason="emergency brake")
        allowed, reason = guard.is_trading_allowed()
        assert allowed is False
        assert "emergency brake" in reason

        info = guard.info()
        assert info["avoid_trading"] is True


def test_wave22_equity_curve_halt_drawdown_and_recovery():
    """Verify EquityCurveHalt halts on steep negative slope and recovers via win streak or cooldown."""
    halt = EquityCurveHalt(
        window=5,
        loss_threshold_usd=-100.0,
        slope_threshold=-20.0,
        recovery_win_streak=2,
        cooldown_sec=300.0,
    )
    halt.reset()

    # 1. Warm-up phase (fewer trades than window)
    for _ in range(4):
        halt.record_trade(-25.0, won=False)
    allowed, reason = halt.is_trading_allowed(current_balance=10000.0)
    assert allowed is True
    assert "warming up" in reason

    # 2. Window filled: sum = -125 < -100, slope = -25 < -20 -> HALTED
    halt.record_trade(-25.0, won=False)
    allowed, reason = halt.is_trading_allowed(current_balance=9875.0, now_mono=1000.0)
    assert allowed is False
    assert "EQUITY CURVE HALT" in reason

    # 3. Recovery via 2 consecutive wins
    halt.record_trade(30.0, won=True)
    allowed, _ = halt.is_trading_allowed(current_balance=9905.0, now_mono=1010.0)
    assert allowed is False  # Needs 2 consecutive wins

    halt.record_trade(30.0, won=True)
    allowed, reason = halt.is_trading_allowed(current_balance=9935.0, now_mono=1020.0)
    assert allowed is True
    assert "recovered" in reason

    # 4. Invalid input handling
    assert halt.is_trading_allowed(float("nan"))[0] is False


def test_wave23_spread_optimizer_limits_and_volatility():
    """Verify SpreadOptimizer enforces session limits and scales with volatility."""
    so = SpreadOptimizer()
    so.reset()

    # Tokyo session base limit is 1.8 pips
    # 1.5 pips -> OK
    ok, reason = so.is_spread_ok(spread_pips=1.5, session_name="TOKYO", vol_index=1.0)
    assert ok is True
    assert "spread ok" in reason

    # 2.2 pips in Tokyo -> REJECT
    ok, reason = so.is_spread_ok(spread_pips=2.2, session_name="TOKYO", vol_index=1.0)
    assert ok is False
    assert "SPREAD REJECT" in reason

    # High vol index (1.6 >= 1.5) widens limit by 1.2x (1.8 * 1.2 = 2.16)
    # 2.1 pips in Tokyo with high vol -> OK
    ok, _ = so.is_spread_ok(spread_pips=2.1, session_name="TOKYO", vol_index=1.6)
    assert ok is True

    # Overlap session (LDN_NY) base limit is 3.5 pips
    ok, _ = so.is_spread_ok(spread_pips=3.2, session_name="LDN_NY")
    assert ok is True

    # Invalid spread values
    assert so.is_spread_ok(-1.0)[0] is False
    assert so.is_spread_ok(float("nan"))[0] is False

    info = so.info()
    assert info["accepted"] >= 3
    assert info["rejected"] >= 1


def test_wave24_daily_profit_lock_engagement():
    """Verify DailyProfitLock engages protect mode upon hitting target and reduces lot size."""
    lock = DailyProfitLock(profit_target_usd=150.0, protect_lot=0.01, protect_min_score=70)
    lock.reset()

    assert lock.is_active is False
    assert lock.apply_lot(0.05) == 0.05
    assert lock.get_min_score(55) == 55

    # Daily PnL hits $160 >= $150 target
    lock.update(160.0)
    assert lock.is_active is True

    # In protect mode: lot is capped at 0.01 and min score elevated to 70
    assert lock.apply_lot(0.05) == 0.01
    assert lock.apply_lot(0.005) == 0.005  # smaller lot preserved
    assert lock.get_min_score(55) == 70
    assert lock.get_min_score(75) == 75

    # Reset clears protect mode
    lock.reset()
    assert lock.is_active is False
    assert lock.apply_lot(0.05) == 0.05


def test_wave25_drawdown_accelerator_progressive_scaling():
    """Verify DrawdownAccelerator reduces lot on consecutive losses and resets on 2 wins."""
    da = DrawdownAccelerator(recovery_wins=2)
    da.reset()

    assert da.get_multiplier() == 1.0
    assert da.apply_lot(0.04) == 0.04

    # 1-2 losses: full size
    da.record_trade(won=False)
    da.record_trade(won=False)
    assert da.get_multiplier() == 1.0

    # 3 losses: 0.50x
    da.record_trade(won=False)
    assert da.get_multiplier() == 0.50
    assert da.apply_lot(0.04) == 0.02

    # 5 losses: 0.25x
    da.record_trade(won=False)
    da.record_trade(won=False)
    assert da.get_multiplier() == 0.25
    assert da.apply_lot(0.04) == 0.01

    # 7 losses: 0.10x
    da.record_trade(won=False)
    da.record_trade(won=False)
    assert da.get_multiplier() == 0.10

    # Recovery: 1 win does not fully reset, 2 consecutive wins resets to 1.0x
    da.record_trade(won=True)
    assert da.apply_lot(0.04) == 0.01  # still in reduced mode
    da.record_trade(won=True)
    assert da.get_multiplier() == 1.0
    assert da.apply_lot(0.04) == 0.04

    info = da.info()
    assert info["mode"] == "FULL_SIZE"
    assert info["lot_multiplier"] == 1.0
    assert "current_multiplier" in info


def test_wave26_time_filter_release_windows():
    """Verify TimeFilter blocks trades within economic release blackout windows."""
    tf = TimeFilter(
        release_times=[(12, 30), (18, 0)],
        block_before=30,
        block_after=30,
    )

    # 1. Clear trading time (10:00 UTC) -> allowed
    dt_clear = datetime(2026, 10, 17, 10, 0, tzinfo=timezone.utc)
    allowed, reason = tf.is_trading_allowed(dt_clear)
    assert allowed is True
    assert reason == ""

    # 2. Inside window: 12:15 UTC (15 mins before 12:30 release) -> blocked
    dt_blocked_pre = datetime(2026, 10, 17, 12, 15, tzinfo=timezone.utc)
    allowed, reason = tf.is_trading_allowed(dt_blocked_pre)
    assert allowed is False
    assert "TIME_FILTER" in reason

    # 3. Inside window: 12:45 UTC (15 mins after 12:30 release) -> blocked
    dt_blocked_post = datetime(2026, 10, 17, 12, 45, tzinfo=timezone.utc)
    allowed, _ = tf.is_trading_allowed(dt_blocked_post)
    assert allowed is False

    # 4. Outside window: 13:01 UTC -> allowed
    dt_post_window = datetime(2026, 10, 17, 13, 1, tzinfo=timezone.utc)
    allowed, _ = tf.is_trading_allowed(dt_post_window)
    assert allowed is True


def test_wave27_correlation_guard_and_pearson():
    """Verify Pearson correlation calculation and CorrelationGuard signal cluster density."""
    # 1. Perfectly correlated
    r1 = compute_pearson_correlation([1.0, 2.0, 3.0, 4.0], [2.0, 4.0, 6.0, 8.0])
    assert abs(r1 - 1.0) < 1e-6

    # 2. Inversely correlated
    r2 = compute_pearson_correlation([1.0, 2.0, 3.0, 4.0], [8.0, 6.0, 4.0, 2.0])
    assert abs(r2 - (-1.0)) < 1e-6

    # 3. Zero variance handling (flat series -> 0.0, no ZeroDivisionError)
    r_flat = compute_pearson_correlation([5.0, 5.0, 5.0, 5.0], [1.0, 2.0, 3.0, 4.0])
    assert r_flat == 0.0

    # 4. CorrelationGuard rapid cluster density
    guard = CorrelationGuard(window_sec=10.0, max_signals_in_window=3, cooldown_sec=30.0)
    guard.reset()

    # Record signals: max allowed in window is 3, 4th triggers cooldown
    guard.record_signal(now_ts=100.0)
    guard.record_signal(now_ts=101.0)
    guard.record_signal(now_ts=102.0)
    assert guard.is_trading_allowed(now_ts=102.5)[0] is True

    # 4th signal (> 3) at t=103 -> triggers cooldown
    guard.record_signal(now_ts=103.0)
    ok, reason = guard.is_trading_allowed(now_ts=103.5)
    assert ok is False
    assert "cooldown active" in reason


def test_wave28_momentum_confirmation_ticks():
    """Verify MomentumConfirmation validates tick price direction before trade entry."""
    mc = MomentumConfirmation(lookback=5, min_ticks_in_dir=3)
    mc.reset()

    # Insufficient data -> allowed
    assert mc.is_momentum_confirmed("BUY")[0] is True

    # Upward momentum ticks: 2400.0 -> 2400.5 -> 2401.0 -> 2401.5 -> 2402.0
    for p in [2400.0, 2400.5, 2401.0, 2401.5, 2402.0]:
        mc.update_price(p)

    # BUY is confirmed
    ok, _ = mc.is_momentum_confirmed("BUY")
    assert ok is True

    # SELL is rejected
    ok, reason = mc.is_momentum_confirmed("SELL")
    assert ok is False
    assert "rejected" in reason

    # Downward momentum ticks
    mc.reset()
    for p in [2402.0, 2401.5, 2401.0, 2400.5, 2400.0]:
        mc.update_price(p)

    assert mc.is_momentum_confirmed("SELL")[0] is True
    assert mc.is_momentum_confirmed("BUY")[0] is False


def test_wave29_adaptive_tp_scaling():
    """Verify AdaptiveTp computes ATR proxy and scales TP targets appropriately."""
    atp = AdaptiveTp(
        window=10,
        extend_ratio=1.5,
        shrink_ratio=0.7,
        atr_high_threshold=0.50,
        atr_low_threshold=0.10,
        min_tp_pips=5.0
    )
    atp.reset()

    # Cold start (fewer than window ticks) -> 1.0x neutral multiplier
    for p in [2400.0, 2400.1, 2400.2]:
        atp.update_price(p)
    assert atp.get_tp_multiplier() == 1.0

    # High volatility ticks (ranges ~ 1.0 per tick > 0.50 threshold)
    atp.reset()
    for i in range(15):
        atp.update_price(2400.0 + (i % 2) * 1.5)
    assert atp.get_tp_multiplier() == 1.5
    assert atp.adjust_tp(10.0) == 15.0

    # Low volatility ticks (ranges ~ 0.02 per tick < 0.10 threshold)
    atp.reset()
    for i in range(15):
        atp.update_price(2400.0 + i * 0.02)
    assert atp.get_tp_multiplier() == 0.7
    assert atp.adjust_tp(10.0) == 7.0

    # Reward to risk safety
    assert atp.calculate_reward_to_risk(15.0, 10.0) == 1.5
    assert atp.calculate_reward_to_risk(15.0, 0.0) == 0.0


def test_wave30_session_lot_booster_overlap():
    """Verify SessionLotBooster boosts lot size during London/NY overlap under favorable conditions."""
    slb = SessionLotBooster(
        overlap_start_utc=12,
        overlap_end_utc=15,
        boost_multiplier=1.2,
        min_vol_index=1.3,
        min_win_rate=55.0
    )
    slb.reset()

    # 1. In overlap (13:30 UTC), high vol (1.4), high win rate (60%) -> 1.2x boost
    dt_overlap = datetime(2026, 10, 20, 13, 30, tzinfo=timezone.utc)
    boosted = slb.apply_boost(lot=0.05, vol_index=1.4, win_rate_pct=60.0, now_dt=dt_overlap)
    assert boosted == 0.06  # 0.05 * 1.2

    # 2. In overlap but low vol (1.0 < 1.3) -> no boost
    unchanged = slb.apply_boost(lot=0.05, vol_index=1.0, win_rate_pct=60.0, now_dt=dt_overlap)
    assert unchanged == 0.05

    # 3. Outside overlap (09:00 UTC) -> no boost
    dt_outside = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
    unchanged2 = slb.apply_boost(lot=0.05, vol_index=1.5, win_rate_pct=65.0, now_dt=dt_outside)
    assert unchanged2 == 0.05

    info = slb.info(now_dt=dt_overlap)
    assert info["in_overlap_window"] is True
    assert info["boost_multiplier"] == 1.2
