"""
tests/test_batch274.py
----------------------
Unit tests for Batch 274:
  - Wave 314: Wave314LobSpreadMeanReversionHalfLifeGuard
  - Wave 315: Wave315TradeArrivalHawkesBranchingRatioGuard
"""

import math
import time
import pytest

from wave314_lob_spread_mean_reversion_half_life_guard import Wave314LobSpreadMeanReversionHalfLifeGuard
from wave315_trade_arrival_hawkes_branching_ratio_guard import Wave315TradeArrivalHawkesBranchingRatioGuard


# ----------------------------------------------------------------------
# Wave 314 Tests: LOB Spread Mean-Reversion Half-Life Guard
# ----------------------------------------------------------------------

def test_wave314_swift_mean_reversion_no_block():
    guard = Wave314LobSpreadMeanReversionHalfLifeGuard(
        max_persistence_phi=0.92,
        min_samples=12,
    )

    # Oscillating, rapidly mean-reverting spread around 1.20 bps
    for i in range(15):
        spr = 1.20 + (0.30 if i % 2 == 0 else -0.30)
        guard.record_spread(spr)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_reversion_metrics()
    assert metrics["persistence_phi"] < 0.50
    assert not metrics["is_blocked"]


def test_wave314_spread_hysteresis_blocks():
    guard = Wave314LobSpreadMeanReversionHalfLifeGuard(
        max_persistence_phi=0.92,
        min_elevated_spread_bps=2.50,
        min_samples=12,
        cooldown_seconds=45.0,
    )

    # Directly inject precomputed high persistence metrics (phi = 0.95, mean_spread = 3.20 bps)
    guard.record_reversion_metrics(persistence_phi=0.95, mean_spread_bps=3.20, sample_count=16)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    status = guard.get_status()
    assert status["is_blocked"]
    assert "SPREAD_HYSTERESIS" in status["last_block_reason"]


def test_wave314_acute_spread_lockout_blocks():
    guard = Wave314LobSpreadMeanReversionHalfLifeGuard(
        acute_lockout_spread_bps=3.50,
        acute_lockout_ticks=8,
        cooldown_seconds=45.0,
    )

    # 7 wide spread ticks (3.80 bps) -> not yet 8
    for _ in range(7):
        guard.record_spread(3.80)
        assert not guard.is_entry_blocked()

    # 8th tick -> trips acute lockout
    guard.record_spread(3.80)
    assert guard.is_entry_blocked()
    metrics = guard.get_reversion_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_SPREAD_LOCKOUT" in metrics["last_block_reason"]


def test_wave314_direct_reversion_metrics():
    guard = Wave314LobSpreadMeanReversionHalfLifeGuard(
        max_persistence_phi=0.92,
        cooldown_seconds=45.0,
    )

    # Below threshold (phi = 0.50)
    guard.record_reversion_metrics(persistence_phi=0.50, mean_spread_bps=2.0, sample_count=14)
    assert not guard.is_entry_blocked()

    # Above threshold (phi = 0.96)
    guard.record_reversion_metrics(persistence_phi=0.96, mean_spread_bps=3.0, sample_count=14)
    assert guard.is_entry_blocked()
    assert "SPREAD_HYSTERESIS" in guard.get_status()["last_block_reason"]


def test_wave314_fail_closed_and_reset():
    guard = Wave314LobSpreadMeanReversionHalfLifeGuard(cooldown_seconds=45.0)

    # Corrupted inputs: zero, negative, NaN, Inf, bool, None
    for bad_s in [0.0, -2.0, float("nan"), float("inf"), True, None]:
        guard.record_spread(bad_s)
        assert guard.is_entry_blocked()
        assert "CORRUPTED_SPREAD_INPUT" in guard.get_status()["last_block_reason"]
        guard.reset()
        assert not guard.is_entry_blocked()

    # Update alias check
    guard.update(1.2)
    assert not guard.is_entry_blocked()


# ----------------------------------------------------------------------
# Wave 315 Tests: Trade Arrival Hawkes Branching Ratio Guard
# ----------------------------------------------------------------------

def test_wave315_subcritical_poisson_arrivals_no_block():
    guard = Wave315TradeArrivalHawkesBranchingRatioGuard(
        max_branching_ratio=0.88,
        min_bins=20,
    )

    # 25 independent Poisson-like counts with low autocorrelation
    poisson_counts = [
        1, 2, 0, 1, 3, 1, 0, 2, 1, 1,
        2, 0, 1, 2, 1, 3, 0, 1, 2, 1,
        0, 2, 1, 2, 1
    ]
    for c in poisson_counts:
        guard.record_bin_count(c)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_branching_metrics()
    assert metrics["branching_ratio_eta"] < 0.60
    assert not metrics["is_blocked"]


def test_wave315_critical_branching_surge_blocks():
    guard = Wave315TradeArrivalHawkesBranchingRatioGuard(
        max_branching_ratio=0.88,
        min_bins=20,
        min_mean_bin_trades=1.5,
        cooldown_seconds=45.0,
    )

    # Direct injection of critical branching metrics (eta = 0.94 >= 0.88)
    guard.record_branching_metrics(branching_ratio=0.94, mean_bin_trades=2.5, sample_count=22)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    status = guard.get_status()
    assert status["is_blocked"]
    assert "CRITICAL_BRANCHING_SURGE" in status["last_block_reason"]


def test_wave315_supercritical_cascade_blocks():
    guard = Wave315TradeArrivalHawkesBranchingRatioGuard(
        critical_cascade_eta=1.05,
        min_mean_bin_trades=1.5,
        cooldown_seconds=45.0,
    )

    # Direct injection of supercritical explosive cascade (eta = 1.15 >= 1.05)
    guard.record_branching_metrics(branching_ratio=1.15, mean_bin_trades=3.0, sample_count=12)

    assert guard.is_entry_blocked()
    metrics = guard.get_branching_metrics()
    assert metrics["is_blocked"]
    assert "SUPER_CRITICAL_CASCADE" in metrics["last_block_reason"]


def test_wave315_acute_reflexive_burst_streak_blocks():
    guard = Wave315TradeArrivalHawkesBranchingRatioGuard(
        acute_bin_streak=6,
        acute_min_trades_per_bin=5,
        cooldown_seconds=45.0,
    )

    # 5 dense bins (6 trades/bin) -> not yet 6
    for _ in range(5):
        guard.record_bin_count(6)
        assert not guard.is_entry_blocked()

    # 6th dense bin -> trips acute streak
    guard.record_bin_count(6)
    assert guard.is_entry_blocked()
    assert "ACUTE_REFLEXIVE_BURST_STREAK" in guard.get_status()["last_block_reason"]


def test_wave315_fail_closed_and_reset():
    guard = Wave315TradeArrivalHawkesBranchingRatioGuard(cooldown_seconds=45.0)

    # Corrupted inputs: negative, NaN, Inf, bool, None
    for bad_c in [-1, float("nan"), float("inf"), True, None]:
        guard.record_bin_count(bad_c)
        assert guard.is_entry_blocked()
        assert "CORRUPTED_BIN_COUNT_INPUT" in guard.get_status()["last_block_reason"]
        guard.reset()
        assert not guard.is_entry_blocked()

    # Timestamp arrival binning check
    guard.record_trade_arrival(100.0)
    guard.record_trade_arrival(100.02)
    assert not guard.is_entry_blocked()

    # Update alias check
    guard.update(2)
    assert not guard.is_entry_blocked()
