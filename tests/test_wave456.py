"""
Unit Test Suite for Wave 456: Jump-Diffusion Hazard Rate Circuit Breaker Guard
"""

import pytest
import numpy as np
from wave456_jump_diffusion_hazard_guard import Wave456JumpDiffusionHazardGuard


def test_initialization_defaults_and_validation():
    guard = Wave456JumpDiffusionHazardGuard()
    assert guard.window_size == 30
    assert guard.jump_sigma_multiplier == 3.0
    assert guard.max_jump_intensity == 2.0
    assert guard.max_jump_variance_ratio == 0.40
    assert not guard.is_blocked()

    with pytest.raises(ValueError, match="window_size"):
        Wave456JumpDiffusionHazardGuard(window_size=10)
    with pytest.raises(ValueError, match="jump_sigma_multiplier"):
        Wave456JumpDiffusionHazardGuard(jump_sigma_multiplier=1.2)
    with pytest.raises(ValueError, match="max_jump_intensity"):
        Wave456JumpDiffusionHazardGuard(max_jump_intensity=0.05)
    with pytest.raises(ValueError, match="max_jump_variance_ratio"):
        Wave456JumpDiffusionHazardGuard(max_jump_variance_ratio=0.05)


def test_insufficient_samples_does_not_block():
    guard = Wave456JumpDiffusionHazardGuard(min_samples=12)
    t = 100.0
    for _ in range(8):
        t += 0.5
        blocked = guard.update(0.001, timestamp=t)
        assert not blocked
        assert guard.block_reason == "INSUFFICIENT_SAMPLE"


def test_monotonic_timestamp_and_finite_validation():
    guard = Wave456JumpDiffusionHazardGuard()
    guard.update(0.001, timestamp=10.0)
    with pytest.raises(ValueError, match="strictly monotonic"):
        guard.update(0.001, timestamp=10.0)
    with pytest.raises(ValueError, match="strictly monotonic"):
        guard.update(0.001, timestamp=9.0)
    with pytest.raises(ValueError, match="finite"):
        guard.update(float("inf"), timestamp=11.0)


def test_pure_gaussian_diffusion_no_block():
    guard = Wave456JumpDiffusionHazardGuard(min_samples=12)
    np.random.seed(42)
    # Small Gaussian returns (sigma ~ 0.0005)
    returns = np.random.normal(0.0, 0.0005, size=25)
    t = 50.0
    for r in returns:
        t += 0.5
        guard.update(r, timestamp=t)

    assert not guard.is_blocked()
    assert guard.block_reason == ""
    assert guard.jump_variance_ratio < 0.40


def test_jump_arrival_hazard_burst_blocking():
    guard = Wave456JumpDiffusionHazardGuard(
        jump_sigma_multiplier=2.5,
        max_jump_intensity=2.0,
        min_samples=12
    )
    # 15 baseline ticks with tiny returns (dt = 0.5s)
    t = 100.0
    for _ in range(15):
        t += 0.5
        guard.update(0.0001, timestamp=t)

    # Inject 3 rapid jumps within 0.2s (intensity = 2 / 0.2 = 10 jumps/s > 2.0)
    t += 0.05
    guard.update(0.025, timestamp=t)
    t += 0.05
    guard.update(0.022, timestamp=t)
    t += 0.05
    blocked = guard.update(0.028, timestamp=t)

    assert blocked
    assert guard.is_blocked()
    assert "JUMP_ARRIVAL_HAZARD_BURST" in guard.block_reason


def test_discontinuous_jump_dominance_blocking():
    guard = Wave456JumpDiffusionHazardGuard(
        jump_sigma_multiplier=2.5,
        max_jump_intensity=100.0,  # disable arrival burst to test variance ratio
        max_jump_variance_ratio=0.40,
        min_samples=12
    )
    # 15 small ticks with dt = 1.0s
    t = 10.0
    for _ in range(15):
        t += 1.0
        guard.update(0.0001, timestamp=t)

    # Inject 2 massive jumps spaced by 1.0s (low intensity, huge variance)
    t += 1.0
    guard.update(0.050, timestamp=t)
    t += 1.0
    blocked = guard.update(0.050, timestamp=t)

    assert blocked
    assert guard.is_blocked()
    assert guard.is_entry_blocked("BUY")
    assert guard.is_entry_blocked("SELL")
    assert "DISCONTINUOUS_JUMP_DOMINANCE" in guard.block_reason
    assert guard.jump_variance_ratio > 0.40


def test_sliding_window_eviction():
    guard = Wave456JumpDiffusionHazardGuard(window_size=20)
    t = 1.0
    for i in range(35):
        t += 0.1
        guard.update(0.0005, timestamp=t)

    assert len(guard._returns) == 20
    assert len(guard._timestamps) == 20


def test_telemetry_dictionary_structure():
    guard = Wave456JumpDiffusionHazardGuard()
    t = 1.0
    for _ in range(15):
        t += 0.2
        guard.update(0.0002, timestamp=t)

    telem = guard.get_telemetry()
    assert telem["guard"] == "Wave456JumpDiffusionHazardGuard"
    assert "jump_intensity_hz" in telem
    assert "jump_variance_ratio" in telem
    assert "continuous_sigma" in telem
    assert telem["sample_size"] == 15
    assert isinstance(telem["is_blocked"], bool)


def test_reset_functionality():
    guard = Wave456JumpDiffusionHazardGuard()
    t = 10.0
    for _ in range(15):
        t += 0.1
        guard.update(0.0001, timestamp=t)
    guard.update(0.05, timestamp=12.0)
    guard.update(0.05, timestamp=12.1)

    guard.reset()
    assert len(guard._returns) == 0
    assert not guard.is_blocked()
    assert guard.jump_intensity_hz == 0.0
    assert guard.jump_variance_ratio == 0.0
    assert guard.block_reason == ""
