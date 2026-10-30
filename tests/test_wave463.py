"""
Unit Test Suite for Wave 463: Discrete Fourier Spectral Density HFT Signature Guard
"""

import math
import numpy as np
import pytest
from wave463_spectral_density_hft_signature_guard import Wave463SpectralDensityHFTSignatureGuard


def test_initialization_defaults_and_validation():
    guard = Wave463SpectralDensityHFTSignatureGuard()
    assert guard.window_size == 32
    assert guard.max_hf_energy_ratio == 0.65
    assert guard.max_peak_prominence == 4.50
    assert guard.min_samples == 16
    assert guard.cooldown_sec == 2.0
    assert not guard.is_blocked()

    with pytest.raises(ValueError, match="window_size"):
        Wave463SpectralDensityHFTSignatureGuard(window_size=12)
    with pytest.raises(ValueError, match="max_hf_energy_ratio"):
        Wave463SpectralDensityHFTSignatureGuard(max_hf_energy_ratio=0.20)
    with pytest.raises(ValueError, match="max_peak_prominence"):
        Wave463SpectralDensityHFTSignatureGuard(max_peak_prominence=1.20)
    with pytest.raises(ValueError, match="min_samples"):
        Wave463SpectralDensityHFTSignatureGuard(min_samples=8)
    with pytest.raises(ValueError, match="cooldown_sec"):
        Wave463SpectralDensityHFTSignatureGuard(cooldown_sec=0.05)


def test_input_validation_and_monotonicity():
    guard = Wave463SpectralDensityHFTSignatureGuard()

    # Non-finite values
    with pytest.raises(ValueError, match="finite"):
        guard.update(value=float("nan"), timestamp=1.0)
    with pytest.raises(ValueError, match="finite"):
        guard.update(value=1.0, timestamp=float("inf"))

    # Monotonic timestamps
    guard.update(value=1.0, timestamp=10.0)
    with pytest.raises(ValueError, match="strictly monotonic"):
        guard.update(value=1.5, timestamp=10.0)
    with pytest.raises(ValueError, match="strictly monotonic"):
        guard.update(value=1.5, timestamp=9.0)


def test_insufficient_samples_state():
    guard = Wave463SpectralDensityHFTSignatureGuard(min_samples=16)
    for i in range(15):
        blocked = guard.update(value=math.sin(i * 0.5), timestamp=10.0 + i * 0.1)
        assert not blocked
        assert not guard.is_blocked()
        assert guard.block_reason == "INSUFFICIENT_SAMPLES"


def test_broadband_pink_noise_no_block():
    guard = Wave463SpectralDensityHFTSignatureGuard(
        window_size=32,
        min_samples=16,
        max_peak_prominence=4.50,
        max_hf_energy_ratio=0.75
    )
    # Simulate broadband Gaussian stochastic returns with uniform spectral spread
    t = 10.0
    np.random.seed(42)
    # White noise returns have roughly uniform expected spectral density across bins
    noise = np.random.normal(0.0, 1.0, size=32)
    for i in range(32):
        t += 0.05
        blocked = guard.update(value=float(noise[i]), timestamp=t)

    assert not blocked
    assert not guard.is_blocked()
    assert guard.block_reason == ""


def test_periodic_harmonic_pulse_block():
    guard = Wave463SpectralDensityHFTSignatureGuard(
        window_size=32,
        min_samples=16,
        max_peak_prominence=4.50
    )
    # Pure single-frequency sinusoidal oscillation at f = 4/32 = 0.125 cycles/sample
    # This concentrates all AC energy in a single FFT bin, maximizing peak prominence Pi > 10x
    t = 100.0
    for i in range(32):
        t += 0.05
        # Sinusoidal tone
        val = 10.0 * math.sin(2.0 * math.pi * 4.0 * (i / 32.0))
        guard.update(value=val, timestamp=t)

    assert guard.is_blocked()
    assert guard.is_entry_blocked("BUY")
    assert guard.is_entry_blocked("SELL")
    assert "HFT_PERIODIC_SPECTRAL_PULSE" in guard.block_reason
    assert guard.peak_prominence > 4.50
    assert abs(guard.dominant_frequency - 0.125) < 0.02


def test_high_frequency_noise_dominance_block():
    guard = Wave463SpectralDensityHFTSignatureGuard(
        window_size=32,
        min_samples=16,
        max_hf_energy_ratio=0.65,
        max_peak_prominence=20.0 # High so periodic pulse check doesn't mask HF check
    )
    # Alternating high-frequency noise at Nyquist limit f = 0.50 (where f >= 0.25)
    t = 200.0
    for i in range(32):
        t += 0.02
        val = 5.0 if i % 2 == 0 else -5.0
        guard.update(value=val, timestamp=t)

    assert guard.is_blocked()
    assert "HF_NOISE_ENERGY_DOMINANCE" in guard.block_reason or "HFT_PERIODIC_SPECTRAL_PULSE" in guard.block_reason
    assert guard.hf_energy_ratio > 0.65


def test_cooldown_period_enforcement():
    guard = Wave463SpectralDensityHFTSignatureGuard(
        window_size=32,
        min_samples=16,
        cooldown_sec=2.0
    )
    t = 300.0
    # Trigger periodic breach
    for i in range(32):
        t += 0.05
        val = 10.0 * math.sin(2.0 * math.pi * 4.0 * (i / 32.0))
        guard.update(value=val, timestamp=t)

    assert guard.is_blocked()

    # Next update within cooldown (0.5s < 2.0s cooldown)
    t += 0.5
    blocked_in_cooldown = guard.update(value=0.0, timestamp=t)
    assert blocked_in_cooldown
    assert guard.is_blocked()


def test_telemetry_dictionary_structure():
    guard = Wave463SpectralDensityHFTSignatureGuard()
    t = 400.0
    for i in range(20):
        t += 0.05
        guard.update(value=float(i % 5), timestamp=t)

    telem = guard.get_telemetry()
    assert telem["guard"] == "Wave463SpectralDensityHFTSignatureGuard"
    assert "hf_energy_ratio" in telem
    assert "peak_prominence" in telem
    assert "dominant_frequency" in telem
    assert telem["max_hf_energy_ratio"] == 0.65
    assert telem["max_peak_prominence"] == 4.50
    assert isinstance(telem["is_blocked"], bool)
    assert telem["sample_size"] == 20


def test_reset_functionality():
    guard = Wave463SpectralDensityHFTSignatureGuard()
    t = 500.0
    for i in range(32):
        t += 0.05
        val = 10.0 * math.sin(2.0 * math.pi * 4.0 * (i / 32.0))
        guard.update(value=val, timestamp=t)

    assert guard.is_blocked()

    guard.reset()
    assert not guard.is_blocked()
    assert guard.hf_energy_ratio == 0.0
    assert guard.peak_prominence == 1.0
    assert guard.dominant_frequency == 0.0
    assert guard.block_reason == ""
    assert guard._last_breach_time == -1.0
