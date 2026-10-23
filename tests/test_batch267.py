"""
tests/test_batch267.py
----------------------
Unit tests for Batch 267:
  - Wave 300: Wave300LobResilienceRecoveryIndexGuard
  - Wave 301: Wave301TradeArrivalPoissonClumpingGuard
"""

import math
import time
import pytest

from wave300_lob_resilience_recovery_index_guard import Wave300LobResilienceRecoveryIndexGuard
from wave301_trade_arrival_poisson_clumping_guard import Wave301TradeArrivalPoissonClumpingGuard


# ----------------------------------------------------------------------
# Wave 300 Tests: LOB Post-Trade Queue Resilience & Depth Recovery Guard
# ----------------------------------------------------------------------

def test_wave300_rapid_recovery_no_block():
    guard = Wave300LobResilienceRecoveryIndexGuard(
        min_resilience_ratio=0.25,
        min_cycles=8,
        acute_freeze_ratio=0.10,
    )

    # 10 cycles where a 5.0 lot sweep is rapidly restocked by 4.5 lots (ratio = 0.90) in 0.5s
    for _ in range(10):
        guard.record_sweep_recovery(sweep_depth=5.0, recovered_depth=4.5, duration_sec=0.5)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_resilience_metrics()
    assert metrics["mean_resilience_ratio"] >= 0.80
    assert not metrics["is_blocked"]


def test_wave300_impaired_resilience_blocks():
    guard = Wave300LobResilienceRecoveryIndexGuard(
        min_resilience_ratio=0.25,
        min_cycles=8,
        cooldown_seconds=45.0,
    )

    # Directly inject precomputed impaired resilience metric (ratio = 0.15 over 10 cycles)
    guard.record_resilience_metrics(recovery_ratio=0.15, duration_sec=1.0, sweep_depth=4.0, sample_count=10)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    metrics = guard.get_status()
    assert metrics["is_blocked"]
    assert "IMPAIRED_BOOK_RESILIENCE" in metrics["last_block_reason"]


def test_wave300_acute_hollow_freeze_blocks():
    guard = Wave300LobResilienceRecoveryIndexGuard(
        acute_freeze_ratio=0.10,
        acute_freeze_duration_sec=3.0,
        acute_min_sweep_depth=5.0,
        cooldown_seconds=45.0,
    )

    # Sweep of 6.0 lots, recovered only 0.20 lots (ratio = 0.033) persisting for 3.5s
    guard.record_sweep_recovery(sweep_depth=6.0, recovered_depth=0.20, duration_sec=3.5)

    assert guard.is_entry_blocked()
    metrics = guard.get_resilience_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_HOLLOW_FREEZE" in metrics["last_block_reason"]


def test_wave300_insufficient_samples_no_block():
    guard = Wave300LobResilienceRecoveryIndexGuard(
        min_resilience_ratio=0.25,
        min_cycles=8,
    )

    # Low recovery ratio (0.15) but only 4 cycles (< 8 min_cycles)
    guard.record_resilience_metrics(recovery_ratio=0.15, duration_sec=1.0, sweep_depth=3.0, sample_count=4)

    assert not guard.is_entry_blocked()


def test_wave300_input_validation_and_reset():
    guard = Wave300LobResilienceRecoveryIndexGuard()

    # Boolean sweep depth triggers fail-closed
    guard.record_sweep_recovery(True, 5.0)
    assert guard.is_entry_blocked()
    assert "CORRUPTED" in guard.get_status()["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked()

    # Negative recovered depth triggers fail-closed
    guard.record_sweep_recovery(5.0, -1.0)
    assert guard.is_entry_blocked()

    guard.reset()
    assert not guard.is_entry_blocked()


# ----------------------------------------------------------------------
# Wave 301 Tests: Trade Arrival Poisson Clumping Heuristic Guard
# ----------------------------------------------------------------------

def test_wave301_small_clumps_no_block():
    guard = Wave301TradeArrivalPoissonClumpingGuard(
        max_mean_clump_size=5.5,
        min_clumps=8,
        acute_hyper_clump=16,
    )

    # Small natural clumps of 1-3 trades
    clumps = [1, 2, 1, 3, 2, 1, 2, 1, 2, 3]
    for c in clumps:
        guard.record_clump_size(c)
        assert not guard.is_entry_blocked()

    metrics = guard.get_clumping_metrics()
    assert metrics["mean_clump_size"] <= 2.5
    assert not metrics["is_blocked"]


def test_wave301_clumping_surge_blocks():
    guard = Wave301TradeArrivalPoissonClumpingGuard(
        max_mean_clump_size=5.5,
        min_clumps=8,
        cooldown_seconds=45.0,
    )

    # Directly inject precomputed Poisson clumping surge metric
    guard.record_clump_metrics(mean_clump_size=6.8, acute_clump=5, sample_count=10)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    metrics = guard.get_status()
    assert metrics["is_blocked"]
    assert "POISSON_CLUMPING_SURGE" in metrics["last_block_reason"]


def test_wave301_acute_hyper_clump_blocks():
    guard = Wave301TradeArrivalPoissonClumpingGuard(
        acute_hyper_clump=16,
        clump_distance_sec=0.050,
        cooldown_seconds=45.0,
    )

    # Contiguous cluster of 16 trades arriving at 10 ms intervals
    for _ in range(16):
        guard.record_duration(0.010)

    assert guard.is_entry_blocked()
    metrics = guard.get_clumping_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_HYPER_CLUMP" in metrics["last_block_reason"]


def test_wave301_insufficient_samples_no_block():
    guard = Wave301TradeArrivalPoissonClumpingGuard(
        max_mean_clump_size=5.5,
        min_clumps=8,
    )

    # High clump metric but only 4 clumps (< 8 min_clumps)
    guard.record_clump_metrics(mean_clump_size=7.5, acute_clump=6, sample_count=4)

    assert not guard.is_entry_blocked()


def test_wave301_input_validation_and_reset():
    guard = Wave301TradeArrivalPoissonClumpingGuard()

    # Corrupted duration (NaN) triggers fail-closed
    guard.record_duration(float("nan"))
    assert guard.is_entry_blocked()
    assert "CORRUPTED" in guard.get_status()["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked()

    # Negative duration triggers fail-closed
    guard.update(-0.05)
    assert guard.is_entry_blocked()

    guard.reset()
    assert not guard.is_entry_blocked()
