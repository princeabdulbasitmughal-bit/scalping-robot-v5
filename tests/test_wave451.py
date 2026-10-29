"""
tests/test_wave451.py
=====================
Pytest suite for Wave 451: Wave451WaveletVarianceDecompositionGuard.
Validates Multi-Scale Wavelet Variance Decomposition Guard (MODWT Haar).
"""

import sys
import os
import pytest
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wave451_wavelet_variance_decomposition_guard import Wave451WaveletVarianceDecompositionGuard


def _make_guard(**kwargs):
    defaults = dict(
        window_size=32,
        max_hf_energy_ratio=0.65,
        min_samples=16
    )
    defaults.update(kwargs)
    return Wave451WaveletVarianceDecompositionGuard(**defaults)


def test_guard_initialization():
    g = _make_guard()
    assert g.window_size == 32
    assert g.max_hf_energy_ratio == 0.65
    assert not g.is_blocked()
    assert g.block_reason == ""
    assert g.hf_energy_ratio == 0.0


def test_guard_invalid_initialization():
    with pytest.raises(ValueError, match="window_size must be >= 16"):
        Wave451WaveletVarianceDecompositionGuard(window_size=10)

    with pytest.raises(ValueError, match="max_hf_energy_ratio must be in"):
        Wave451WaveletVarianceDecompositionGuard(max_hf_energy_ratio=0.20)


def test_invalid_return_or_timestamp():
    g = _make_guard()
    with pytest.raises(ValueError, match="log_return must be finite"):
        g.update(float("inf"), 100.0)

    g.update(0.001, 100.0)
    with pytest.raises(ValueError, match="timestamp must be strictly monotonic"):
        g.update(0.002, 100.0)


def test_insufficient_sample_does_not_block():
    g = _make_guard(min_samples=16)
    for i in range(15):
        blocked = g.update(0.001, 100.0 + i)
        assert not blocked
    assert not g.is_blocked()
    assert g.block_reason == "INSUFFICIENT_SAMPLE"


def test_trending_market_low_hf_energy_no_block():
    """Smooth directional return sequence should concentrate variance in scale 2 & 3, not scale 1."""
    g = _make_guard(window_size=32, max_hf_energy_ratio=0.65)
    t = 1000.0
    # Smooth slow-moving sinusoidal trend has low HF noise
    for i in range(32):
        ret = 0.002 * np.sin(i * 0.2)
        g.update(ret, t + i)

    assert not g.is_blocked()
    assert g.hf_energy_ratio <= 0.65
    telem = g.get_telemetry()
    assert telem["guard"] == "Wave451WaveletVarianceDecompositionGuard"
    assert "scale_1" in telem["scale_variances"]
    assert telem["sample_size"] == 32


def test_noise_dominated_microstructure_blocks():
    """Rapid alternating bid-ask bounce (+1 tick, -1 tick) concentrates energy at scale 1."""
    g = _make_guard(window_size=32, max_hf_energy_ratio=0.60)
    t = 2000.0
    # Rapid pure high-frequency oscillation: +0.005, -0.005, +0.005, -0.005...
    for i in range(32):
        ret = 0.005 if i % 2 == 0 else -0.005
        g.update(ret, t + i)

    assert g.is_blocked()
    assert "NOISE_DOMINATED_MICROSTRUCTURE" in g.block_reason
    assert g.hf_energy_ratio > 0.60
    assert g.is_entry_blocked("BUY")
    assert g.is_entry_blocked("SELL")


def test_reset_behavior():
    g = _make_guard(window_size=32, max_hf_energy_ratio=0.60)
    t = 3000.0
    for i in range(32):
        ret = 0.005 if i % 2 == 0 else -0.005
        g.update(ret, t + i)

    assert g.is_blocked()
    g.reset()
    assert not g.is_blocked()
    assert g.block_reason == ""
    assert g.hf_energy_ratio == 0.0
    assert len(g._returns) == 0
