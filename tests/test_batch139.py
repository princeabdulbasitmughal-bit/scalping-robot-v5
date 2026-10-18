"""
Test Suite for Batch 139:
- wave44_price_velocity_filter.py (PriceVelocityFilter: 5-pip in 3s velocity chase filter)
- wave45_london_open_booster.py (LondonOpenBooster: London open 07:00-08:00 UTC score discount)
Zero regressions, continuing toward 1,637+ passed tests.
"""

import math
from datetime import datetime, timezone
import pytest

from wave44_price_velocity_filter import (
    PriceVelocityFilter,
    price_velocity_filter,
    is_entry_blocked as w44_is_entry_blocked,
    is_blocked as w44_is_blocked,
    update as w44_update,
    reset as w44_reset,
)
from wave45_london_open_booster import (
    LondonOpenBooster,
    london_open_booster,
    is_active as w45_is_active,
    adjust_min_score as w45_adjust_min_score,
    reset as w45_reset,
)


# ---------------------------------------------------------------------
# Wave 44: Price Velocity Filter Tests
# ---------------------------------------------------------------------

def test_wave44_initial_state():
    pvf = PriceVelocityFilter()
    assert not pvf.is_entry_blocked()
    assert not pvf.is_blocked()
    allowed, reason = pvf.is_trading_allowed()
    assert allowed
    assert reason == ""
    info = pvf.info()
    assert not info["blocked"]
    assert info["velocity_pips"] == 0.0
    assert info["total_blocks"] == 0
    assert info["history_length"] == 0


def test_wave44_invalid_inputs():
    pvf = PriceVelocityFilter()
    t0 = 1000.0
    invalid_prices = [None, True, False, -100.0, 0.0, float("nan"), float("inf"), "high"]
    for p in invalid_prices:
        pvf.update(p, now_ts=t0)

    assert len(pvf._history) == 0
    assert not pvf.is_entry_blocked(now_ts=t0)


def test_wave44_normal_velocity():
    pvf = PriceVelocityFilter(pip_limit=5.0, window_sec=3.0, pip_size=0.1)
    t0 = 1000.0
    # Price moves from 2000.0 to 2000.2 (2.0 pips over 2.0s < 5.0 pip limit)
    pvf.update(2000.0, now_ts=t0)
    pvf.update(2000.1, now_ts=t0 + 1.0)
    pvf.update(2000.2, now_ts=t0 + 2.0)

    assert not pvf.is_entry_blocked(now_ts=t0 + 2.0)
    assert not pvf.is_blocked(now_ts=t0 + 2.0)
    allowed, reason = pvf.is_trading_allowed(now_ts=t0 + 2.0)
    assert allowed
    assert reason == ""
    info = pvf.info()
    assert info["velocity_pips"] == 2.0


def test_wave44_high_velocity_block():
    pvf = PriceVelocityFilter(pip_limit=5.0, window_sec=3.0, pip_size=0.1)
    t0 = 1000.0
    # Price surges from 2000.0 to 2000.8 (8.0 pips over 1.5s > 5.0 pip limit)
    pvf.update(2000.0, now_ts=t0)
    pvf.update(2000.8, now_ts=t0 + 1.5)

    assert pvf.is_entry_blocked(now_ts=t0 + 1.5)
    assert pvf.is_blocked(now_ts=t0 + 1.5)
    allowed, reason = pvf.is_trading_allowed(now_ts=t0 + 1.5)
    assert not allowed
    assert "VELOCITY_LIMIT" in reason
    info = pvf.info()
    assert info["blocked"]
    assert info["velocity_pips"] == 8.0
    assert info["total_blocks"] >= 1


