"""
tests/test_batch260.py
----------------------
Unit tests for Batch 260:
  - Wave 286: Wave286LobSpreadVarianceRatioGuard
  - Wave 287: Wave287TradeArrivalInterarrivalSkewnessGuard
"""

import math
import time
import pytest

from wave286_lob_spread_variance_ratio_guard import Wave286LobSpreadVarianceRatioGuard
from wave287_trade_arrival_interarrival_skewness_guard import Wave287TradeArrivalInterarrivalSkewnessGuard


# ----------------------------------------------------------------------
# Wave 286 Tests: LOB Inside Spread Realized Variance Ratio Guard
# ----------------------------------------------------------------------

def test_wave286_steady_spread_no_block():
    guard = Wave286LobSpreadVarianceRatioGuard(
        max_variance_ratio=4.50,
        min_mean_spread_bps=2.00,
        min_samples=12,
        acute_spread_std_bps=2.20,
    )

    # Tight, calm spread around 1.0 bps
    for _ in range(15):
        guard.record_spread_bps(1.0)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_spread_variance_metrics()
    assert metrics["short_term_spread_std_bps"] < 0.50
    assert not metrics["is_blocked"]


def test_wave286_spread_variance_ratio_surge_blocks():
    guard = Wave286LobSpreadVarianceRatioGuard(
        max_variance_ratio=4.50,
        min_mean_spread_bps=2.00,
        min_samples=12,
        cooldown_seconds=45.0,
    )

    # Directly inject precomputed spread variance surge (ratio = 5.20, mean spread = 2.50 bps)
    guard.record_spread_variance(variance_ratio=5.20, short_std=1.80, sample_count=14)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    metrics = guard.get_status()
    assert metrics["is_blocked"]
    assert "SPREAD_VARIANCE_RATIO_SURGE" in metrics["last_block_reason"]


def test_wave286_acute_spread_volatility_shock_blocks():
    guard = Wave286LobSpreadVarianceRatioGuard(
        acute_spread_std_bps=2.20,
        acute_min_samples=6,
        cooldown_seconds=45.0,
    )

    # Alternating 0.5 and 6.0 bps spread flickering over 6 ticks
    for _ in range(3):
        guard.record_spread_bps(0.5)
        guard.record_spread_bps(6.0)

    assert guard.is_entry_blocked()
    metrics = guard.get_spread_variance_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_SPREAD_VOLATILITY_SHOCK" in metrics["last_block_reason"]


def test_wave286_insufficient_samples_no_block():
    guard = Wave286LobSpreadVarianceRatioGuard(
        acute_spread_std_bps=2.20,
        acute_min_samples=6,
    )

    # High volatility but only 3 samples (< 6 min_samples)
    guard.record_spread_bps(0.5)
    guard.record_spread_bps(6.0)
    guard.record_spread_bps(0.5)

    assert not guard.is_entry_blocked()


def test_wave286_input_validation_and_reset():
    guard = Wave286LobSpreadVarianceRatioGuard()

    # Boolean spread triggers fail-closed
    guard.record_spread_bps(True)
    assert guard.is_entry_blocked()
    assert "CORRUPTED" in guard.get_status()["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked()

    # Negative spread triggers fail-closed
    guard.update(-2.0)
    assert guard.is_entry_blocked()

    guard.reset()
    assert not guard.is_entry_blocked()


# ----------------------------------------------------------------------
# Wave 287 Tests: Trade Arrival Interarrival Skewness Guard
# ----------------------------------------------------------------------

def test_wave287_regular_arrival_no_block():
    guard = Wave287TradeArrivalInterarrivalSkewnessGuard(
        max_skewness=4.20,
        min_mean_duration=0.35,
        min_trades=15,
        acute_streak_len=8,
    )

    # Regular Poisson-like arrivals (~0.4s to 0.6s)
    durations = [0.4, 0.5, 0.6, 0.45, 0.55, 0.42, 0.58, 0.5, 0.48, 0.52] * 2
    for d in durations:
        guard.record_duration(d)
        assert not guard.is_entry_blocked()

    metrics = guard.get_skewness_metrics()
    assert metrics["duration_skewness"] < 3.0
    assert not metrics["is_blocked"]


def test_wave287_skewness_explosion_blocks():
    guard = Wave287TradeArrivalInterarrivalSkewnessGuard(
        max_skewness=4.20,
        min_mean_duration=0.35,
        min_trades=15,
        cooldown_seconds=45.0,
    )

    # Directly inject precomputed skewness explosion (skew = 4.80, mean_dur = 0.20s)
    guard.record_skewness_metrics(skewness=4.80, mean_duration=0.20, sample_count=18)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    metrics = guard.get_status()
    assert metrics["is_blocked"]
    assert "DURATION_SKEWNESS_EXPLOSION" in metrics["last_block_reason"]


def test_wave287_acute_cascade_streak_blocks():
    guard = Wave287TradeArrivalInterarrivalSkewnessGuard(
        acute_cascade_interval_sec=0.020,
        acute_streak_len=8,
        cooldown_seconds=45.0,
    )

    # 8 consecutive microsecond cascade trades with tau = 10 ms (0.010s)
    for _ in range(8):
        guard.record_duration(0.010)

    assert guard.is_entry_blocked()
    metrics = guard.get_skewness_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_CASCADE_STREAK" in metrics["last_block_reason"]


def test_wave287_insufficient_samples_no_block():
    guard = Wave287TradeArrivalInterarrivalSkewnessGuard(
        max_skewness=4.20,
        min_mean_duration=0.35,
        min_trades=15,
    )

    # High skewness metric but only 6 samples (< 15 min_trades)
    guard.record_skewness_metrics(skewness=5.50, mean_duration=0.15, sample_count=6)

    assert not guard.is_entry_blocked()


def test_wave287_input_validation_and_reset():
    guard = Wave287TradeArrivalInterarrivalSkewnessGuard()

    # Corrupted duration (NaN) triggers fail-closed
    guard.record_duration(float("nan"))
    assert guard.is_entry_blocked()
    assert "CORRUPTED" in guard.get_status()["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked()

    # Boolean duration triggers fail-closed
    guard.update(True)
    assert guard.is_entry_blocked()

    guard.reset()
    assert not guard.is_entry_blocked()
