"""
tests/test_batch66.py
=====================
Hermetic unit tests for Batch 66 Milestone:
1. DrawdownAccelerator: Progressive lot reduction (0.50x, 0.25x, 0.10x) & 2-win recovery
2. DailyProfitLock: +$150 profit target trip-wire, protect mode 0.01 lot & daily reset
3. SpreadOptimizer: Session-specific spread limits (Tokyo 1.8p, Overlap 3.5p) & rejection
4. EquityCurveHalt: Running equity slope halt & 2-win recovery resumption
5. NewsGuard: High-impact news status parsing, override handling & telemetry
6. SpikeFilter: Tick-to-tick spike ratio threshold, cooldown lockout & cluster check
7. VolatilityTPSLAdjuster: Volatility-adaptive TP widening, low-vol SL/TP tightening & bounds
8. AutoTuner: Trade history statistical analysis (PF, MAE, MFE, RR) & suggestion generation
9. ProfitOptimizer: Win/loss streak lot modifiers (1.1x / 0.5x) & floating PnL reversal auto-close
10. SessionOptimizer: Weekend/Friday/Monday window filtering & London-NY overlap premium status
"""

import math
import time
from datetime import datetime, timezone
import pytest

from wave25_drawdown_accelerator import DrawdownAccelerator
from wave24_daily_profit_lock import DailyProfitLock
from wave23_spread_optimizer import SpreadOptimizer
from wave22_equity_curve_halt import EquityCurveHalt
from wave21_news_guard import NewsGuard
from wave20_spike_filter import SpikeFilter
from wave19_volatility_tpsl import VolatilityTPSLAdjuster
from wave14_auto_tuner import AutoTuner
from wave11_profit_optimizer import ProfitOptimizer
from wave10_session_optimizer import SessionOptimizer


def test_wave25_drawdown_accelerator_streak_reduction():
    """Verify DrawdownAccelerator reduces lot size on losing streaks and recovers on 2 wins."""
    dda = DrawdownAccelerator()
    assert dda.get_multiplier() == 1.0

    # 1-2 losses: no reduction yet
    dda.record_trade(False)
    dda.record_trade(False)
    assert dda.get_multiplier() == 1.0
    assert dda.apply_lot(0.10) == 0.10

    # 3 consecutive losses: multiplier drops to 0.50
    dda.record_trade(False)
    assert dda.get_multiplier() == 0.50
    assert dda.apply_lot(0.10) == 0.05

    # 5 consecutive losses: multiplier drops to 0.25
    dda.record_trade(False)
    dda.record_trade(False)
    assert dda.get_multiplier() == 0.25
    assert dda.apply_lot(0.10) == 0.03  # 0.025 rounded to 0.03 (or min lot bounds)

    # 7 consecutive losses: multiplier drops to 0.10
    dda.record_trade(False)
    dda.record_trade(False)
    assert dda.get_multiplier() == 0.10
    assert dda.apply_lot(0.10) == 0.01

    # 1 win: does not fully recover yet (needs 2 consecutive wins)
    dda.record_trade(True)
    assert dda.get_multiplier() == 0.10

    # 2nd consecutive win: fully recovers to 1.0
    dda.record_trade(True)
    assert dda.get_multiplier() == 1.0
    assert dda.apply_lot(0.10) == 0.10


def test_wave24_daily_profit_lock_mode_and_sizing():
    """Verify DailyProfitLock engages protect mode at target and resets cleanly."""
    dpl = DailyProfitLock(profit_target_usd=150.0, protect_lot=0.01, protect_min_score=70)

    # 1. Below target ($100 PnL): protect mode not active
    dpl.update(100.0)
    assert not dpl.is_active
    assert dpl.apply_lot(0.05) == 0.05
    assert dpl.apply_min_score(55) == 55

    # 2. At or above target ($160 PnL >= $150): protect mode engages
    dpl.update(160.0)
    assert dpl.is_active
    assert dpl.apply_lot(0.05) == 0.01
    assert dpl.apply_min_score(55) == 70

    # 3. Daily reset clears protect mode
    dpl.reset()
    assert not dpl.is_active
    assert dpl.apply_lot(0.05) == 0.05


