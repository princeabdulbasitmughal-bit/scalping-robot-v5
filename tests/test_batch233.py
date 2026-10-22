"""
tests/test_batch233.py
-----------------------
Unit test suite for Batch 233:
- Wave 232: Quote Level Resiliency Half-Life & Spread Gap Recovery Guard
- Wave 233: Multi-Venue Order Flow Inter-Arrival Cross-Entropy Guard

Verifies post-shock spread healing failure, persistent wide-spread fractures,
cross-venue arrival distribution KL divergence, routing lag, fail-closed assertions, and cooldowns.
"""

import math
import time
import pytest

import wave232_lob_spread_resiliency_half_life_guard as wave232
import wave233_cross_venue_interarrival_cross_entropy_guard as wave233


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave232.reset()
    wave233.reset()
    yield
    wave232.reset()
    wave233.reset()


# ---------------------------------------------------------------------------
# Wave 232: LOB Spread Resiliency Half-Life Guard Tests
# ---------------------------------------------------------------------------

def test_wave232_healthy_fast_resiliency_recovery_no_block():
    """Rapid post-shock spread healing back toward baseline does not block."""
    assert not wave232.is_entry_blocked()
    assert not wave232.is_blocked()

    t = 1000.0
    # Shock to 5.0 bps
    wave232.record_spread(spread_bps=5.0, ts=t)
    # Rapid retrace to 1.5 bps in 0.5s (retrace = (5.0 - 1.5) / (5.0 - 1.0) = 87.5% >= 40%)
    wave232.record_spread(spread_bps=1.5, ts=t + 0.5)

    assert not wave232.is_entry_blocked()
    metrics = wave232.get_resiliency_metrics()
    assert metrics["retrace_ratio"] >= wave232.MIN_RETRACE_RATIO
    status = wave232.get_status()
    assert not status["is_blocked"]


def test_wave232_failed_resiliency_retrace_blocks():
    """Spread remaining wide without healing after 2.0s blocks entries for 45s."""
    t = 2000.0
    # Shock to 6.0 bps
    wave232.record_spread(spread_bps=6.0, ts=t)
    # Fails to heal: stays at 5.5 bps after 2.5s (retrace = 10% <= 40%)
    wave232.update(spread_bps=5.5, ts=t + 2.5)

    assert wave232.is_entry_blocked()
    assert wave232.is_blocked()
    metrics = wave232.get_resiliency_metrics()
    assert metrics["retrace_ratio"] < wave232.MIN_RETRACE_RATIO
    status = wave232.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave232_persistent_wide_spread_fracture_blocks():
    """Spread >= 8.0 bps persisting for >= 1.5s immediately triggers fracture cooldown block."""
    t = 3000.0
    wave232.record_spread(spread_bps=9.0, ts=t)
    wave232.record_spread(spread_bps=9.0, ts=t + 1.6)

    assert wave232.is_entry_blocked()
    assert wave232.is_blocked()
    status = wave232.get_status()
    assert status["is_blocked"]


def test_wave232_direct_shock_record_blocks():
    """Direct invocation of record_spread_shock validates unhealed spread and blocks."""
    # Shock = 6.0 bps, current = 5.2 bps after 2.2s -> retrace = 16% <= 40%
    wave232.record_spread_shock(spread_bps=5.2, shock_start_spread_bps=6.0, elapsed_sec=2.2)

    assert wave232.is_entry_blocked()
    metrics = wave232.get_resiliency_metrics()
    assert metrics["retrace_ratio"] < wave232.MIN_RETRACE_RATIO


