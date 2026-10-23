"""
tests/test_batch277.py
----------------------
Unit tests for Batch 277:
  - Wave 320: Wave320LobQueueReplenishmentLatencyGuard [Wave 320 Landmark]
  - Wave 321: Wave321TradeSizeLognormalTruncationGuard
"""

import math
import time
import pytest

from wave320_lob_queue_replenishment_latency_guard import Wave320LobQueueReplenishmentLatencyGuard
from wave321_trade_size_lognormal_truncation_guard import Wave321TradeSizeLognormalTruncationGuard


# ----------------------------------------------------------------------
# Wave 320 Tests: LOB Queue Replenishment Latency Guard
# ----------------------------------------------------------------------

def test_wave320_swift_replenishment_no_block():
    guard = Wave320LobQueueReplenishmentLatencyGuard(
        max_replenishment_sec=4.50,
        min_cycles=8,
    )

    # 10 cycles of swift replenishment (latency = 0.5s - 1.0s following 2.5 lot sweeps)
    for _ in range(10):
        guard.record_sweep_cycle(sweep_lots=2.5, latency_sec=0.8)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_replenishment_metrics()
    assert metrics["mean_latency_sec"] <= 1.50
    assert not metrics["is_blocked"]


def test_wave320_replenishment_latency_surge_blocks():
    guard = Wave320LobQueueReplenishmentLatencyGuard(
        max_replenishment_sec=4.50,
        min_cycles=8,
        cooldown_seconds=45.0,
    )

    # Directly inject precomputed high latency metrics (mean latency = 5.20s over 10 cycles)
    guard.record_latency_metrics(mean_latency_sec=5.20, sample_count=10)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    status = guard.get_status()
    assert status["is_blocked"]
    assert "REPLENISHMENT_LATENCY_SURGE" in status["last_block_reason"]


def test_wave320_acute_queue_desertion_freeze_blocks():
    guard = Wave320LobQueueReplenishmentLatencyGuard(
        acute_min_sweep_lots=3.00,
        acute_desertion_sec=6.00,
        cooldown_seconds=45.0,
    )

    # Sweep of 4.0 lots followed by deserted book freezing for 7.5 seconds
    guard.record_sweep_cycle(sweep_lots=4.0, latency_sec=7.5)

    assert guard.is_entry_blocked()
    metrics = guard.get_replenishment_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_QUEUE_DESERTION_FREEZE" in metrics["last_block_reason"]


def test_wave320_direct_latency_metrics():
    guard = Wave320LobQueueReplenishmentLatencyGuard(
        max_replenishment_sec=4.50,
        cooldown_seconds=45.0,
    )

    # Below threshold (latency = 2.0s)
    guard.record_latency_metrics(mean_latency_sec=2.0, sample_count=10)
    assert not guard.is_entry_blocked()

    # Above threshold (latency = 5.0s)
    guard.record_latency_metrics(mean_latency_sec=5.0, sample_count=10)
    assert guard.is_entry_blocked()
    assert "REPLENISHMENT_LATENCY_SURGE" in guard.get_status()["last_block_reason"]


def test_wave320_fail_closed_and_reset():
    guard = Wave320LobQueueReplenishmentLatencyGuard(cooldown_seconds=45.0)

    # Corrupted inputs: zero/negative sweep or latency, NaN, Inf, bool
    for bad_s, bad_l in [(0.0, 1.0), (-2.0, 1.0), (1.0, -0.5), (float("nan"), 1.0), (1.0, float("inf")), (True, 1.0)]:
        guard.record_sweep_cycle(bad_s, bad_l)
        assert guard.is_entry_blocked()
        assert "CORRUPTED_SWEEP_CYCLE_INPUT" in guard.get_status()["last_block_reason"]
        guard.reset()
        assert not guard.is_entry_blocked()

    # Update alias check
    guard.update(2.0, 0.5)
    assert not guard.is_entry_blocked()


# ----------------------------------------------------------------------
# Wave 321 Tests: Trade Size Log-Normal Truncation Guard
# ----------------------------------------------------------------------

def test_wave321_unconstrained_lognormal_no_block():
    guard = Wave321TradeSizeLognormalTruncationGuard(
        min_log_skewness=-1.40,
        min_samples=15,
    )

    # Natural unconstrained trade sizes drawn from log-normal distribution (skewness near 0)
    lognormal_trades = [
        0.3, 0.5, 0.8, 1.2, 1.8, 2.5, 0.4, 0.7, 1.1, 1.6,
        2.2, 3.5, 0.6, 0.9, 1.4, 2.0, 3.0, 4.5
    ]
    for sz in lognormal_trades:
        guard.record_trade_size(sz)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_truncation_metrics()
    assert metrics["log_skewness"] >= -1.0
    assert not metrics["is_blocked"]


def test_wave321_lognormal_truncation_skew_blocks():
    guard = Wave321TradeSizeLognormalTruncationGuard(
        min_log_skewness=-1.40,
        min_mean_volume=2.00,
        min_samples=15,
        cooldown_seconds=45.0,
    )

    # Directly inject precomputed negative skewness metrics (skewness = -1.85, mean_vol = 3.50 lots)
    guard.record_truncation_metrics(log_skewness=-1.85, mean_volume=3.50, sample_count=18)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    status = guard.get_status()
    assert status["is_blocked"]
    assert "LOGNORMAL_TRUNCATION_SKEW" in status["last_block_reason"]


def test_wave321_acute_truncation_ceiling_streak_blocks():
    guard = Wave321TradeSizeLognormalTruncationGuard(
        acute_ceiling_streak=8,
        acute_min_ceiling_lots=5.00,
        cooldown_seconds=45.0,
    )

    # 7 trades hitting 5.0 lots ceiling -> not yet 8
    for _ in range(7):
        guard.record_trade_size(5.0)
        assert not guard.is_entry_blocked()

    # 8th trade hitting 5.0 lots ceiling -> trips acute ceiling streak
    guard.record_trade_size(5.0)
    assert guard.is_entry_blocked()
    metrics = guard.get_truncation_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_TRUNCATION_CEILING_STREAK" in metrics["last_block_reason"]


def test_wave321_direct_truncation_metrics():
    guard = Wave321TradeSizeLognormalTruncationGuard(
        min_log_skewness=-1.40,
        cooldown_seconds=45.0,
    )

    # Below threshold (safe skewness = -0.40)
    guard.record_truncation_metrics(log_skewness=-0.40, mean_volume=2.5, sample_count=16)
    assert not guard.is_entry_blocked()

    # Above threshold (dangerous negative skewness = -1.65)
    guard.record_truncation_metrics(log_skewness=-1.65, mean_volume=2.5, sample_count=16)
    assert guard.is_entry_blocked()
    assert "LOGNORMAL_TRUNCATION_SKEW" in guard.get_status()["last_block_reason"]


def test_wave321_fail_closed_and_reset():
    guard = Wave321TradeSizeLognormalTruncationGuard(cooldown_seconds=45.0)

    # Corrupted inputs: zero, negative, NaN, Inf, bool
    for bad_sz in [0.0, -1.0, float("nan"), float("inf"), True]:
        guard.record_trade_size(bad_sz)
        assert guard.is_entry_blocked()
        assert "CORRUPTED_TRADE_SIZE_INPUT" in guard.get_status()["last_block_reason"]
        guard.reset()
        assert not guard.is_entry_blocked()

    # Update alias check
    guard.update(1.5)
    assert not guard.is_entry_blocked()
