"""
tests/test_batch220.py
-----------------------
Unit test suite for Batch 220:
- Wave 206: Trade Size Uniformity & Iceberg Chunking Dispersion Guard
- Wave 207: High-Frequency Tick Arrival Burst Fano Factor & Cluster Dispersion Guard

Verifies algorithmic order slicing coefficient of variation, tick arrival Fano dispersion,
fail-closed assertions, and monotonic cooldown timers.
"""

import math
import time
import pytest

import wave206_trade_size_clustering_dispersion_guard as wave206
import wave207_tick_arrival_clustering_burst_guard as wave207


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave206.reset()
    wave207.reset()
    yield
    wave206.reset()
    wave207.reset()


# ---------------------------------------------------------------------------
# Wave 206: Trade Size Uniformity Guard Tests
# ---------------------------------------------------------------------------

def test_wave206_normal_heterogeneous_trade_sizes_no_block():
    """Heterogeneous natural trade sizes (CV >= 0.40) do not block."""
    assert not wave206.is_entry_blocked()
    assert not wave206.is_blocked()

    # Varied trade sizes
    sizes = [0.5, 2.0, 5.0, 1.2, 0.8, 3.5, 7.0, 1.5, 4.0, 0.6]
    for s in sizes:
        wave206.record_trade(volume=s)

    assert not wave206.is_entry_blocked()
    metrics = wave206.get_dispersion_metrics()
    assert metrics["volume_cv"] > wave206.MAX_UNIFORMITY_CV
    status = wave206.get_status()
    assert not status["is_blocked"]


def test_wave206_uniform_algorithmic_chunking_blocks():
    """Algorithmic order slicing (CV <= 0.08 with size >= 2.0 lots) blocks entries for 45s."""
    # Automated slicing: 10 chunks around 5.0 lots with negligible variance
    chunks = [5.00, 5.01, 4.99, 5.00, 5.02, 4.98, 5.00, 5.01, 4.99, 5.00]
    for c in chunks:
        wave206.update(volume=c)

    assert wave206.is_entry_blocked()
    assert wave206.is_blocked()
    metrics = wave206.get_dispersion_metrics()
    assert metrics["volume_cv"] <= wave206.MAX_UNIFORMITY_CV
    status = wave206.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave206_identical_chunk_streak_blocks():
    """8 consecutive identical trades of size >= 2.0 lots trigger streak block."""
    for _ in range(8):
        wave206.record_trade(volume=4.0)

    assert wave206.is_entry_blocked()
    metrics = wave206.get_dispersion_metrics()
    assert metrics["identical_streak"] >= 8.0


def test_wave206_input_validation_and_fail_closed():
    """Booleans, negative volumes, NaNs, and Infs are safely rejected."""
    wave206.record_trade(True)  # bool rejected
    wave206.record_trade(False)  # bool rejected
    wave206.record_trade(-5.0)  # negative rejected
    wave206.record_trade(0.0)  # zero rejected
    wave206.record_trade(float("nan"))  # nan rejected
    wave206.record_trade(float("inf"))  # inf rejected
    wave206.record_trade("5.0")  # string rejected

    assert not wave206.is_entry_blocked()
    assert wave206.get_status()["sample_count"] == 0


def test_wave206_reset_and_status():
    """Reset clears volume history, streak counters, and active blocks."""
    for _ in range(8):
        wave206.record_trade(5.0)
    assert wave206.is_entry_blocked()

    wave206.reset()
    assert not wave206.is_entry_blocked()
    metrics = wave206.get_dispersion_metrics()
    assert metrics["identical_streak"] == 0.0
    status = wave206.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 207: Tick Arrival Clustering Fano Factor Guard Tests
# ---------------------------------------------------------------------------

def test_wave207_normal_steady_arrivals_no_block():
    """Evenly spaced steady quote arrivals produce low Fano Factor and do not block."""
    assert not wave207.is_entry_blocked()
    assert not wave207.is_blocked()

    base_t = 100.0
    # 2 ticks per second over 10 seconds
    for sec in range(10):
        wave207.record_tick(ts=base_t + sec + 0.1)
        wave207.record_tick(ts=base_t + sec + 0.6)

    assert not wave207.is_entry_blocked()
    metrics = wave207.get_fano_metrics()
    assert metrics["fano_factor"] < wave207.MAX_FANO_FACTOR
    status = wave207.get_status()
    assert not status["is_blocked"]


def test_wave207_clustered_micro_burst_blocks():
    """Extreme clustering (9 calm seconds followed by 40 ticks in 1s) blocks entries for 45s."""
    base_t = 100.0
    # First 9 seconds: 1 tick each second
    for sec in range(9):
        wave207.record_tick(ts=base_t + sec + 0.5)

    # 10th second: burst of 35 ticks
    for i in range(35):
        wave207.update(ts=base_t + 9.1 + (i * 0.02))

    assert wave207.is_entry_blocked()
    assert wave207.is_blocked()
    metrics = wave207.get_fano_metrics()
    assert metrics["fano_factor"] >= wave207.MAX_FANO_FACTOR
    assert metrics["peak_burst"] >= wave207.MIN_PEAK_BURST
    status = wave207.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave207_low_peak_high_fano_no_block():
    """Modest variations where peak burst < MIN_PEAK_BURST do not trigger block."""
    base_t = 100.0
    # Bins with 0, 0, 0, 5, 0, 0, 0, 6, 0, 0 (peak = 6 < 25)
    wave207.record_tick(ts=base_t + 3.1)
    wave207.record_tick(ts=base_t + 3.2)
    wave207.record_tick(ts=base_t + 7.1)
    wave207.record_tick(ts=base_t + 7.2)

    assert not wave207.is_entry_blocked()


def test_wave207_input_validation_and_fail_closed():
    """Invalid timestamps, booleans, negatives, NaNs, and Infs are rejected safely."""
    wave207.record_tick(ts=True)
    wave207.record_tick(ts=False)
    wave207.record_tick(ts=-100.0)
    wave207.record_tick(ts=0.0)
    wave207.record_tick(ts=float("nan"))
    wave207.record_tick(ts=float("inf"))

    assert not wave207.is_entry_blocked()
    assert wave207.get_status()["sample_count"] == 0


def test_wave207_reset_and_status():
    """Reset clears timestamps, metrics, and active blocks."""
    base_t = 100.0
    for i in range(35):
        wave207.record_tick(ts=base_t + 9.1 + (i * 0.02))
    assert wave207.is_entry_blocked()

    wave207.reset()
    assert not wave207.is_entry_blocked()
    metrics = wave207.get_fano_metrics()
    assert metrics["fano_factor"] == 1.0
    assert metrics["peak_burst"] == 0.0
    status = wave207.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]
