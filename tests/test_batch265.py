"""
tests/test_batch265.py
----------------------
Unit tests for Batch 265:
  - Wave 296: Wave296LobQueueImbalanceDispersionEntropyGuard
  - Wave 297: Wave297TradeArrivalInterarrivalKurtosisBurstGuard
"""

import math
import time
import pytest

from wave296_lob_queue_imbalance_dispersion_entropy_guard import Wave296LobQueueImbalanceDispersionEntropyGuard
from wave297_trade_arrival_interarrival_kurtosis_burst_guard import Wave297TradeArrivalInterarrivalKurtosisBurstGuard


# ----------------------------------------------------------------------
# Wave 296 Tests: LOB Multi-Level Imbalance Dispersion Shannon Entropy Guard
# ----------------------------------------------------------------------

def test_wave296_well_dispersed_depth_no_block():
    guard = Wave296LobQueueImbalanceDispersionEntropyGuard(
        min_normalized_entropy=0.35,
        min_total_depth=10.0,
        min_samples=8,
        acute_concentration=0.85,
        acute_total_depth=12.0,
    )

    # Well dispersed depths across 3 levels: 5 vs 5, 5 vs 5, 5 vs 5 lots
    bids = [(100.00, 5.0), (99.99, 5.0), (99.98, 5.0)]
    asks = [(100.01, 5.0), (100.02, 5.0), (100.03, 5.0)]

    for _ in range(10):
        guard.record_book_depth(bids, asks)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_dispersion_entropy_metrics()
    assert metrics["normalized_entropy"] >= 0.80
    assert not metrics["is_blocked"]


def test_wave296_entropy_collapse_blocks():
    guard = Wave296LobQueueImbalanceDispersionEntropyGuard(
        min_normalized_entropy=0.35,
        min_total_depth=10.0,
        min_samples=8,
        cooldown_seconds=45.0,
    )

    # Directly inject precomputed entropy collapse (entropy = 0.20, total depth = 15.0 lots)
    guard.record_entropy_metrics(entropy_norm=0.20, max_share=0.75, total_depth=15.0, sample_count=10)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    metrics = guard.get_status()
    assert metrics["is_blocked"]
    assert "DISPERSION_ENTROPY_COLLAPSE" in metrics["last_block_reason"]


def test_wave296_acute_tier_concentration_blocks():
    guard = Wave296LobQueueImbalanceDispersionEntropyGuard(
        acute_concentration=0.85,
        acute_total_depth=12.0,
        cooldown_seconds=45.0,
    )

    # Single snapshot where Level 1 has 20.0 lots while Level 2 and 3 have 0.5 lots each (max_share > 0.90)
    bids = [(100.00, 10.0), (99.99, 0.25), (99.98, 0.25)]
    asks = [(100.01, 10.0), (100.02, 0.25), (100.03, 0.25)]
    guard.record_book_depth(bids, asks)

    assert guard.is_entry_blocked()
    metrics = guard.get_dispersion_entropy_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_TIER_CONCENTRATION" in metrics["last_block_reason"]


def test_wave296_insufficient_samples_no_block():
    guard = Wave296LobQueueImbalanceDispersionEntropyGuard(
        min_normalized_entropy=0.35,
        min_total_depth=10.0,
        min_samples=8,
    )

    # Low entropy metric but only 4 snapshots (< 8 min_samples)
    guard.record_entropy_metrics(entropy_norm=0.25, max_share=0.70, total_depth=15.0, sample_count=4)

    assert not guard.is_entry_blocked()


def test_wave296_input_validation_and_reset():
    guard = Wave296LobQueueImbalanceDispersionEntropyGuard()

    # Corrupted book snapshot triggers fail-closed
    guard.record_book_depth("invalid", [])
    assert guard.is_entry_blocked()
    assert "CORRUPTED" in guard.get_status()["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked()

    # Negative depth triggers fail-closed
    bids = [(100.0, -5.0)]
    asks = [(100.01, 5.0)]
    guard.record_book_depth(bids, asks)
    assert guard.is_entry_blocked()

    guard.reset()
    assert not guard.is_entry_blocked()


# ----------------------------------------------------------------------
# Wave 297 Tests: Trade Arrival Excess Kurtosis Burst Guard
# ----------------------------------------------------------------------

def test_wave297_regular_arrival_no_block():
    guard = Wave297TradeArrivalInterarrivalKurtosisBurstGuard(
        max_excess_kurtosis=12.0,
        min_mean_duration=0.30,
        min_trades=15,
        acute_streak_len=8,
    )

    # Well-behaved arrival durations (~0.4s)
    durations = [0.4, 0.5, 0.35, 0.45, 0.42, 0.38, 0.48, 0.52, 0.41, 0.39] * 2
    for d in durations:
        guard.record_duration(d)
        assert not guard.is_entry_blocked()

    metrics = guard.get_kurtosis_metrics()
    assert metrics["excess_kurtosis"] < 8.0
    assert not metrics["is_blocked"]


def test_wave297_kurtosis_burst_explosion_blocks():
    guard = Wave297TradeArrivalInterarrivalKurtosisBurstGuard(
        max_excess_kurtosis=12.0,
        min_mean_duration=0.30,
        min_trades=15,
        cooldown_seconds=45.0,
    )

    # Directly inject precomputed kurtosis burst metric
    guard.record_kurtosis_metrics(excess_kurtosis=15.5, mean_duration=0.18, sample_count=18)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    metrics = guard.get_status()
    assert metrics["is_blocked"]
    assert "DURATION_KURTOSIS_BURST_EXPLOSION" in metrics["last_block_reason"]


def test_wave297_acute_flash_streak_blocks():
    guard = Wave297TradeArrivalInterarrivalKurtosisBurstGuard(
        acute_burst_interval_sec=0.010,
        acute_streak_len=8,
        cooldown_seconds=45.0,
    )

    # 8 consecutive microsecond flash trades with tau = 5 ms (0.005s)
    for _ in range(8):
        guard.record_duration(0.005)

    assert guard.is_entry_blocked()
    metrics = guard.get_kurtosis_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_FLASH_BURST_STREAK" in metrics["last_block_reason"]


def test_wave297_insufficient_samples_no_block():
    guard = Wave297TradeArrivalInterarrivalKurtosisBurstGuard(
        max_excess_kurtosis=12.0,
        min_mean_duration=0.30,
        min_trades=15,
    )

    # High kurtosis metric but only 6 trades (< 15 min_trades)
    guard.record_kurtosis_metrics(excess_kurtosis=18.0, mean_duration=0.15, sample_count=6)

    assert not guard.is_entry_blocked()


def test_wave297_input_validation_and_reset():
    guard = Wave297TradeArrivalInterarrivalKurtosisBurstGuard()

    # Corrupted duration (NaN) triggers fail-closed
    guard.record_duration(float("nan"))
    assert guard.is_entry_blocked()
    assert "CORRUPTED" in guard.get_status()["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked()

    # Negative duration triggers fail-closed
    guard.update(-0.1)
    assert guard.is_entry_blocked()

    guard.reset()
    assert not guard.is_entry_blocked()
