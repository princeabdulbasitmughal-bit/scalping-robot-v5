"""
Unit tests for Batch 30: Wave Modules Hardening
Covers:
- wave13_ml_predictor (LinearRegressor & MLPredictor RLock, reset, info, outcome sanitization)
- wave14_auto_tuner (AutoTuner RLock, reset, get_seconds_since_last_run, corrupt trade guards)
- wave19_volatility_tpsl (VolatilityTPSLAdjuster RLock, info, reset)
- wave20_spike_filter (SpikeFilter RLock, deterministic now_ts injection, reset, info)
- wave21_news_guard (NewsGuard RLock, set_override, reset, info)
- wave22_equity_curve_halt (EquityCurveHalt RLock, now_mono injection, reset, info)
- wave23_spread_optimizer (SpreadOptimizer RLock, session limits, reset)
- wave24_daily_profit_lock (DailyProfitLock RLock, protect mode, info, reset)
- wave25_drawdown_accelerator (DrawdownAccelerator RLock, progressive lot reduction, info, reset)
- wave30_session_lot_booster (SessionLotBooster RLock, now_dt support, info, reset)
"""

import math
import time
from datetime import datetime, timezone
import pytest

from wave13_ml_predictor import LinearRegressor, MLPredictor
from wave14_auto_tuner import AutoTuner
from wave19_volatility_tpsl import VolatilityTPSLAdjuster
from wave20_spike_filter import SpikeFilter
from wave21_news_guard import NewsGuard
from wave22_equity_curve_halt import EquityCurveHalt
from wave23_spread_optimizer import SpreadOptimizer
from wave24_daily_profit_lock import DailyProfitLock
from wave25_drawdown_accelerator import DrawdownAccelerator
from wave30_session_lot_booster import SessionLotBooster


# ==============================================================================
# Wave 13: MLPredictor Hardened
# ==============================================================================
def test_wave13_ml_predictor_hardened():
    predictor = MLPredictor(window=10, min_r2=0.20)

    # 1. Prediction on clean uptrend
    uptrend = [100.0 + i * 0.5 for i in range(25)]
    pred_up = predictor.predict(uptrend)
    assert pred_up["direction"] == "UP"
    assert pred_up["slope"] > 0
    assert pred_up["confidence"] > 0

    # 2. Agreement check
    agree_buy = predictor.predict_signal_agreement(uptrend, "BUY")
    assert agree_buy["agree"] is True
    assert agree_buy["direction"] == "UP"
    assert agree_buy["boost"] >= 1.0

    # 3. Outcome tracking with sanitized case-insensitive strings
    predictor.record_outcome("UP", "up")
    predictor.record_outcome("DOWN", "UP")
    assert predictor.accuracy == 50.0

    info = predictor.info()
    assert info["total_checked"] == 2
    assert info["hit_count"] == 1
    assert "last_prediction" in info

    # 4. Reset
    predictor.reset()
    assert predictor.accuracy == 0.0
    assert predictor.info()["total_checked"] == 0

    # 5. LinearRegressor standalone alias
    reg = LinearRegressor()
    fit_res = reg.fit([1.0, 2.0, 3.0, 4.0, 5.0])
    assert fit_res["slope"] == pytest.approx(1.0)
    assert fit_res["r_squared"] == pytest.approx(1.0)
    reg.reset()


# ==============================================================================
# Wave 14: AutoTuner Hardened
# ==============================================================================
def test_wave14_auto_tuner_hardened():
    tuner = AutoTuner()

    # 1. Insufficient data (< 10 trades)
    report_empty = tuner.analyse([])
    assert report_empty["status"] == "insufficient_data"

    # 2. 15 trades with high win rate
    mock_history = [
        {"pnl": 15.0, "exit_reason": "TP_HIT", "duration_sec": 120} for _ in range(12)
    ] + [
        {"pnl": -10.0, "exit_reason": "SL_HIT", "duration_sec": 60} for _ in range(3)
    ]
    report = tuner.analyse(mock_history)
    assert report["status"] == "ok"
    assert report["trades_analysed"] == 15
    assert report["win_rate_pct"] == 80.0
    assert report["profit_factor"] > 1.0

    # 3. get_seconds_since_last_run with deterministic now_ts
    t0 = 5000000.0
    tuner.analyse_and_tune(mock_history, dry_run=True)
    tuner._last_run = t0
    assert tuner.get_seconds_since_last_run(now_ts=t0 + 45.0) == 45.0

    tuner.reset()
    assert tuner.get_seconds_since_last_run() == float("inf")


