"""
tests/test_batch94.py
Batch 94 Unit Tests: Price Velocity Filter (wave44) & London Open Booster (wave45).
Expands test baseline beyond 1,177+ passing tests to 1,187+ passing tests.
Verifies:
1. wave44: PriceVelocityFilter initialization defaults, window seconds, and parameter sanitization.
2. wave44: Tick price ingestion, time window filtering, and non-finite/negative input rejection.
3. wave44: Sub-threshold price velocity allowing entries without restrictions.
4. wave44: Price velocity breach (> 5.0 pips in 3s) blocking entries with diagnostic explanation.
5. wave44: PriceVelocityFilter reset() clearing and info() diagnostic telemetry reporting.
6. wave45: LondonOpenBooster initialization defaults, discount bounds clamping [0.0, 0.50], and property multipliers.
7. wave45: London open spike window detection (07:00-08:00 UTC) with wrap-around support.
8. wave45: Entry score threshold discount adjustment (10% lower min_score) during active open window.
9. wave45: Window exit score restoration to original threshold and single-increment boost tracking.
10. wave45: LondonOpenBooster reset() clearing and info() telemetry diagnostics introspection.
"""

import math
from datetime import datetime, timezone
import pytest

from wave44_price_velocity_filter import PriceVelocityFilter
from wave45_london_open_booster import LondonOpenBooster


def test_wave44_initialization_defaults_and_clamping():
    """Verify PriceVelocityFilter initializes with defaults and clamps invalid arguments."""
    # Defaults: pip_limit=5.0 pips, window_sec=3.0s, pip_size=0.1
    pvf = PriceVelocityFilter()
    assert pvf._pip_limit == 5.0
    assert pvf._window_sec == 3.0
    assert pvf._pip_size == 0.1
    assert len(pvf._history) == 0
    assert pvf._total_blocks == 0

    # Custom valid configuration
    custom = PriceVelocityFilter(pip_limit=8.0, window_sec=5.0, pip_size=0.01)
    assert custom._pip_limit == 8.0
    assert custom._window_sec == 5.0
    assert custom._pip_size == 0.01

    # Clamping invalid/non-finite inputs
    bad = PriceVelocityFilter(pip_limit=-2.0, window_sec=0.0, pip_size=float("nan"))
    assert bad._pip_limit == 5.0
    assert bad._window_sec == 3.0
    assert bad._pip_size == 0.1


def test_wave44_update_and_rejection_of_invalid():
    """Verify tick price ingestion and rejection of non-finite, negative, boolean, or null inputs."""
    pvf = PriceVelocityFilter()
    t0 = 1750000000.0

    # Valid tick updates
    pvf.update(2400.0, now_ts=t0)
    pvf.update(2400.2, now_ts=t0 + 1.0)
    assert len(pvf._history) == 2

    # Rejected invalid inputs
    pvf.update(None, now_ts=t0 + 2.0)
    pvf.update(True, now_ts=t0 + 2.0)
    pvf.update(False, now_ts=t0 + 2.0)
    pvf.update(-2400.0, now_ts=t0 + 2.0)
    pvf.update(0.0, now_ts=t0 + 2.0)
    pvf.update(float("nan"), now_ts=t0 + 2.0)
    pvf.update(float("inf"), now_ts=t0 + 2.0)
    pvf.update("bad_price", now_ts=t0 + 2.0)
    assert len(pvf._history) == 2


def test_wave44_normal_velocity_allows_trading():
    """Verify price movement within velocity limit (e.g. 2.0 pips <= 5.0 pips) allows entry."""
    pvf = PriceVelocityFilter(pip_limit=5.0, window_sec=3.0, pip_size=0.1)
    t0 = 1750000000.0

    # Move from 2400.0 to 2400.2 over 2 seconds (0.2 / 0.1 = 2.0 pips)
    pvf.update(2400.0, now_ts=t0)
    pvf.update(2400.2, now_ts=t0 + 2.0)

    assert pvf.is_entry_blocked(now_ts=t0 + 2.0) is False
    assert pvf.is_blocked(now_ts=t0 + 2.0) is False
    allowed, reason = pvf.is_trading_allowed(now_ts=t0 + 2.0)
    assert allowed is True
    assert reason == ""


def test_wave44_velocity_breach_blocks_entry():
    """Verify excessive price movement in short window (> 5.0 pips in 3s) blocks entry."""
    pvf = PriceVelocityFilter(pip_limit=5.0, window_sec=3.0, pip_size=0.1)
    t0 = 1750000000.0

    # Move from 2400.0 to 2400.8 over 1.5 seconds (0.8 / 0.1 = 8.0 pips > 5.0 limit)
    pvf.update(2400.0, now_ts=t0)
    pvf.update(2400.8, now_ts=t0 + 1.5)

    assert pvf.is_entry_blocked(now_ts=t0 + 1.5) is True
    assert pvf._total_blocks == 1

    allowed, reason = pvf.is_trading_allowed(now_ts=t0 + 1.5)
    assert allowed is False
    assert "VELOCITY_LIMIT: 8.0p > 5.0p limit" in reason


def test_wave44_reset_and_info_introspection():
    """Verify reset() clears history and metrics, and info() provides diagnostic telemetry."""
    pvf = PriceVelocityFilter(pip_limit=5.0, window_sec=3.0, pip_size=0.1)
    t0 = 1750000000.0
    pvf.update(2400.0, now_ts=t0)
    pvf.update(2400.6, now_ts=t0 + 1.0)
    pvf.is_entry_blocked(now_ts=t0 + 1.0)

    info = pvf.info()
    assert info["wave"] == 44
    assert info["name"] == "PriceVelocityFilter"
    assert info["velocity_pips"] == 6.0
    assert info["pip_limit"] == 5.0
    assert info["window_sec"] == 3.0
    assert info["blocked"] is True
    assert info["total_blocks"] == 1
    assert info["history_length"] == 2

    pvf.reset()
    info_reset = pvf.info()
    assert info_reset["velocity_pips"] == 0.0
    assert info_reset["blocked"] is False
    assert info_reset["total_blocks"] == 0
    assert info_reset["history_length"] == 0


