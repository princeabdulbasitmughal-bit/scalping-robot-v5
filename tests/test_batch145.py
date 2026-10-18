"""
Test Suite for Batch 145:
- wave56_consecutive_loss_guard.py (ConsecutiveLossGuard: 3 consecutive losses 30-min entry pause)
- wave57_hourly_pnl_map.py (HourlyPnLMap: hourly PnL map & 50% lot scaling on loss hours)
Zero regressions, continuing toward 1,697+ passed tests.
"""

import math
from datetime import datetime, timezone
import pytest

from wave56_consecutive_loss_guard import (
    ConsecutiveLossGuard,
    consecutive_loss_guard,
    is_entry_blocked as w56_is_entry_blocked,
    is_blocked as w56_is_blocked,
    record_trade as w56_record_trade,
    reset as w56_reset,
)
from wave57_hourly_pnl_map import (
    HourlyPnLMap,
    hourly_pnl_map,
    get_lot_multiplier as w57_get_lot_multiplier,
    record_trade as w57_record_trade,
    reset as w57_reset,
)


# ---------------------------------------------------------------------
# Wave 56: Consecutive Loss Guard Tests
# ---------------------------------------------------------------------

def test_wave56_initial_state():
    clg = ConsecutiveLossGuard()
    assert clg.max_losses == 3
    assert clg.pause_seconds == 1800.0
    assert not clg.is_entry_blocked()
    assert not clg.is_blocked()
    info = clg.info()
    assert info["consecutive_losses"] == 0
    assert not info["paused"]
    assert info["total_pauses"] == 0


def test_wave56_single_and_two_losses_no_pause():
    clg = ConsecutiveLossGuard(max_losses=3)
    t0 = 1000.0
    clg.record_trade(won=False, now_ts=t0)
    assert not clg.is_entry_blocked(now_ts=t0)
    assert clg.info(now_ts=t0)["consecutive_losses"] == 1

    clg.record_trade(won=False, now_ts=t0 + 10)
    assert not clg.is_entry_blocked(now_ts=t0 + 10)
    assert clg.info(now_ts=t0 + 10)["consecutive_losses"] == 2


def test_wave56_three_losses_trigger_pause():
    clg = ConsecutiveLossGuard(max_losses=3, pause_seconds=1800.0)
    t0 = 1000.0
    clg.record_trade(won=False, now_ts=t0)
    clg.record_trade(won=False, now_ts=t0 + 10)
    clg.record_trade(won=False, now_ts=t0 + 20)

    # 3 losses trigger 1800s pause (until t0 + 20 + 1800 = 2820.0)
    current_t = t0 + 20.0
    assert clg.is_entry_blocked(now_ts=current_t)
    assert clg.is_blocked(now_ts=current_t)
    info = clg.info(now_ts=current_t)
    assert info["paused"]
    assert info["pause_remaining_sec"] == 1800.0
    assert info["total_pauses"] == 1


def test_wave56_win_resets_streak():
    clg = ConsecutiveLossGuard(max_losses=3)
    t0 = 1000.0
    clg.record_trade(won=False, now_ts=t0)
    clg.record_trade(won=False, now_ts=t0 + 10)
    assert clg.info()["consecutive_losses"] == 2

    # Win resets streak to 0
    clg.record_trade(won=True, now_ts=t0 + 20)
    assert clg.info()["consecutive_losses"] == 0
    assert not clg.is_entry_blocked(now_ts=t0 + 20)


def test_wave56_cooldown_expiry_and_module_aliases():
    clg = ConsecutiveLossGuard(max_losses=3, pause_seconds=1800.0)
    t0 = 1000.0
    clg.record_trade(won=False, now_ts=t0)
    clg.record_trade(won=False, now_ts=t0 + 10)
    clg.record_trade(won=False, now_ts=t0 + 20)
    assert clg.is_entry_blocked(now_ts=t0 + 20)

    # 1801 seconds later, the pause has expired
    t_after = t0 + 20 + 1801.0
    assert not clg.is_entry_blocked(now_ts=t_after)
    assert clg.info(now_ts=t_after)["consecutive_losses"] == 0

    clg.reset()
    assert not clg.is_entry_blocked()

    # Module-level aliases
    w56_reset()
    assert not w56_is_entry_blocked()
    assert not w56_is_blocked()
    w56_record_trade(won=False)
    w56_record_trade(won=True)
    w56_reset()


