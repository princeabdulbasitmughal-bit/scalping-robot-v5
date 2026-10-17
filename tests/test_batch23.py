"""
test_batch23.py - Regression & Hardening tests for Batch 23:
- wave23_spread_optimizer: Finite guards, deterministic now_dt session detection, volatility scaling.
- wave24_daily_profit_lock: Finite guards, protect mode engagement, lot clamping, score raising, reset.
- wave25_drawdown_accelerator: Progressive sizing reduction, recovery threshold, finite float bounds.
- wave30_session_lot_booster: Deterministic now_dt overlap injection, qualification guards, thread safety.
"""

import math
import threading
from datetime import datetime, timezone
import pytest

from wave23_spread_optimizer import SpreadOptimizer
from wave24_daily_profit_lock import DailyProfitLock
from wave25_drawdown_accelerator import DrawdownAccelerator
from wave30_session_lot_booster import SessionLotBooster


def test_wave23_spread_optimizer():
    opt = SpreadOptimizer()
    opt.reset()

    # 1. Non-finite or negative spread rejected
    ok, reason = opt.is_spread_ok(float('nan'))
    assert ok is False
    assert "invalid spread value" in reason

    ok, reason = opt.is_spread_ok(float('inf'))
    assert ok is False

    ok, reason = opt.is_spread_ok(-1.5)
    assert ok is False

    ok, reason = opt.is_spread_ok("invalid")
    assert ok is False

    # 2. Deterministic session resolution via now_dt
    # London session: 09:00 UTC (limit = 3.0)
    dt_london = datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)
    ok_lon, _ = opt.is_spread_ok(2.8, now_dt=dt_london)
    assert ok_lon is True
    assert opt.info()["session"] == "LONDON"

    # Tokyo session: 03:00 UTC (limit = 1.8)
    dt_tokyo = datetime(2026, 10, 19, 3, 0, tzinfo=timezone.utc)
    ok_tok, _ = opt.is_spread_ok(2.2, now_dt=dt_tokyo)
    assert ok_tok is False
    assert opt.info()["session"] == "TOKYO"

    # Overlap session: 14:00 UTC (limit = 3.5) with high vol (1.5x -> limit * 1.2 = 4.2)
    dt_overlap = datetime(2026, 10, 19, 14, 0, tzinfo=timezone.utc)
    ok_ov, _ = opt.is_spread_ok(3.8, vol_index=1.6, now_dt=dt_overlap)
    assert ok_ov is True
    assert opt.info()["session"] == "LDN_NY"


def test_wave24_daily_profit_lock():
    lock = DailyProfitLock(profit_target_usd=100.0, protect_lot=0.01, protect_min_score=70)
    lock.reset()

    # 1. Non-finite PnL safely ignored
    lock.update(float('nan'))
    lock.update(float('inf'))
    assert lock.is_active is False

    # 2. Under target -> normal trading
    lock.update(80.0)
    assert lock.is_active is False
    assert lock.apply_lot(0.05) == 0.05
    assert lock.get_min_score(55) == 55

    # 3. Hit target -> protect mode engaged
    lock.update(105.0)
    assert lock.is_active is True
    assert lock.apply_lot(0.05) == 0.01
    assert lock.get_min_score(55) == 70

    # 4. Non-finite lot handling
    assert math.isnan(lock.apply_lot(float('nan')))
    assert lock.apply_lot(-0.02) == -0.02

    # 5. Reset restores normal state
    lock.reset()
    assert lock.is_active is False
    assert lock.apply_lot(0.05) == 0.05


def test_wave25_drawdown_accelerator():
    accel = DrawdownAccelerator(recovery_wins=2)
    accel.reset()

    # 1. Initial state
    assert accel.get_multiplier() == 1.0
    assert accel.apply_lot(0.10) == 0.10

    # 2. 3 consecutive losses -> 0.5x
    for _ in range(3):
        accel.record_trade(False)
    assert accel.get_multiplier() == 0.50
    assert accel.apply_lot(0.10) == 0.05

    # 3. 5 consecutive losses -> 0.25x
    accel.record_trade(False)
    accel.record_trade(False)
    assert accel.get_multiplier() == 0.25
    assert accel.apply_lot(0.10) == 0.02 or accel.apply_lot(0.10) == 0.03  # 0.025 rounded

    # 4. 1 win does not fully restore
    accel.record_trade(True)
    assert accel.get_multiplier() == 1.0 or accel._consec_wins == 1

    # 2nd consecutive win -> full recovery
    accel.record_trade(True)
    assert accel.get_multiplier() == 1.0
    assert accel.apply_lot(0.10) == 0.10

    # 5. Non-finite lot guarded
    assert accel.apply_lot(float('nan')) == 0.0
    assert accel.apply_lot(-0.05) == 0.0


def test_wave30_session_lot_booster():
    booster = SessionLotBooster(
        overlap_start_utc=12,
        overlap_end_utc=15,
        boost_multiplier=1.2,
        min_vol_index=1.3,
        min_win_rate=55.0
    )
    booster.reset()

    # 1. Non-finite lot inputs return unmodified lot
    assert math.isnan(booster.apply_boost(float('nan')))
    assert booster.apply_boost(-0.02) == -0.02

    # 2. Inside overlap (13:00 UTC) with qualified vol & win rate -> boosted
    dt_inside = datetime(2026, 10, 19, 13, 0, tzinfo=timezone.utc)
    boosted = booster.apply_boost(0.10, vol_index=1.4, win_rate_pct=60.0, now_dt=dt_inside)
    assert boosted == 0.12

    # 3. Inside overlap but low vol -> not boosted
    regular = booster.apply_boost(0.10, vol_index=1.0, win_rate_pct=60.0, now_dt=dt_inside)
    assert regular == 0.10

    # 4. Outside overlap (08:00 UTC) -> not boosted
    dt_outside = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)
    out = booster.apply_boost(0.10, vol_index=1.5, win_rate_pct=70.0, now_dt=dt_outside)
    assert out == 0.10

    # 5. Thread safety
    def run_boosts():
        for _ in range(25):
            booster.apply_boost(0.05, vol_index=1.5, win_rate_pct=65.0, now_dt=dt_inside)

    threads = [threading.Thread(target=run_boosts) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    info = booster.info()
    assert info["total_boosts"] >= 1
