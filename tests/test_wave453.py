"""
Unit Test Suite for Wave 453: Multivariate Hawkes Cross-Excitation & Contagion Spillover Guard
"""

import pytest
import numpy as np
from wave453_hawkes_cross_excitation_spillover_guard import Wave453HawkesCrossExcitationSpilloverGuard


def test_initialization_defaults_and_validation():
    guard = Wave453HawkesCrossExcitationSpilloverGuard()
    assert guard.num_channels == 4
    assert guard.decay_beta == 10.0
    assert guard.window_size == 50
    assert guard.max_spectral_radius == 0.88
    assert guard.max_spillover_ratio == 0.65

    # Validations
    with pytest.raises(ValueError, match="num_channels must be in"):
        Wave453HawkesCrossExcitationSpilloverGuard(num_channels=1)
    with pytest.raises(ValueError, match="decay_beta must be > 0.1"):
        Wave453HawkesCrossExcitationSpilloverGuard(decay_beta=0.05)
    with pytest.raises(ValueError, match="window_size must be >= 20"):
        Wave453HawkesCrossExcitationSpilloverGuard(window_size=10)
    with pytest.raises(ValueError, match="max_spectral_radius must be in"):
        Wave453HawkesCrossExcitationSpilloverGuard(max_spectral_radius=0.1)
    with pytest.raises(ValueError, match="max_spillover_ratio must be in"):
        Wave453HawkesCrossExcitationSpilloverGuard(max_spillover_ratio=0.05)


def test_warmup_insufficient_events():
    guard = Wave453HawkesCrossExcitationSpilloverGuard(min_events_for_decision=15)
    t = 1000.0
    for i in range(10):
        t += 0.5
        blocked = guard.update(timestamp=t, channel_id=i % 4)
        assert not blocked
        assert guard._block_reason == "WARMUP_INSUFFICIENT_EVENTS"


def test_monotonic_timestamp_enforcement():
    guard = Wave453HawkesCrossExcitationSpilloverGuard()
    guard.update(100.0, 0)
    with pytest.raises(ValueError, match="strictly monotonic"):
        guard.update(100.0, 1)
    with pytest.raises(ValueError, match="strictly monotonic"):
        guard.update(99.0, 2)
    with pytest.raises(ValueError, match="finite"):
        guard.update(float("nan"), 0)
    with pytest.raises(ValueError, match="channel_id must be in"):
        guard.update(101.0, 99)


def test_subcritical_stationary_arrivals():
    guard = Wave453HawkesCrossExcitationSpilloverGuard(
        num_channels=3,
        decay_beta=10.0,
        max_spectral_radius=0.88,
        min_events_for_decision=15
    )
    # Slow, equispaced independent arrivals (dt = 0.5s -> e^(-10 * 0.5) = e^-5 ~ 0.0067)
    t = 100.0
    for i in range(25):
        t += 0.5
        guard.update(t, i % 3)

    assert not guard._is_blocked
    assert guard._block_reason == "NOMINAL_STATIONARY"
    assert guard.spectral_radius < 0.88


def test_supercritical_explosive_cascade_blocking():
    guard = Wave453HawkesCrossExcitationSpilloverGuard(
        num_channels=3,
        decay_beta=5.0,
        max_spectral_radius=0.75,
        min_events_for_decision=15
    )
    # Extremely dense rapid clustered bursts across all channels (dt = 0.001s)
    # Heavy accumulation in R without decay
    t = 500.0
    blocked_any = False
    for i in range(30):
        t += 0.001
        is_blocked = guard.update(t, i % 3)
        if is_blocked:
            blocked_any = True

    assert blocked_any
    assert guard._is_blocked
    assert "HAWKES_SUPERCRITICAL_CASCADE" in guard._block_reason
    assert guard.spectral_radius >= 0.75


def test_cross_spillover_contagion_blocking():
    guard = Wave453HawkesCrossExcitationSpilloverGuard(
        num_channels=4,
        decay_beta=5.0,
        max_spectral_radius=2.0,  # disable spectral radius check to test spillover
        max_spillover_ratio=0.60,
        min_events_for_decision=15
    )
    # Alternating circular cross-channel triggers (0 -> 1 -> 2 -> 3 -> 0)
    # Maximizes off-diagonal cross-excitation vs self-excitation
    t = 200.0
    for i in range(25):
        t += 0.05
        guard.update(t, i % 4)

    diag = {guard.get_diagnostics()}
    assert guard.spillover_ratio > 0.60
    assert guard._is_blocked
    assert "HAWKES_CROSS_SPILLOVER_CONTAGION" in guard._block_reason


def test_sliding_window_eviction():
    guard = Wave453HawkesCrossExcitationSpilloverGuard(window_size=20)
    t = 10.0
    for i in range(35):
        t += 0.1
        guard.update(t, i % 4)

    assert len(guard._events) == 20


def test_diagnostics_structure_and_types():
    guard = Wave453HawkesCrossExcitationSpilloverGuard()
    t = 50.0
    for i in range(20):
        t += 0.2
        guard.update(t, i % 4)

    diag = guard.get_diagnostics()
    assert isinstance(diag["num_channels"], int)
    assert isinstance(diag["spectral_radius"], float)
    assert isinstance(diag["spillover_ratio"], float)
    assert isinstance(diag["is_blocked"], bool)
    assert isinstance(diag["block_reason"], str)
    assert isinstance(diag["channel_counts"], list)
    assert len(diag["channel_counts"]) == 4


def test_reset_functionality():
    guard = Wave453HawkesCrossExcitationSpilloverGuard()
    t = 10.0
    for i in range(20):
        t += 0.05
        guard.update(t, i % 4)

    assert len(guard._events) > 0
    guard.reset()
    assert len(guard._events) == 0
    assert guard.spectral_radius == 0.0
    assert guard.spillover_ratio == 0.0
    assert not guard._is_blocked
    assert guard._block_reason == ""
