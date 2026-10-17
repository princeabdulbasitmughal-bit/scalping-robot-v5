"""
tests/test_batch108.py
======================
Unit tests for Batch 108:
- wave10_session_optimizer.py (SessionOptimizer)
- wave11_profit_optimizer.py (ProfitOptimizer)
"""

import math
from datetime import datetime, timezone
import pytest
from wave10_session_optimizer import SessionOptimizer
from wave11_profit_optimizer import ProfitOptimizer


# =====================================================================
# SessionOptimizer Tests (wave10)
# =====================================================================

def test_session_optimizer_init_defaults():
    so = SessionOptimizer()
    assert so._total_optimizations == 0
    inf = so.info()
    assert inf["wave"] == 10
    assert inf["name"] == "SessionOptimizer"
    assert "session" in inf
    assert "tradeable" in inf

    so.reset()
    assert so._total_optimizations == 0


def test_session_optimizer_weekend_and_rollover():
    so = SessionOptimizer()

    # Saturday: 2026-10-17 12:00:00 UTC (weekday 5)
    sat_dt = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)
    sat_info = so.get_current_session_info(sat_dt)
    assert sat_info["session"] == "CLOSED"
    assert sat_info["tradeable"] is False
    assert sat_info["reason"] == "WEEKEND"
    assert so.is_entry_blocked(sat_dt) is True

    # Rollover hour: Tuesday 22:30:00 UTC (hour 22 in AVOID_HOURS_UTC)
    tue_rollover = datetime(2026, 10, 20, 22, 30, 0, tzinfo=timezone.utc)
    roll_info = so.get_current_session_info(tue_rollover)
    assert roll_info["session"] == "ROLLOVER"
    assert roll_info["tradeable"] is False
    assert roll_info["reason"] == "ROLLOVER_WINDOW"
    assert so.is_blocked(tue_rollover) is True


def test_session_optimizer_session_classification():
    so = SessionOptimizer()

    # Tuesday 14:30:00 UTC -> London-NY Overlap
    tue_overlap = datetime(2026, 10, 20, 14, 30, 0, tzinfo=timezone.utc)
    ov_info = so.get_current_session_info(tue_overlap)
    assert ov_info["session"] == "OVERLAP"
    assert ov_info["quality"] == "PREMIUM"
    assert ov_info["pip_multiplier"] == 1.3
    assert ov_info["vol_index"] == 10
    assert ov_info["tradeable"] is True
    assert so.is_entry_blocked(tue_overlap) is False

    # Tuesday 08:30:00 UTC -> London peak
    tue_london = datetime(2026, 10, 20, 8, 30, 0, tzinfo=timezone.utc)
    ldn_info = so.get_current_session_info(tue_london)
    assert ldn_info["session"] == "LONDON"
    assert ldn_info["quality"] == "HIGH"
    assert ldn_info["pip_multiplier"] == 1.0
    assert ldn_info["vol_index"] == 9
    assert ldn_info["tradeable"] is True


def test_session_optimizer_friday_and_monday_filters():
    so = SessionOptimizer()

    # Friday 20:00:00 UTC (weekday 4, hour 20 >= 19)
    fri_close = datetime(2026, 10, 23, 20, 0, 0, tzinfo=timezone.utc)
    fri_info = so.get_current_session_info(fri_close)
    assert fri_info["session"] == "FRIDAY_CLOSE"
    assert fri_info["tradeable"] is False
    assert fri_info["reason"] == "FRIDAY_AFTERNOON"

    # Monday 05:00:00 UTC (weekday 0, hour 5 < 8)
    mon_open = datetime(2026, 10, 19, 5, 0, 0, tzinfo=timezone.utc)
    mon_info = so.get_current_session_info(mon_open)
    assert mon_info["session"] == "MONDAY_OPEN"
    assert mon_info["tradeable"] is False
    assert mon_info["reason"] == "MONDAY_MORNING_GAP"


def test_session_optimizer_get_adjusted_targets():
    so = SessionOptimizer()
    tue_overlap = datetime(2026, 10, 20, 14, 0, 0, tzinfo=timezone.utc)

    # In overlap, multiplier is 1.3
    # base_sl = 30.0 -> sl = 30 * 1.3 = 39.0, tp = 39.0 * 1.5 = 58.5
    sl, tp = so.get_adjusted_targets(base_sl=30.0, base_tp=45.0, rr_ratio=1.5, now_dt=tue_overlap)
    assert sl == 39.0
    assert tp == 58.5

    # Safe fallback on invalid/boolean inputs
    sl_bad, tp_bad = so.get_adjusted_targets(base_sl=True, base_tp=False, rr_ratio=-1.0, now_dt=tue_overlap)
    assert 15.0 <= sl_bad <= 70.0
    assert tp_bad > sl_bad