def test_wave44_window_pruning_and_module_aliases():
    pvf = PriceVelocityFilter(pip_limit=5.0, window_sec=3.0, pip_size=0.1)
    t0 = 1000.0
    pvf.update(2000.0, now_ts=t0)
    pvf.update(2000.8, now_ts=t0 + 1.0)
    assert pvf.is_entry_blocked(now_ts=t0 + 1.0)

    # 4 seconds later (t0 + 5.0), the 3.0s window has expired
    # Price is now stable at 2000.8
    pvf.update(2000.81, now_ts=t0 + 5.0)
    assert not pvf.is_entry_blocked(now_ts=t0 + 5.0)

    pvf.reset()
    assert len(pvf._history) == 0
    assert pvf.info()["velocity_pips"] == 0.0

    # Module-level aliases
    w44_reset()
    assert not w44_is_entry_blocked()
    assert not w44_is_blocked()
    w44_update(2000.0)
    w44_reset()


# ---------------------------------------------------------------------
# Wave 45: London Open Booster Tests
# ---------------------------------------------------------------------

def test_wave45_initial_state():
    lob = LondonOpenBooster()
    assert lob.multiplier == 0.90
    info = lob.info()
    assert info["name"] == "LondonOpenBooster"
    assert info["window_utc"] == "07:00-08:00"
    assert info["score_discount_pct"] == 10.0
    assert info["score_multiplier"] == 0.90
    assert info["total_boosts"] == 0


def test_wave45_invalid_scores():
    lob = LondonOpenBooster()
    dt_london = datetime(2026, 10, 18, 7, 30, tzinfo=timezone.utc)
    for invalid_score in [None, True, False, -50.0, 0.0, float("nan"), float("inf")]:
        res = lob.adjust_min_score(invalid_score, now_dt=dt_london)
        if isinstance(invalid_score, float) and math.isnan(invalid_score):
            assert math.isnan(res)
        else:
            assert res == invalid_score


def test_wave45_outside_london_window():
    lob = LondonOpenBooster()
    # 06:59 UTC (just before London open)
    dt_pre = datetime(2026, 10, 18, 6, 59, tzinfo=timezone.utc)
    assert not lob.is_active(now_dt=dt_pre)
    assert lob.adjust_min_score(70.0, now_dt=dt_pre) == 70.0

    # 08:01 UTC (just after London open window)
    dt_post = datetime(2026, 10, 18, 8, 1, tzinfo=timezone.utc)
    assert not lob.is_active(now_dt=dt_post)
    assert lob.adjust_min_score(70.0, now_dt=dt_post) == 70.0

    info = lob.info(now_dt=dt_post)
    assert not info["london_open_active"]


def test_wave45_inside_london_window():
    lob = LondonOpenBooster()
    # 07:30 UTC (middle of London open)
    dt_active = datetime(2026, 10, 18, 7, 30, tzinfo=timezone.utc)
    assert lob.is_active(now_dt=dt_active)

    # Base score 70.0 discounted by 10% (0.90x) -> 63.0
    adjusted = lob.adjust_min_score(70.0, now_dt=dt_active)
    assert adjusted == 63.0
    assert lob._total_boosts == 1

    info = lob.info(now_dt=dt_active)
    assert info["london_open_active"]
    assert info["currently_boosted"]
    assert info["last_original_score"] == 70.0
    assert info["last_adjusted_score"] == 63.0


def test_wave45_discount_clamping_and_module_aliases():
    # Discount clamped to max 50%
    lob_max = LondonOpenBooster(score_discount=0.80)
    assert lob_max._discount == 0.50
    assert lob_max.multiplier == 0.50

    # Discount clamped to min 0%
    lob_min = LondonOpenBooster(score_discount=-0.20)
    assert lob_min._discount == 0.0
    assert lob_min.multiplier == 1.0

    dt_active = datetime(2026, 10, 18, 7, 15, tzinfo=timezone.utc)
    lob_max.adjust_min_score(80.0, now_dt=dt_active)
    assert lob_max._total_boosts == 1
    lob_max.reset()
    assert lob_max._total_boosts == 0

    # Module-level aliases
    w45_reset()
    assert w45_is_active(now_dt=dt_active)
    assert w45_adjust_min_score(80.0, now_dt=dt_active) == 72.0  # 80 * 0.90
    w45_reset()
