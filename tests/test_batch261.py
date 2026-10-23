"""
tests/test_batch261.py
----------------------
Unit tests for Batch 261:
  - Wave 288: Wave288LobEffectiveSpreadExpansionGuard
  - Wave 289: Wave289TradeArrivalClusteringFanoFactorGuard
"""

import math
import time
import pytest

from wave288_lob_effective_spread_expansion_guard import Wave288LobEffectiveSpreadExpansionGuard
from wave289_trade_arrival_clustering_fano_factor_guard import Wave289TradeArrivalClusteringFanoFactorGuard


# ----------------------------------------------------------------------
# Wave 288 Tests: LOB Realized Effective Spread Blowout Guard
# ----------------------------------------------------------------------

def test_wave288_tight_execution_no_block():
    guard = Wave288LobEffectiveSpreadExpansionGuard(
        max_mean_effective_spread_bps=3.80,
        min_eq_ratio=2.20,
        min_trades=10,
        acute_effective_spread_bps=6.50,
    )

    # Tight fills at inside quotes: mid=100.0, bid=99.995, ask=100.005, trade=100.005 (1.0 bps effective)
    for _ in range(12):
        guard.record_execution(trade_price=100.005, bid_price=99.995, ask_price=100.005, direction=1)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_effective_spread_metrics()
    assert metrics["mean_effective_spread_bps"] <= 1.50
    assert not metrics["is_blocked"]


def test_wave288_effective_spread_expansion_blocks():
    guard = Wave288LobEffectiveSpreadExpansionGuard(
        max_mean_effective_spread_bps=3.80,
        min_eq_ratio=2.20,
        min_trades=10,
        cooldown_seconds=45.0,
    )

    # Directly inject precomputed blown-out effective spread metrics
    guard.record_effective_metrics(effective_bps=4.50, eq_ratio=2.80, sample_count=12)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    metrics = guard.get_status()
    assert metrics["is_blocked"]
    assert "EFFECTIVE_SPREAD_EXPANSION" in metrics["last_block_reason"]


def test_wave288_acute_effective_blowout_blocks():
    guard = Wave288LobEffectiveSpreadExpansionGuard(
        acute_effective_spread_bps=6.50,
        cooldown_seconds=45.0,
    )

    # Severe acute execution walk: mid=100.0, trade executed at 100.050 (10.0 bps effective)
    guard.record_execution(trade_price=100.050, bid_price=99.990, ask_price=100.010, direction=1)

    assert guard.is_entry_blocked()
    metrics = guard.get_effective_spread_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_EFFECTIVE_SPREAD_BLOWOUT" in metrics["last_block_reason"]


def test_wave288_insufficient_samples_no_block():
    guard = Wave288LobEffectiveSpreadExpansionGuard(
        max_mean_effective_spread_bps=3.80,
        min_eq_ratio=2.20,
        min_trades=10,
    )

    # Elevated effective spread but only 4 executions (< 10 min_trades)
    guard.record_effective_metrics(effective_bps=4.20, eq_ratio=2.50, sample_count=4)

    assert not guard.is_entry_blocked()


def test_wave288_input_validation_and_reset():
    guard = Wave288LobEffectiveSpreadExpansionGuard()

    # Invalid direction (e.g. 0) triggers fail-closed
    guard.record_execution(100.0, 99.9, 100.1, direction=0)
    assert guard.is_entry_blocked()
    assert "CORRUPTED" in guard.get_status()["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked()

    # Negative trade price triggers fail-closed
    guard.update(-100.0, 99.9, 100.1, 1)
    assert guard.is_entry_blocked()

    guard.reset()
    assert not guard.is_entry_blocked()


# ----------------------------------------------------------------------
# Wave 289 Tests: Trade Arrival Counting Fano Factor Guard
# ----------------------------------------------------------------------

def test_wave289_regular_poisson_arrival_no_block():
    guard = Wave289TradeArrivalClusteringFanoFactorGuard(
        max_fano_factor=3.80,
        min_mean_count=3.0,
        min_bins=8,
        acute_bin_count=22,
    )

    # Regular Poisson arrivals with ~4 trades per bin
    counts = [4, 5, 3, 4, 5, 4, 3, 5, 4, 4]
    for c in counts:
        guard.record_bin_count(c)
        assert not guard.is_entry_blocked()

    metrics = guard.get_fano_metrics()
    assert metrics["fano_factor"] < 2.0
    assert not metrics["is_blocked"]


def test_wave289_fano_overclustering_blocks():
    guard = Wave289TradeArrivalClusteringFanoFactorGuard(
        max_fano_factor=3.80,
        min_mean_count=3.0,
        min_bins=8,
        cooldown_seconds=45.0,
    )

    # Directly inject precomputed Fano overclustering
    guard.record_fano_metrics(fano_factor=4.50, mean_count=5.0, sample_count=10)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    metrics = guard.get_status()
    assert metrics["is_blocked"]
    assert "FANO_OVERCLUSTERING_SURGE" in metrics["last_block_reason"]


def test_wave289_acute_arrival_avalanche_blocks():
    guard = Wave289TradeArrivalClusteringFanoFactorGuard(
        acute_bin_count=22,
        cooldown_seconds=45.0,
    )

    # Single bin with 25 trades in 1.0s
    guard.record_bin_count(25)

    assert guard.is_entry_blocked()
    metrics = guard.get_fano_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_ARRIVAL_AVALANCHE" in metrics["last_block_reason"]


def test_wave289_insufficient_samples_no_block():
    guard = Wave289TradeArrivalClusteringFanoFactorGuard(
        max_fano_factor=3.80,
        min_mean_count=3.0,
        min_bins=8,
    )

    # High Fano metric but only 3 bins (< 8 min_bins)
    guard.record_fano_metrics(fano_factor=5.0, mean_count=4.0, sample_count=3)

    assert not guard.is_entry_blocked()


def test_wave289_input_validation_and_reset():
    guard = Wave289TradeArrivalClusteringFanoFactorGuard()

    # Boolean trade count triggers fail-closed
    guard.record_bin_count(True)
    assert guard.is_entry_blocked()
    assert "CORRUPTED" in guard.get_status()["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked()

    # Negative count triggers fail-closed
    guard.update(-5)
    assert guard.is_entry_blocked()

    guard.reset()
    assert not guard.is_entry_blocked()
