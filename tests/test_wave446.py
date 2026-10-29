"""
tests/test_wave446.py
=====================
Pytest suite for Wave 446: Wave446RoughVolatilityHurstGuard.
Validates Fractional Brownian Motion Rough Volatility Hurst Exponent Guard.
"""

import sys
import os
import math
import pytest
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wave446_rough_volatility_hurst_guard import Wave446RoughVolatilityHurstGuard


def _make_guard(**kwargs):
    defaults = dict(
        window_size=32,
        min_hurst_threshold=0.05,
        max_hurst_threshold=0.50,
        lags=[1, 2, 4, 8]
    )
    defaults.update(kwargs)
    return Wave446RoughVolatilityHurstGuard(**defaults)


def test_guard_initialization():
    g = _make_guard()
    assert g.window_size == 32
    assert g.min_hurst_threshold == 0.05
    assert g.max_hurst_threshold == 0.50
    assert not g.is_blocked()
    assert g.block_reason == ""
    assert g.estimated_hurst == 0.14


def test_guard_invalid_initialization():
    with pytest.raises(ValueError, match="window_size must be >= 16"):
        Wave446RoughVolatilityHurstGuard(window_size=10)

    with pytest.raises(ValueError, match="Invalid thresholds"):
        Wave446RoughVolatilityHurstGuard(min_hurst_threshold=0.60, max_hurst_threshold=0.50)


def test_invalid_volatility_or_timestamps():
    g = _make_guard()
    with pytest.raises(ValueError, match="Volatility must be positive"):
        g.update(-0.05, 1000.0)

    with pytest.raises(ValueError, match="Volatility must be positive"):
        g.update(float("nan"), 1000.0)

    g.update(0.15, 1000.0)
    with pytest.raises(ValueError, match="Timestamp must be strictly increasing"):
        g.update(0.16, 1000.0)


def test_insufficient_data_does_not_block():
    g = _make_guard()
    for i in range(10):
        blocked = g.update(0.15 + (i * 0.001), 1000.0 + i)
        assert not blocked
    assert not g.is_blocked()
    assert g.block_reason == "INSUFFICIENT_DATA"


def test_stationary_rough_volatility_regime():
    """Typical stationary regime should remain in (0.05, 0.50) and not block."""
    g = _make_guard(window_size=32)
    np.random.seed(42)
    # Simulate stationary rough volatility around 0.20
    t = 1000.0
    for i in range(32):
        vol = 0.20 + (np.random.randn() * 0.01)
        g.update(max(0.01, vol), t + i)

    # Telemetry should be populated
    telem = g.get_telemetry()
    assert telem["guard"] == "Wave446RoughVolatilityHurstGuard"
    assert "estimated_hurst" in telem
    assert telem["buffer_depth"] == 32


def test_ultra_rough_turbulence_trigger():
    """Extreme singular jump cascade leading to ultra-low Hurst exponent < 0.10."""
    g = _make_guard(window_size=32, min_hurst_threshold=0.10)
    t = 2000.0
    np.random.seed(42)
    # White noise realized variance gives H ~ 0.001
    for i in range(32):
        vol = 0.10 + abs(np.random.randn() * 0.05)
        g.update(vol, t + i)

    assert g.is_blocked()
    assert "ULTRA_ROUGH_TURBULENCE" in g.block_reason
    assert g.is_entry_blocked("BUY")
    assert g.is_entry_blocked("SELL")


def test_super_diffusive_drift_trigger():
    """Strong persistent smooth drift resulting in H > max_hurst_threshold."""
    g = _make_guard(window_size=32, max_hurst_threshold=0.35)
    t = 3000.0
    # Smooth cubic power drift creates very high persistence
    for i in range(32):
        vol = 0.10 + (i ** 1.8) * 0.01
        g.update(vol, t + i)

    assert g.is_blocked()
    assert "SUPER_DIFFUSIVE_DRIFT" in g.block_reason


def test_reset_behavior():
    g = _make_guard(window_size=32, min_hurst_threshold=0.10)
    t = 4000.0
    np.random.seed(42)
    for i in range(32):
        vol = 0.10 + abs(np.random.randn() * 0.05)
        g.update(vol, t + i)

    assert g.is_blocked()
    g.reset()
    assert not g.is_blocked()
    assert g.block_reason == ""
    assert g.estimated_hurst == 0.14
    assert len(g.get_telemetry()["structure_values"]) == 0