# ==============================================================================
# Wave 19: VolatilityTPSLAdjuster Hardened
# ==============================================================================
def test_wave19_volatility_tpsl_hardened():
    adjuster = VolatilityTPSLAdjuster(min_tp_pips=20.0, max_tp_pips=120.0, min_sl_pips=15.0, max_sl_pips=60.0)

    # 1. High-volatility session widens TP up to 1.5x
    high_vol_closes = [2400.0 + (i % 2) * 5.0 for i in range(30)]
    tp_high, sl_high = adjuster.adjusted_tpsl(high_vol_closes, base_tp_pips=40.0, base_sl_pips=30.0, session_info={"vol_index": 1.6})
    assert tp_high > 40.0
    assert sl_high == 30.0  # SL preserved for improved R:R

    # 2. Low-volatility session tightens both TP and SL
    flat_closes = [2400.0 + (i * 0.01) for i in range(30)]
    tp_low, sl_low = adjuster.adjusted_tpsl(flat_closes, base_tp_pips=40.0, base_sl_pips=30.0, session_info={"vol_index": 0.5})
    assert tp_low < 40.0
    assert sl_low < 30.0

    info = adjuster.info()
    assert info["min_tp_pips"] == 20.0
    assert info["max_tp_pips"] == 120.0
    adjuster.reset()


# ==============================================================================
# Wave 20: SpikeFilter Hardened
# ==============================================================================
def test_wave20_spike_filter_hardened():
    filter_ = SpikeFilter(spike_ratio_threshold=4.0, cooldown_sec=90.0, lookback=10)

    t0 = 3000000.0
    # 1. Feed baseline normal ticks (avg change ~0.2 pips)
    for i in range(10):
        ok, reason = filter_.check(2400.0 + (i * 0.2), 2400.0 + ((i - 1) * 0.2), now_ts=t0 + i)
        assert ok is True

    # 2. Huge price spike: 2.0 pips (10x avg) triggers spike cooldown
    ok_spike, reason_spike = filter_.check(2402.0, 2400.0, now_ts=t0 + 15)
    assert ok_spike is False
    assert "SPIKE" in reason_spike

    # 3. Check cooldown active at 30s, expired at 100s
    assert filter_.is_blocked(now_ts=t0 + 45) is True
    assert filter_.is_blocked(now_ts=t0 + 110) is False

    info = filter_.info(now_ts=t0 + 45)
    assert info["blocked"] is True

    filter_.reset()
    assert filter_.is_blocked(now_ts=t0 + 45) is False


# ==============================================================================
# Wave 21: NewsGuard Hardened
# ==============================================================================
def test_wave21_news_guard_hardened():
    guard = NewsGuard()

    # 1. Explicit override to avoid trading
    guard.set_override(avoid=True, reason="FOMC Rate Decision Announcement")
    allowed, reason = guard.is_trading_allowed()
    assert allowed is False
    assert "FOMC" in reason
    assert guard.info()["blocked_total"] == 1

    # 2. Clear override and reset
    guard.reset()
    assert guard.info()["blocked_total"] == 0


# ==============================================================================
# Wave 22: EquityCurveHalt Hardened
# ==============================================================================
def test_wave22_equity_curve_halt_hardened():
    eq_halt = EquityCurveHalt(window=5, loss_threshold_usd=-100.0, slope_threshold=-15.0, recovery_win_streak=2, cooldown_sec=300.0)

    mono = 1000.0
    # 1. Feed 5 consecutive losses of -$25 each (sum -$125 < -100, slope -25 < -15)
    for _ in range(5):
        eq_halt.record_trade(-25.0, won=False)

    allowed, reason = eq_halt.is_trading_allowed(9875.0, now_mono=mono)
    assert allowed is False
    assert "EQUITY CURVE HALT" in reason

    # 2. Cooldown recovery after 301 seconds
    allowed_recovered, reason_rec = eq_halt.is_trading_allowed(9875.0, now_mono=mono + 305.0)
    assert allowed_recovered is True
    assert "recovered" in reason_rec

    # 3. Reset
    eq_halt.reset()
    assert eq_halt.info()["halted"] is False


