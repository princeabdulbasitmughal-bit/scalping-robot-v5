"""
Unit Test Suite for Wave 455: Multi-Scale Microstructure Fragility Synthesizer Guard
"""

import pytest
from wave455_multiscale_fragility_synthesizer_guard import Wave455MultiscaleFragilitySynthesizerGuard


def test_initialization_defaults_and_validation():
    guard = Wave455MultiscaleFragilitySynthesizerGuard()
    assert guard.critical_fragility_threshold == 0.65
    assert guard.dual_spike_threshold == 0.85
    assert not guard.is_blocked()

    with pytest.raises(ValueError, match="critical_fragility_threshold"):
        Wave455MultiscaleFragilitySynthesizerGuard(critical_fragility_threshold=0.10)
    with pytest.raises(ValueError, match="critical_fragility_threshold"):
        Wave455MultiscaleFragilitySynthesizerGuard(critical_fragility_threshold=0.99)
    with pytest.raises(ValueError, match="dual_spike_threshold"):
        Wave455MultiscaleFragilitySynthesizerGuard(dual_spike_threshold=0.40)
    with pytest.raises(ValueError, match="dual_spike_threshold"):
        Wave455MultiscaleFragilitySynthesizerGuard(dual_spike_threshold=1.05)


def test_monotonic_timestamp_enforcement():
    guard = Wave455MultiscaleFragilitySynthesizerGuard()
    guard.update(0.1, 0.1, 0.1, 0.1, timestamp=100.0)
    with pytest.raises(ValueError, match="strictly monotonic"):
        guard.update(0.1, 0.1, 0.1, 0.1, timestamp=100.0)
    with pytest.raises(ValueError, match="strictly monotonic"):
        guard.update(0.1, 0.1, 0.1, 0.1, timestamp=99.0)


def test_invalid_input_validation():
    guard = Wave455MultiscaleFragilitySynthesizerGuard()
    with pytest.raises(ValueError, match="must be non-negative"):
        guard.update(-0.1, 0.1, 0.1, 0.1, timestamp=10.0)
    with pytest.raises(ValueError, match="finite"):
        guard.update(float("nan"), 0.1, 0.1, 0.1, timestamp=10.0)


def test_nominal_subcritical_market():
    guard = Wave455MultiscaleFragilitySynthesizerGuard()
    # All vectors low
    blocked = guard.update(0.20, 0.25, 0.15, 0.30, timestamp=10.0)
    assert not blocked
    assert not guard.is_blocked()
    assert guard.composite_fragility == pytest.approx(0.225)
    assert guard.block_reason == ""


def test_composite_fragility_breach():
    guard = Wave455MultiscaleFragilitySynthesizerGuard(critical_fragility_threshold=0.65)
    # Average = 0.70 >= 0.65
    blocked = guard.update(0.70, 0.70, 0.70, 0.70, timestamp=10.0)
    assert blocked
    assert guard.is_blocked()
    assert guard.is_entry_blocked("BUY")
    assert guard.is_entry_blocked("SELL")
    assert "MULTISCALE_FRAGILITY_COLLAPSE" in guard.block_reason


def test_dual_vector_extreme_spike_lock():
    guard = Wave455MultiscaleFragilitySynthesizerGuard(
        critical_fragility_threshold=0.65,
        dual_spike_threshold=0.85
    )
    # Two vectors at 0.90, two vectors at 0.10
    # Composite = 0.25*(0.90 + 0.90 + 0.10 + 0.10) = 0.50 (< 0.65)
    # But dual spike rule must trigger because 2 vectors >= 0.85!
    blocked = guard.update(0.90, 0.90, 0.10, 0.10, timestamp=10.0)
    assert blocked
    assert guard.is_blocked()
    assert "DUAL_VECTOR_EXTREME_CONVERGENCE" in guard.block_reason
    assert "wavelet_hf_energy" in guard.block_reason
    assert "poisson_burstiness" in guard.block_reason


def test_single_vector_spike_does_not_trigger_dual_lock():
    guard = Wave455MultiscaleFragilitySynthesizerGuard(
        critical_fragility_threshold=0.65,
        dual_spike_threshold=0.85
    )
    # Only 1 vector spiked at 0.90, others low at 0.10
    # Composite = 0.25*(0.90 + 0.10 + 0.10 + 0.10) = 0.30 (< 0.65)
    blocked = guard.update(0.90, 0.10, 0.10, 0.10, timestamp=10.0)
    assert not blocked
    assert not guard.is_blocked()
    assert guard.block_reason == ""


def test_telemetry_and_diagnostics():
    guard = Wave455MultiscaleFragilitySynthesizerGuard()
    guard.update(0.20, 0.30, 0.40, 0.50, timestamp=10.0)
    telem = guard.get_telemetry()
    assert telem["guard"] == "Wave455MultiscaleFragilitySynthesizerGuard"
    assert telem["composite_fragility"] == 0.35
    assert telem["critical_threshold"] == 0.65
    assert not telem["is_blocked"]
    assert telem["vectors"]["wavelet_hf_energy"] == 0.20
    assert telem["vectors"]["volume_divergence"] == 0.50


def test_reset_functionality():
    guard = Wave455MultiscaleFragilitySynthesizerGuard()
    guard.update(0.80, 0.80, 0.80, 0.80, timestamp=10.0)
    assert guard.is_blocked()

    guard.reset()
    assert not guard.is_blocked()
    assert guard.composite_fragility == 0.0
    assert guard.block_reason == ""
    assert guard._last_timestamp == 0.0