def test_wave23_spread_optimizer_session_limits():
    """Verify SpreadOptimizer enforces session-specific spread limits."""
    so = SpreadOptimizer()

    # Tokyo session (02:00 UTC, limit 1.8 pips)
    tokyo_dt = datetime(2026, 10, 17, 2, 0, 0, tzinfo=timezone.utc)
    ok_tokyo, _ = so.is_spread_ok(1.5, now_dt=tokyo_dt)
    assert ok_tokyo is True

    bad_tokyo, reason_t = so.is_spread_ok(2.2, now_dt=tokyo_dt)
    assert bad_tokyo is False
    assert "REJECT" in reason_t

    # London-NY Overlap (14:00 UTC, limit 3.5 pips)
    overlap_dt = datetime(2026, 10, 17, 14, 0, 0, tzinfo=timezone.utc)
    ok_ov, _ = so.is_spread_ok(3.2, now_dt=overlap_dt)
    assert ok_ov is True

    bad_ov, _ = so.is_spread_ok(4.0, now_dt=overlap_dt)
    assert bad_ov is False

    # Invalid spread
    inv_ok, _ = so.is_spread_ok(-0.5)
    assert inv_ok is False


def test_wave22_equity_curve_halt_drawdown_trigger_and_recovery():
    """Verify EquityCurveHalt stops trading on severe negative equity slope and resumes on 2 wins."""
    ech = EquityCurveHalt(
        window=5,
        loss_threshold_usd=-150.0,
        slope_threshold=-10.0,
        recovery_win_streak=2,
        cooldown_sec=300.0,
    )

    # 5 losing trades of -$40 each -> total -$200 < -$150, slope -$40 < -10
    for _ in range(5):
        ech.record_trade(-40.0, won=False)

    allowed, reason = ech.is_trading_allowed(current_balance=9800.0, now_mono=100.0)
    assert not allowed
    assert "EQUITY CURVE HALT" in reason

    # In cooldown at now_mono=200.0
    allowed_cd, _ = ech.is_trading_allowed(current_balance=9800.0, now_mono=200.0)
    assert not allowed_cd

    # 2 consecutive wins trigger recovery
    ech.record_trade(15.0, won=True)
    ech.record_trade(20.0, won=True)
    allowed_rec, _ = ech.is_trading_allowed(current_balance=9835.0, now_mono=210.0)
    assert allowed_rec is True


def test_wave21_news_guard_file_loading_and_override(tmp_path):
    """Verify NewsGuard handles status overrides and allows safe fallback."""
    stat_file = str(tmp_path / "mock_news_status.json")
    ov_file = str(tmp_path / "mock_news_override.json")
    ng = NewsGuard(status_file=stat_file, override_file=ov_file)

    # Default fallback allows trading when files do not exist
    allowed, _ = ng.is_trading_allowed()
    assert allowed is True

    # Explicit override: avoid trading
    ng.set_override(avoid=True, reason="US CPI Release")
    allowed_cpi, reason_cpi = ng.is_trading_allowed()
    assert not allowed_cpi
    assert "US CPI Release" in reason_cpi

    # Explicit override: trading cleared
    ng.set_override(avoid=False, reason="News window passed")
    allowed_clear, _ = ng.is_trading_allowed()
    assert allowed_clear is True


def test_wave20_spike_filter_ratio_check_and_cooldown():
    """Verify SpikeFilter blocks single-tick price spikes and holds cooldown."""
    sf = SpikeFilter(spike_ratio_threshold=4.0, cooldown_sec=90.0)

    # Establish baseline moves of 0.10 pips across 10 ticks
    for _ in range(10):
        sf.check(current_price=2650.1, prev_price=2650.0, now_ts=100.0)

    # Normal tick move (0.15 pips -> ratio ~1.5x < 4.0x) -> OK
    ok_normal, _ = sf.check(current_price=2650.25, prev_price=2650.1, now_ts=101.0)
    assert ok_normal is True

    # Price spike (2.75 pips move -> ratio ~7x >= 4.0x) -> SPIKE_DETECTED
    ok_spike, reason_s = sf.check(current_price=2653.0, prev_price=2650.25, now_ts=102.0)
    assert not ok_spike
    assert "SPIKE_DETECTED" in reason_s

    # In cooldown at t=140.0 -> SPIKE_COOLDOWN
    ok_cd, reason_cd = sf.check(current_price=2653.1, prev_price=2653.0, now_ts=140.0)
    assert not ok_cd
    assert "SPIKE_COOLDOWN" in reason_cd

    # Cooldown expires at t=195.0 (> 90s from 102.0)
    ok_expired, _ = sf.check(current_price=2653.2, prev_price=2653.1, now_ts=195.0)
    assert ok_expired is True


