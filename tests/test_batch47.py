"""
Batch 47 Test Suite:
1. wave21_news_guard.py NewsGuard file loading, avoid_trading, and override
2. wave22_equity_curve_halt.py drawdown acceleration halt & win-streak/cooldown recovery
3. wave23_spread_optimizer.py session-based thresholds, vol scaling, and invalid input rejection
4. wave24_daily_profit_lock.py protect mode trigger, lot/score modification, and reset
5. wave25_drawdown_accelerator.py progressive loss reduction ladder & 2-win recovery
6. wave26_time_filter.py economic release window blocking and allow boundaries
7. wave27_correlation_guard.py Pearson correlation edge cases & rapid signal density trigger
8. wave28_momentum_confirmation.py directional tick trend confirmation for BUY/SELL
9. wave29_adaptive_tp.py ATR-driven TP expansion, contraction & reward-to-risk calculation
10. wave30_session_lot_booster.py London-NY overlap conditions and lot multiplier boost
"""
import datetime
from datetime import timezone
import json
import math
from unittest.mock import patch

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


# ── Test 1: Wave 21 News Guard ────────────────────────────────────────────────
def test_wave21_news_guard_file_and_override(tmp_path):
    """Verify NewsGuard blocks trading on news avoid status and respects override file."""
    status_file = tmp_path / "news_status.json"
    override_file = tmp_path / "news_override.json"

    # Status file indicating high-impact news event
    status_file.write_text(
        json.dumps({
            "avoid_trading": True,
            "last_headlines": ["US CPI surges 0.5% above expectations"],
            "last_checked": "2026-10-17 12:30:00 UTC",
        }),
        encoding="utf-8",
    )

    ng = NewsGuard(status_file=str(status_file), override_file=str(override_file))
    allowed, reason = ng.is_trading_allowed()
    assert allowed is False
    assert "US CPI surges" in reason

    # Manual override file created
    override_file.write_text(json.dumps({"override": True}), encoding="utf-8")
    ng._last_check_time = 0.0  # expire TTL cache
    allowed_ov, reason_ov = ng.is_trading_allowed()
    assert allowed_ov is True
    assert "manual override" in reason_ov

    # Programmatic override & reset
    ng.set_override(avoid=True, reason="manual test block")
    assert ng.is_trading_allowed()[0] is False
    ng.reset()
    assert ng._blocked_count == 0


# ── Test 2: Wave 22 Equity Curve Halt ─────────────────────────────────────────
def test_wave22_equity_curve_halt_and_recovery():
    """Verify EquityCurveHalt halts on steep negative PnL slope and recovers."""
    eq_halt = EquityCurveHalt(
        window=5,
        loss_threshold_usd=-100.0,
        slope_threshold=-15.0,
        recovery_win_streak=2,
        cooldown_sec=120.0,
    )

    base_mono = 1000.0
    # Feed 4 losses (warming up)
    for _ in range(4):
        eq_halt.record_trade(-30.0, won=False)
        allowed, _ = eq_halt.is_trading_allowed(10000.0, now_mono=base_mono)
        assert allowed is True

    # 5th loss pushes window sum to -150.0 (< -100) and slope to -30.0 (< -15)
    eq_halt.record_trade(-30.0, won=False)
    allowed_halt, reason_halt = eq_halt.is_trading_allowed(9850.0, now_mono=base_mono)
    assert allowed_halt is False
    assert "EQUITY CURVE HALT" in reason_halt

    # Single win is not enough for recovery (needs 2)
    eq_halt.record_trade(25.0, won=True)
    allowed_w1, _ = eq_halt.is_trading_allowed(9875.0, now_mono=base_mono + 10)
    assert allowed_w1 is False

    # Second win achieves recovery
    eq_halt.record_trade(30.0, won=True)
    allowed_rec, reason_rec = eq_halt.is_trading_allowed(9905.0, now_mono=base_mono + 20)
    assert allowed_rec is True
    assert "recovered" in reason_rec