def test_wave232_input_validation_and_reset():
    """Non-positive spreads, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave232.record_spread(True)
    wave232.record_spread(False)
    wave232.record_spread(-1.0)
    wave232.record_spread(0.0)
    wave232.record_spread(float("nan"))
    wave232.record_spread(float("inf"))

    assert not wave232.is_entry_blocked()

    # Trigger block then reset
    wave232.record_spread(9.0, ts=100.0)
    wave232.record_spread(9.0, ts=102.0)
    assert wave232.is_entry_blocked()

    wave232.reset()
    assert not wave232.is_entry_blocked()
    metrics = wave232.get_resiliency_metrics()
    assert metrics["spread_bps"] == 1.0
    status = wave232.get_status()
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 233: Cross-Venue Inter-Arrival Cross-Entropy Guard Tests
# ---------------------------------------------------------------------------

def test_wave233_synchronized_cross_venue_flow_no_block():
    """Synchronized trade arrival distributions across Venue A and B yield low KL divergence, no block."""
    assert not wave233.is_entry_blocked()
    assert not wave233.is_blocked()

    # 12 trades on both venues arriving every 100ms (bin 1 [50-150ms])
    t_a = 1000.0
    t_b = 1000.0
    for _ in range(12):
        t_a += 0.10
        t_b += 0.10
        wave233.record_venue_trade("Venue_A", ts=t_a)
        wave233.record_venue_trade("Venue_B", ts=t_b)

    assert not wave233.is_entry_blocked()
    metrics = wave233.get_cross_entropy_metrics()
    assert metrics["kl_divergence_bits"] < wave233.MAX_CROSS_ENTROPY
    status = wave233.get_status()
    assert not status["is_blocked"]


def test_wave233_cross_entropy_divergence_blocks():
    """Asymmetric routing causing high KL divergence (D_KL >= 1.20 bits) blocks entries for 45s."""
    # Venue A receives ultra-fast 30ms trades (bin 0 [<50ms])
    # Venue B receives slow 800ms trades (bin 4 [>600ms])
    t_a = 2000.0
    t_b = 2000.0
    for _ in range(12):
        t_a += 0.03
        t_b += 0.80
        wave233.update("A", ts=t_a)
        wave233.update("B", ts=t_b)

    assert wave233.is_entry_blocked()
    assert wave233.is_blocked()
    metrics = wave233.get_cross_entropy_metrics()
    assert metrics["kl_divergence_bits"] >= wave233.MAX_CROSS_ENTROPY
    status = wave233.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave233_desynchronization_lag_blocks():
    """Mean inter-arrival timing lag between venues >= 300ms triggers cooldown block."""
    # Venue A: 80ms interval, Venue B: 420ms interval -> Lag = 340ms >= 300ms
    t_a = 3000.0
    t_b = 3000.0
    for _ in range(12):
        t_a += 0.08
        t_b += 0.42
        wave233.record_venue_trade("A", ts=t_a)
        wave233.record_venue_trade("B", ts=t_b)

    assert wave233.is_entry_blocked()
    metrics = wave233.get_cross_entropy_metrics()
    assert metrics["desynchronization_lag_ms"] >= wave233.MAX_LAG_MS


def test_wave233_insufficient_samples_no_block():
    """Fewer than MIN_SAMPLES=10 trades per venue does not trigger block."""
    t_a = 4000.0
    t_b = 4000.0
    for _ in range(5):
        t_a += 0.02
        t_b += 0.90
        wave233.record_venue_trade("A", ts=t_a)
        wave233.record_venue_trade("B", ts=t_b)

    assert not wave233.is_entry_blocked()
    assert wave233.get_status()["samples_venue_a"] == 4


def test_wave233_input_validation_and_reset():
    """Invalid venues, negative timestamps, booleans, NaNs, and Infs are safely ignored."""
    wave233.record_venue_trade(True, ts=100.0)
    wave233.record_venue_trade("A", ts=True)
    wave233.record_venue_trade("A", ts=-50.0)
    wave233.record_venue_trade("A", ts=float("nan"))
    wave233.record_venue_trade("A", ts=float("inf"))

    assert not wave233.is_entry_blocked()

    # Trigger block then reset
    t_a = 5000.0
    t_b = 5000.0
    for _ in range(12):
        t_a += 0.03
        t_b += 0.80
        wave233.record_venue_trade("A", ts=t_a)
        wave233.record_venue_trade("B", ts=t_b)
    assert wave233.is_entry_blocked()

    wave233.reset()
    assert not wave233.is_entry_blocked()
    metrics = wave233.get_cross_entropy_metrics()
    assert metrics["kl_divergence_bits"] == 0.0
    status = wave233.get_status()
    assert status["samples_venue_a"] == 0
    assert not status["is_blocked"]