# =====================================================================
# ProfitOptimizer Tests (wave11)
# =====================================================================

def test_profit_optimizer_init_defaults():
    po = ProfitOptimizer()
    assert po.is_recovery_mode() is False
    assert po.streak_lot_modifier() == 1.0
    assert po.is_entry_blocked() is False
    assert po.is_blocked() is False

    inf = po.info()
    assert inf["win_streak"] == 0
    assert inf["loss_streak"] == 0
    assert inf["recovery_mode"] is False
    assert inf["tracked_positions"] == 0


def test_profit_optimizer_streak_lot_modifiers():
    po = ProfitOptimizer()

    # 3 consecutive wins
    for _ in range(3):
        po.record_result(True)
    assert po.streak_lot_modifier() == 1.1
    assert po.is_recovery_mode() is False

    # 3 consecutive losses
    for _ in range(3):
        po.record_result(False)
    assert po.streak_lot_modifier() == 0.5
    assert po.is_recovery_mode() is True

    # 5 consecutive losses
    for _ in range(2):
        po.record_result(False)
    assert po.streak_lot_modifier() == 0.10


def test_profit_optimizer_floating_pnl_peak_and_reversal():
    po = ProfitOptimizer()
    ticket = "12345"

    po.update_peak_float(ticket, 50.0)
    assert po._peak_floating_pnl[ticket] == 50.0

    # Slight reversal: 50 -> 40 (20% drop < 50% threshold)
    assert po.should_close_reversal(ticket, 40.0, threshold=0.5) is False

    # Heavy reversal: 50 -> 20 (60% drop >= 50% threshold)
    assert po.should_close_reversal(ticket, 20.0, threshold=0.5) is True

    # Invalid / boolean input safe
    assert po.should_close_reversal(ticket, True) is False

    po.cleanup_ticket(ticket)
    assert ticket not in po._peak_floating_pnl


def test_profit_optimizer_partial_close_level():
    po = ProfitOptimizer()
    ticket = "99999"

    # Below 40% TP: 10 pips / 40.0 tp = 25%
    lvl_early = po.get_partial_close_level(ticket=ticket, pips_profit=10.0, tp_pips=40.0, lot_size=0.10)
    assert lvl_early is None

    # At or above 40% TP: 18 pips / 40.0 tp = 45% -> closes 33% of 0.10 = 0.03
    lvl_close = po.get_partial_close_level(ticket=ticket, pips_profit=18.0, tp_pips=40.0, lot_size=0.10)
    assert lvl_close == 0.03

    # Subsequent call for same ticket: already partially closed -> None
    lvl_dup = po.get_partial_close_level(ticket=ticket, pips_profit=25.0, tp_pips=40.0, lot_size=0.07)
    assert lvl_dup is None


def test_profit_optimizer_dynamic_tp_extension_and_daily_scale():
    po = ProfitOptimizer()

    # Dynamic TP extension: trending market, win streak >= 2, profit >= 80% of TP (36 / 40 = 90%)
    ext_tp = po.get_extended_tp_pips(
        base_tp=40.0,
        pips_profit=36.0,
        market_regime="TRENDING_UP",
        win_streak=3,
    )
    assert ext_tp == 48.0  # 40 * 1.2

    # In ranging market, no extension
    no_ext = po.get_extended_tp_pips(
        base_tp=40.0,
        pips_profit=36.0,
        market_regime="RANGING",
        win_streak=3,
    )
    assert no_ext == 40.0

    # Daily target scaling
    scale_half = po.daily_target_lot_scale(daily_pnl=160.0, daily_target=200.0)  # 80% >= 75%
    assert scale_half == 0.5

    scale_three_quarters = po.daily_target_lot_scale(daily_pnl=120.0, daily_target=200.0)  # 60% >= 50%
    assert scale_three_quarters == 0.75

    scale_full = po.daily_target_lot_scale(daily_pnl=50.0, daily_target=200.0)  # 25% < 50%
    assert scale_full == 1.0