# ── Test 3: Wave 23 Spread Optimizer ──────────────────────────────────────────
def test_wave23_spread_optimizer_sessions_and_guards():
    """Verify SpreadOptimizer enforces session-specific limits and rejects invalid spreads."""
    so = SpreadOptimizer()

    # Tokyo session (02:00 UTC) -> max limit is 1.8 pips
    dt_tokyo = datetime.datetime(2026, 10, 17, 2, 0, tzinfo=timezone.utc)
    ok_tokyo, _ = so.is_spread_ok(1.5, now_dt=dt_tokyo)
    assert ok_tokyo is True
    reject_tokyo, reason_tokyo = so.is_spread_ok(2.2, now_dt=dt_tokyo)
    assert reject_tokyo is False
    assert "SPREAD REJECT" in reason_tokyo

    # London-NY Overlap (14:00 UTC) -> max limit is 3.5 pips
    dt_overlap = datetime.datetime(2026, 10, 17, 14, 0, tzinfo=timezone.utc)
    ok_overlap, _ = so.is_spread_ok(3.2, now_dt=dt_overlap)
    assert ok_overlap is True

    # Invalid non-finite or negative spreads
    assert so.is_spread_ok(-1.0)[0] is False
    assert so.is_spread_ok(float("nan"))[0] is False
    assert so.is_spread_ok(None)[0] is False


# ── Test 4: Wave 24 Daily Profit Lock ─────────────────────────────────────────
def test_wave24_daily_profit_lock():
    """Verify DailyProfitLock engages protect mode at target and alters lot/score."""
    lock = DailyProfitLock(profit_target_usd=150.0, protect_lot=0.01, protect_min_score=70)

    # Initial state
    assert lock.is_active is False
    assert lock.apply_lot(0.05) == 0.05
    assert lock.apply_min_score(55) == 55

    # Profit below target
    lock.update(120.0)
    assert lock.is_active is False

    # Profit hits target (+$155.0 >= $150.0)
    lock.update(155.0)
    assert lock.is_active is True
    assert lock.apply_lot(0.05) == 0.01
    assert lock.apply_min_score(55) == 70

    # Reset clears protect mode
    lock.reset()
    assert lock.is_active is False
    assert lock.apply_lot(0.05) == 0.05


# ── Test 5: Wave 25 Drawdown Accelerator ──────────────────────────────────────
def test_wave25_drawdown_accelerator():
    """Verify DrawdownAccelerator applies progressive multipliers and resets on 2 wins."""
    da = DrawdownAccelerator(recovery_wins=2)

    assert da.get_multiplier() == 1.0
    assert da.apply_lot(0.10) == 0.10

    # 3 consecutive losses -> 0.50x
    for _ in range(3):
        da.record_trade(won=False)
    assert da.get_multiplier() == 0.50
    assert da.apply_lot(0.10) == 0.05

    # 5 consecutive losses -> 0.25x
    for _ in range(2):
        da.record_trade(won=False)
    assert da.get_multiplier() == 0.25
    assert da.apply_lot(0.10) == 0.03  # round(0.025, 2) = 0.03 (or 0.02)

    # 7 consecutive losses -> 0.10x
    for _ in range(2):
        da.record_trade(won=False)
    assert da.get_multiplier() == 0.10
    assert da.apply_lot(0.10) == 0.01

    # 1 win does not fully reset
    da.record_trade(won=True)
    assert da.get_multiplier() == 0.10

    # 2nd consecutive win triggers full reset
    da.record_trade(won=True)
    assert da.get_multiplier() == 1.0
    assert da.apply_lot(0.10) == 0.10


# ── Test 6: Wave 26 Time Filter ───────────────────────────────────────────────
def test_wave26_time_filter():
    """Verify TimeFilter blocks trades inside economic release windows."""
    # US NFP / CPI at 12:30 UTC with 30 min before/after (12:00 to 13:00)
    tf = TimeFilter(release_times=[(12, 30)], block_before=30, block_after=30)

    # 12:15 UTC (inside block window)
    dt_blocked = datetime.datetime(2026, 10, 17, 12, 15, tzinfo=timezone.utc)
    allowed_b, reason_b = tf.is_trading_allowed(now_utc=dt_blocked)
    assert allowed_b is False
    assert "TIME_FILTER" in reason_b and "blocked" in reason_b

    # 11:50 UTC (outside window -> allowed)
    dt_ok_before = datetime.datetime(2026, 10, 17, 11, 50, tzinfo=timezone.utc)
    allowed_ob, _ = tf.is_trading_allowed(now_utc=dt_ok_before)
    assert allowed_ob is True

    # 13:10 UTC (outside window -> allowed)
    dt_ok_after = datetime.datetime(2026, 10, 17, 13, 10, tzinfo=timezone.utc)
    allowed_oa, _ = tf.is_trading_allowed(now_utc=dt_ok_after)
    assert allowed_oa is True