def test_wave19_volatility_tpsl_high_and_low_vol():
    """Verify VolatilityTPSLAdjuster widens TP in high-vol and tightens in low-vol."""
    adjuster = VolatilityTPSLAdjuster(
        min_tp_pips=20.0,
        max_tp_pips=120.0,
        min_sl_pips=15.0,
        max_sl_pips=60.0,
    )

    # High-volatility series with session vol_index=1.6
    high_vol_closes = [2650.0, 2652.0, 2649.0, 2653.0, 2650.0, 2654.0]
    tp_high, sl_high = adjuster.adjusted_tpsl(
        closes=high_vol_closes,
        base_tp_pips=45.0,
        base_sl_pips=30.0,
        session_info={"vol_index": 1.6},
    )
    assert tp_high > 45.0  # widens TP
    assert 15.0 <= sl_high <= 60.0

    # Low-volatility flat closes with session vol_index=0.4
    low_vol_closes = [2650.00, 2650.02, 2650.01, 2650.03, 2650.01, 2650.02]
    tp_low, sl_low = adjuster.adjusted_tpsl(
        closes=low_vol_closes,
        base_tp_pips=45.0,
        base_sl_pips=30.0,
        session_info={"vol_index": 0.4},
    )
    assert tp_low < 45.0   # tightens TP
    assert sl_low <= 30.0  # tightens SL


def test_wave14_auto_tuner_analysis_and_rules():
    """Verify AutoTuner evaluates trade history metrics and generates parameter tuning rules."""
    tuner = AutoTuner()

    # 1. Insufficient data (< 10 trades)
    res_small = tuner.analyse([{"pnl": 10.0}] * 5)
    assert res_small["status"] == "insufficient_data"

    # 2. Low win rate sample (12 trades: 2 wins, 10 losses -> 16.7% win rate)
    history = (
        [{"pnl": 20.0, "duration_sec": 300, "exit_reason": "TP"}] * 2
        + [{"pnl": -30.0, "duration_sec": 180, "exit_reason": "SL"}] * 10
    )
    cfg = {
        "sl_pips": 30.0,
        "tp_pips": 45.0,
        "lot_size": 0.02,
        "max_lot_size": 0.10,
        "max_daily_loss_usd": 200.0,
        "rr_ratio": 1.5,
    }
    res_tune = tuner.analyse(history, current_config=cfg)
    assert len(res_tune["suggestions"]) > 0
    # Proposed SL should be reduced from 30.0
    assert res_tune["proposed_config"]["sl_pips"] < 30.0


def test_wave11_profit_optimizer_streak_and_floating_reversal():
    """Verify ProfitOptimizer tracks streaks and triggers auto-close on floating PnL reversal."""
    po = ProfitOptimizer()

    # 3 consecutive wins -> 1.1x lot modifier
    for _ in range(3):
        po.record_result(won=True)
    assert po.streak_lot_modifier() == 1.1

    # 3 consecutive losses -> recovery mode active, 0.5x lot modifier
    for _ in range(3):
        po.record_result(won=False)
    assert po.is_recovery_mode() is True
    assert po.streak_lot_modifier() == 0.5

    # Floating PnL reversal: peak $20.0, current drops to $8.0 (reversal = (20-8)/20 = 60% > 50%)
    po.update_peak_float("TICKET_1", 20.0)
    assert po.should_close_reversal("TICKET_1", 15.0, threshold=0.5) is False
    assert po.should_close_reversal("TICKET_1", 8.0, threshold=0.5) is True


def test_wave10_session_optimizer_windows_and_quality():
    """Verify SessionOptimizer classifies sessions, avoids dangerous hours, and flags overlap."""
    so = SessionOptimizer()

    # Weekend: Saturday 12:00 UTC -> CLOSED, not tradeable
    sat_dt = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)
    info_sat = so.get_current_session_info(sat_dt)
    assert info_sat["session"] == "CLOSED"
    assert info_sat["tradeable"] is False

    # Friday close: Friday 20:00 UTC -> FRIDAY_CLOSE, not tradeable
    fri_dt = datetime(2026, 10, 16, 20, 0, 0, tzinfo=timezone.utc)
    info_fri = so.get_current_session_info(fri_dt)
    assert info_fri["session"] == "FRIDAY_CLOSE"
    assert info_fri["tradeable"] is False

    # London-NY Overlap: Thursday 14:00 UTC -> PREMIUM overlap, pip_multiplier=1.3, tradeable=True
    overlap_dt = datetime(2026, 10, 15, 14, 0, 0, tzinfo=timezone.utc)
    info_ov = so.get_current_session_info(overlap_dt)
    assert info_ov["session"] == "OVERLAP"
    assert info_ov["quality"] == "PREMIUM"
    assert info_ov["pip_multiplier"] == 1.3
    assert info_ov["tradeable"] is True