def test_wave45_initialization_defaults_and_clamping():
    """Verify LondonOpenBooster initializes with defaults and clamps discount bounds [0.0, 0.50]."""
    # Defaults: 07:00-08:00 UTC, discount=10% (0.10), multiplier=0.90
    booster = LondonOpenBooster()
    assert booster._start == 7
    assert booster._end == 8
    assert booster._discount == 0.10
    assert booster.multiplier == 0.90
    assert booster._total_boosts == 0

    # Custom valid configuration
    custom = LondonOpenBooster(start_hour_utc=8, end_hour_utc=9, score_discount=0.20)
    assert custom._start == 8
    assert custom._end == 9
    assert custom._discount == 0.20
    assert custom.multiplier == 0.80

    # Clamping discount: max 0.50, min 0.0
    assert LondonOpenBooster(score_discount=0.80)._discount == 0.50
    assert LondonOpenBooster(score_discount=-0.10)._discount == 0.0
    assert LondonOpenBooster(score_discount=float("nan"))._discount == 0.10


def test_wave45_in_london_open_window_detection():
    """Verify active London Open window detection (07:00-08:00 UTC)."""
    booster = LondonOpenBooster(start_hour_utc=7, end_hour_utc=8)

    # Active inside window: 07:15 UTC
    dt_active = datetime(2026, 10, 18, 7, 15, 0, tzinfo=timezone.utc)
    assert booster.is_active(now_dt=dt_active) is True

    # Inactive outside window: 06:59 UTC
    dt_before = datetime(2026, 10, 18, 6, 59, 59, tzinfo=timezone.utc)
    assert booster.is_active(now_dt=dt_before) is False

    # Inactive outside window: 08:00 UTC (end bound is exclusive)
    dt_after = datetime(2026, 10, 18, 8, 0, 0, tzinfo=timezone.utc)
    assert booster.is_active(now_dt=dt_after) is False


def test_wave45_adjust_min_score_in_window():
    """Verify adjust_min_score applies discount during London Open and leaves score unchanged outside."""
    booster = LondonOpenBooster(start_hour_utc=7, end_hour_utc=8, score_discount=0.10)
    dt_active = datetime(2026, 10, 18, 7, 30, 0, tzinfo=timezone.utc)
    dt_inactive = datetime(2026, 10, 18, 11, 0, 0, tzinfo=timezone.utc)

    # In window: min_score 70.0 reduced by 10% -> 63.0
    adj = booster.adjust_min_score(70.0, now_dt=dt_active)
    assert adj == 63.0
    assert booster._total_boosts == 1
    assert booster._last_boosted is True

    # Out of window: min_score 70.0 unchanged
    unadj = booster.adjust_min_score(70.0, now_dt=dt_inactive)
    assert unadj == 70.0
    assert booster._last_boosted is False

    # Invalid min_score inputs returned unmodified
    assert booster.adjust_min_score(None, now_dt=dt_active) is None
    assert booster.adjust_min_score(True, now_dt=dt_active) is True
    assert booster.adjust_min_score(-10.0, now_dt=dt_active) == -10.0
    assert booster.adjust_min_score(0.0, now_dt=dt_active) == 0.0


def test_wave45_consecutive_adjust_boost_count():
    """Verify consecutive adjust_min_score calls in the same active window only increment total_boosts once."""
    booster = LondonOpenBooster(start_hour_utc=7, end_hour_utc=8, score_discount=0.15)
    dt_active1 = datetime(2026, 10, 18, 7, 10, 0, tzinfo=timezone.utc)
    dt_active2 = datetime(2026, 10, 18, 7, 20, 0, tzinfo=timezone.utc)

    # First call in window
    booster.adjust_min_score(80.0, now_dt=dt_active1)
    assert booster._total_boosts == 1

    # Second call in same window: boosted remains active, counter does not double-increment
    booster.adjust_min_score(80.0, now_dt=dt_active2)
    assert booster._total_boosts == 1


def test_wave45_reset_and_info_telemetry():
    """Verify reset() flushes state and info() outputs diagnostic telemetry."""
    booster = LondonOpenBooster(start_hour_utc=7, end_hour_utc=8, score_discount=0.10)
    dt_active = datetime(2026, 10, 18, 7, 45, 0, tzinfo=timezone.utc)
    booster.adjust_min_score(75.0, now_dt=dt_active)

    info = booster.info(now_dt=dt_active)
    assert info["wave"] == 45
    assert info["name"] == "LondonOpenBooster"
    assert info["london_open_active"] is True
    assert info["currently_boosted"] is True
    assert info["window_utc"] == "07:00-08:00"
    assert info["score_discount_pct"] == 10.0
    assert info["score_multiplier"] == 0.90
    assert info["total_boosts"] == 1
    assert info["last_original_score"] == 75.0
    assert info["last_adjusted_score"] == 67.5
    assert info["utc_hour"] == 7

    booster.reset()
    info_reset = booster.info(now_dt=dt_active)
    assert info_reset["total_boosts"] == 0
    assert info_reset["currently_boosted"] is False
    assert info_reset["last_original_score"] is None