# ---------------------------------------------------------------------
# Wave 57: Hourly PnL Map Tests
# ---------------------------------------------------------------------

def test_wave57_initial_state():
    hpm = HourlyPnLMap()
    assert hpm.loss_threshold_usd == -30.0
    assert hpm.get_lot_multiplier() == 1.0
    info = hpm.info()
    assert info["name"] == "HourlyPnLMap"
    assert info["lot_multiplier"] == 1.0
    assert info["total_trades_recorded"] == 0


def test_wave57_invalid_pnl_inputs():
    hpm = HourlyPnLMap()
    dt = datetime(2026, 10, 18, 14, 0, tzinfo=timezone.utc)
    for bad in [None, True, False, float("nan"), float("inf"), "abc"]:
        hpm.record_trade(bad, now_dt=dt)

    assert hpm.get_lot_multiplier(now_dt=dt) == 1.0
    assert hpm.info(now_dt=dt)["total_trades_recorded"] == 0


def test_wave57_positive_and_moderate_loss():
    hpm = HourlyPnLMap(loss_threshold_usd=-30.0)
    dt_14 = datetime(2026, 10, 18, 14, 15, tzinfo=timezone.utc)

    # Gain: +$25.0
    hpm.record_trade(25.0, now_dt=dt_14)
    assert hpm.get_lot_multiplier(now_dt=dt_14) == 1.0

    # Loss: -$40.0 -> net is +$25 - $40 = -$15.0 (> -$30.0 threshold)
    hpm.record_trade(-40.0, now_dt=dt_14)
    assert hpm.get_lot_multiplier(now_dt=dt_14) == 1.0
    assert hpm.info(now_dt=dt_14)["current_hour_pnl_usd"] == -15.0


def test_wave57_excessive_loss_scales_lot():
    hpm = HourlyPnLMap(loss_threshold_usd=-30.0)
    dt_14 = datetime(2026, 10, 18, 14, 30, tzinfo=timezone.utc)
    dt_15 = datetime(2026, 10, 18, 15, 0, tzinfo=timezone.utc)

    # Hour 14 accumulates -$50.0 loss (< -$30.0 threshold)
    hpm.record_trade(-50.0, now_dt=dt_14)
    assert hpm.get_lot_multiplier(now_dt=dt_14) == 0.5
    assert hpm.info(now_dt=dt_14)["lot_multiplier"] == 0.5

    # Hour 15 has 0.0 PnL, lot multiplier is unaffected (1.0x)
    assert hpm.get_lot_multiplier(now_dt=dt_15) == 1.0


def test_wave57_rollover_and_module_aliases():
    hpm = HourlyPnLMap(loss_threshold_usd=-30.0)
    dt_day1 = datetime(2026, 10, 18, 14, 0, tzinfo=timezone.utc)
    hpm.record_trade(-50.0, now_dt=dt_day1)
    assert hpm.get_lot_multiplier(now_dt=dt_day1) == 0.5

    # Rollover to next day at 14:00 UTC (2026-10-19)
    dt_day2 = datetime(2026, 10, 19, 14, 0, tzinfo=timezone.utc)
    # Map automatically reset upon new date detection
    assert hpm.get_lot_multiplier(now_dt=dt_day2) == 1.0
    assert hpm.info(now_dt=dt_day2)["current_hour_pnl_usd"] == 0.0

    hpm.reset()
    assert hpm.info()["total_trades_recorded"] == 0

    # Module-level aliases
    w57_reset()
    assert w57_get_lot_multiplier(now_dt=dt_day1) == 1.0
    w57_record_trade(10.0, now_dt=dt_day1)
    assert w57_get_lot_multiplier(now_dt=dt_day1) == 1.0
    w57_reset()