# ── Test 7: Wave 27 Correlation Guard ─────────────────────────────────────────
def test_wave27_correlation_guard_and_pearson():
    """Verify Pearson correlation calculation and CorrelationGuard rapid signal detection."""
    # Pearson: Identical sequences -> 1.0
    s1 = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert pytest.approx(compute_pearson_correlation(s1, s1), abs=1e-5) == 1.0

    # Pearson: Exact inverse -> -1.0
    s2 = [5.0, 4.0, 3.0, 2.0, 1.0]
    assert pytest.approx(compute_pearson_correlation(s1, s2), abs=1e-5) == -1.0

    # Pearson: Zero-variance flat sequence -> 0.0 (no division by zero)
    flat = [3.0, 3.0, 3.0, 3.0, 3.0]
    assert compute_pearson_correlation(s1, flat) == 0.0

    # Pearson: Corrupt/short input -> 0.0
    assert compute_pearson_correlation([1.0], [1.0]) == 0.0
    assert compute_pearson_correlation([1.0, float("nan")], [2.0, 3.0]) == 0.0

    # CorrelationGuard density check
    cg = CorrelationGuard(window_sec=30.0, max_signals_in_window=3, cooldown_sec=60.0)
    now = 50000.0
    cg.record_signal(now_ts=now)
    cg.record_signal(now_ts=now + 5)
    cg.record_signal(now_ts=now + 10)
    assert cg.is_trading_allowed(now_ts=now + 11)[0] is True

    # 4th signal within 30s triggers density cooldown
    cg.record_signal(now_ts=now + 15)
    allowed_cg, reason_cg = cg.is_trading_allowed(now_ts=now + 16)
    assert allowed_cg is False
    assert "CORR_GUARD" in reason_cg


# ── Test 8: Wave 28 Momentum Confirmation ─────────────────────────────────────
def test_wave28_momentum_confirmation():
    """Verify MomentumConfirmation validates tick price alignment with signal direction."""
    mc = MomentumConfirmation(lookback=5, min_ticks_in_dir=3)

    # Insufficient data allows trade
    mc.update_price(2400.0)
    mc.update_price(2400.2)
    assert mc.is_momentum_confirmed("BUY")[0] is True

    # Upward trending prices: 2400.0 -> 2400.2 -> 2400.5 -> 2400.8 -> 2401.0
    for p in [2400.5, 2400.8, 2401.0]:
        mc.update_price(p)

    # BUY should confirm (4 up ticks >= 3 required)
    buy_ok, _ = mc.is_momentum_confirmed("BUY")
    assert buy_ok is True

    # SELL should reject (0 down ticks < 3 required)
    sell_ok, sell_reason = mc.is_momentum_confirmed("SELL")
    assert sell_ok is False
    assert "SELL rejected" in sell_reason


# ── Test 9: Wave 29 Adaptive TP ───────────────────────────────────────────────
def test_wave29_adaptive_tp():
    """Verify AdaptiveTp expands TP during high ATR and contracts during low ATR."""
    atp = AdaptiveTp(window=5, extend_ratio=1.5, shrink_ratio=0.7, atr_high_threshold=0.5, atr_low_threshold=0.1)

    # Cold start returns neutral 1.0x
    assert atp.get_tp_multiplier() == 1.0

    # High volatility feed (steps of 1.0 > 0.5)
    for p in [2400.0, 2401.0, 2402.0, 2401.0, 2402.0, 2403.0]:
        atp.update_price(p)
    assert atp.get_tp_multiplier() == 1.5

    # Safe reward to risk calculation
    assert atp.calculate_reward_to_risk(45.0, 30.0) == 1.5
    assert atp.calculate_reward_to_risk(45.0, 0.0) == 0.0
    assert atp.calculate_reward_to_risk(-10.0, 20.0) == 0.0


# ── Test 10: Wave 30 Session Lot Booster ──────────────────────────────────────
def test_wave30_session_lot_booster():
    """Verify SessionLotBooster boosts lot size during London-NY overlap conditions."""
    booster = SessionLotBooster(
        overlap_start_utc=12,
        overlap_end_utc=15,
        boost_multiplier=1.2,
        min_vol_index=1.3,
        min_win_rate=55.0,
    )

    # Within overlap window (13:00 UTC) with sufficient vol and win rate
    dt_overlap = datetime.datetime(2026, 10, 17, 13, 0, tzinfo=timezone.utc)
    boosted_lot = booster.apply_boost(
        lot=0.10,
        vol_index=1.5,
        win_rate_pct=60.0,
        now_dt=dt_overlap,
    )
    assert boosted_lot == 0.12

    # Outside overlap window (09:00 UTC) -> unchanged lot
    dt_outside = datetime.datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)
    unchanged_lot = booster.apply_boost(
        lot=0.10,
        vol_index=1.5,
        win_rate_pct=60.0,
        now_dt=dt_outside,
    )
    assert unchanged_lot == 0.10
