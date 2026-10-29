"""
Batch 335 -- Tests for Wave 423 & Wave 424
==========================================
Wave 423: Realized Tri-Power Quarticity (TPQ) & Vol-of-Vol Guard
Wave 424: Multifractal Hurst Drift & Spectrum Width Guard

Target: 10+ tests, 100% pass rate
"""

import time
import pytest

from wave423_realized_quarticity_guard import (
    Wave423RealizedQuarticityGuard,
)
from wave424_multifractal_hurst_drift_guard import (
    Wave424MultifractalHurstDriftGuard,
)


class TestWave423QuarticityGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave423RealizedQuarticityGuard(window_size=3)
        with pytest.raises(ValueError):
            Wave423RealizedQuarticityGuard(max_tpq_threshold=-1.0)
        with pytest.raises(ValueError):
            Wave423RealizedQuarticityGuard(max_tpq_ratio=0.5)

    def test_calm_diffusion_low_tpq(self):
        guard = Wave423RealizedQuarticityGuard(
            window_size=10, max_tpq_threshold=1e-4, max_tpq_ratio=10.0
        )
        t0 = time.monotonic()
        # Calm steady returns (~0.001)
        p = 100.0
        for i in range(15):
            p += 0.01 if i % 2 == 0 else -0.01
            guard.update(bid=p, ask=p + 0.02, timestamp=t0 + i * 0.1)

        assert not guard.is_blocked()
        assert guard.tpq < 1e-4

    def test_supercritical_tpq_triggers_block(self):
        guard = Wave423RealizedQuarticityGuard(
            window_size=8, max_tpq_threshold=1e-5, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # High volatility series producing large returns (|r| ~ 0.03) -> tpq >> 1e-5
        p = 100.0
        for i in range(10):
            p += 3.0 if i % 2 == 0 else -3.0
            guard.update(bid=p, ask=p + 0.05, timestamp=t0 + i * 0.1)

        assert guard.is_blocked(t0 + 1.0)
        assert guard.last_reason in [
            "SUPERCRITICAL_REALIZED_QUARTICITY",
            "VOL_OF_VOL_TURBULENCE_SPIKE",
        ]
        assert guard.tpq >= 1e-5

    def test_validation_and_reset(self):
        guard = Wave423RealizedQuarticityGuard()
        t0 = time.monotonic()
        guard.update(-10.0, 10.0, t0)  # negative bid
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.tpq == 0.0


class TestWave424MultifractalGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave424MultifractalHurstDriftGuard(window_size=4)
        with pytest.raises(ValueError):
            Wave424MultifractalHurstDriftGuard(max_spectrum_width=1.5)
        with pytest.raises(ValueError):
            Wave424MultifractalHurstDriftGuard(min_h2_roughness=-0.1)

    def test_smooth_monofractal_path_no_block(self):
        guard = Wave424MultifractalHurstDriftGuard(
            window_size=16, max_spectrum_width=0.30
        )
        t0 = time.monotonic()
        # Linear smooth price path where increments scale cleanly
        for i in range(20):
            p = 100.0 + 0.05 * i
            guard.update(bid=p, ask=p + 0.02, timestamp=t0 + i * 0.1)

        assert not guard.is_blocked()
        assert guard.multifractal_width < 0.20

    def test_multifractal_expansion_triggers_block(self):
        guard = Wave424MultifractalHurstDriftGuard(
            window_size=14, max_spectrum_width=0.20, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Highly non-linear multi-scale cascade: alternating micro-fluctuations and macro jumps
        p = 100.0
        pattern = [0.01, -0.01, 0.50, -0.02, 0.01, -0.60, 0.02, -0.01, 0.80, -0.03, 0.01, -0.70, 0.02, 0.01, -0.01]
        for i, delta in enumerate(pattern):
            p += delta
            guard.update(bid=p, ask=p + 0.02, timestamp=t0 + i * 0.1)

        assert guard.is_blocked(t0 + len(pattern)*0.1)
        assert guard.last_reason in [
            "MULTIFRACTAL_SPECTRUM_EXPANSION",
            "MULTISCALE_VOLATILITY_CASCADE",
        ]

    def test_validation_and_reset(self):
        guard = Wave424MultifractalHurstDriftGuard()
        t0 = time.monotonic()
        guard.update(100.0, 99.0, t0)  # bid > ask
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.multifractal_width == 0.0