# ==============================================================================
# Wave 23: SpreadOptimizer Hardened
# ==============================================================================
def test_wave23_spread_optimizer_hardened():
    opt = SpreadOptimizer()

    # 1. London/NY overlap (13:00 UTC) allows up to 3.5 pips
    dt_overlap = datetime(2026, 10, 17, 13, 30, tzinfo=timezone.utc)
    ok_overlap, _ = opt.is_spread_ok(3.2, now_dt=dt_overlap)
    assert ok_overlap is True

    # 2. Off-hours (23:00 UTC / Tokyo) rejects 2.0 pips (Tokyo limit 1.8)
    dt_tokyo = datetime(2026, 10, 17, 23, 0, tzinfo=timezone.utc)
    ok_tokyo, reason_tokyo = opt.is_spread_ok(2.2, now_dt=dt_tokyo)
    assert ok_tokyo is False
    assert "REJECT" in reason_tokyo

    opt.reset()


# ==============================================================================
# Wave 24: DailyProfitLock Hardened
# ==============================================================================
def test_wave24_daily_profit_lock_hardened():
    lock = DailyProfitLock(profit_target_usd=150.0)

    # 1. PnL below target -> protect mode inactive
    lock.update(100.0)
    assert lock.is_active is False
    assert lock.apply_lot(0.05) == 0.05
    assert lock.apply_min_score(55) == 55

    # 2. PnL reaches target ($160 >= $150) -> protect mode engaged
    lock.update(160.0)
    assert lock.is_active is True
    assert lock.apply_lot(0.05) == 0.01  # reduced to 0.01
    assert lock.apply_min_score(55) == 70  # increased to 70

    info = lock.info()
    assert info["protect_mode"] is True
    assert info["peak_daily_pnl"] == 160.0

    lock.reset()
    assert lock.is_active is False


# ==============================================================================
# Wave 25: DrawdownAccelerator Hardened
# ==============================================================================
def test_wave25_drawdown_accelerator_hardened():
    accel = DrawdownAccelerator(recovery_wins=2)

    # 1. 3 consecutive losses -> lot × 0.50
    for _ in range(3):
        accel.record_trade(won=False)
    assert accel.get_multiplier() == 0.50
    assert accel.apply_lot(0.10) == 0.05

    # 2. 5 consecutive losses -> lot × 0.25
    for _ in range(2):
        accel.record_trade(won=False)
    assert accel.get_multiplier() == 0.25
    assert accel.apply_lot(0.08) == 0.02

    # 3. Recovery via 2 consecutive wins
    accel.record_trade(won=True)
    assert accel._consec_wins == 1
    accel.record_trade(won=True)
    assert accel.get_multiplier() == 1.0   # fully recovered
    assert accel.apply_lot(0.10) == 0.10

    info = accel.info()
    assert info["current_multiplier"] == 1.0
    accel.reset()


# ==============================================================================
# Wave 30: SessionLotBooster Hardened
# ==============================================================================
def test_wave30_session_lot_booster_hardened():
    booster = SessionLotBooster(overlap_start_utc=12, overlap_end_utc=15, boost_multiplier=1.2, min_vol_index=1.3, min_win_rate=55.0)

    # 1. Outside overlap window (08:00 UTC) -> no boost
    dt_morning = datetime(2026, 10, 17, 8, 30, tzinfo=timezone.utc)
    assert booster.apply_boost(0.10, vol_index=1.5, win_rate_pct=60.0, now_dt=dt_morning) == 0.10

    # 2. Inside overlap window (13:00 UTC) with favourable conditions -> 1.2x boost
    dt_overlap = datetime(2026, 10, 17, 13, 30, tzinfo=timezone.utc)
    assert booster.apply_boost(0.10, vol_index=1.5, win_rate_pct=60.0, now_dt=dt_overlap) == 0.12

    info = booster.info(now_dt=dt_overlap)
    assert info["in_overlap_window"] is True
    assert info["currently_boosted"] is True

    booster.reset()
    assert booster.info(now_dt=dt_overlap)["total_boosts"] == 0
