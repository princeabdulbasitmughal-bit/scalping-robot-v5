"""
Test Batch 353: Wave 455 Multi-Scale Fragility Synthesizer & Wave 456 Jump-Diffusion Hazard Guard
=================================================================================================
Institutional unit test suite verifying multi-scale microstructure fragility synthesis,
threshold bipower variation jump isolation, and jump-diffusion quadratic variation hazard rates.
"""

import pytest
import math
import numpy as np
from wave455_multiscale_fragility_synthesizer_guard import Wave455MultiscaleFragilitySynthesizerGuard
from wave456_jump_diffusion_hazard_guard import Wave456JumpDiffusionHazardGuard


class TestWave455MultiscaleFragilitySynthesizerGuard:
    """Test suite for Wave 455: Multi-Scale Microstructure Fragility Synthesizer Guard."""

    def test_init_invalid_params(self):
        with pytest.raises(ValueError, match="critical_fragility_threshold must be in"):
            Wave455MultiscaleFragilitySynthesizerGuard(critical_fragility_threshold=0.10)

        with pytest.raises(ValueError, match="dual_spike_threshold must be in"):
            Wave455MultiscaleFragilitySynthesizerGuard(dual_spike_threshold=0.40)

    def test_calm_canopy_no_block(self):
        guard = Wave455MultiscaleFragilitySynthesizerGuard(critical_fragility_threshold=0.65)

        # Calm conditions across all 4 components
        guard.update(
            wavelet_hf_energy=0.20,
            poisson_burstiness=0.15,
            curvature_acceleration=0.10,
            volume_divergence=0.15,
            timestamp=100.0
        )

        assert not guard.is_blocked()
        assert not guard.is_entry_blocked("BUY")
        assert guard.composite_fragility < 0.20
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave455MultiscaleFragilitySynthesizerGuard"

    def test_composite_fragility_spike_triggers_block(self):
        guard = Wave455MultiscaleFragilitySynthesizerGuard(critical_fragility_threshold=0.65)

        # High fragility across components: average = 0.70 > 0.65
        guard.update(
            wavelet_hf_energy=0.70,
            poisson_burstiness=0.75,
            curvature_acceleration=0.65,
            volume_divergence=0.70,
            timestamp=100.0
        )

        assert guard.is_blocked()
        assert "MULTISCALE_FRAGILITY_COLLAPSE" in guard.block_reason
        assert guard.composite_fragility >= 0.65

    def test_dual_vector_extreme_convergence_triggers_block(self):
        guard = Wave455MultiscaleFragilitySynthesizerGuard(
            critical_fragility_threshold=0.75,  # High linear threshold
            dual_spike_threshold=0.85
        )

        # 2 vectors breached 0.85 (wavelet=0.95, curvature=0.90), others 0.10
        # Linear composite = 0.25*0.95 + 0.25*0.90 + 0.25*0.10 + 0.25*0.10 = 0.5125 < 0.75
        guard.update(
            wavelet_hf_energy=0.95,
            poisson_burstiness=0.10,
            curvature_acceleration=0.90,
            volume_divergence=0.10,
            timestamp=100.0
        )

        assert guard.is_blocked()
        assert "DUAL_VECTOR_EXTREME_CONVERGENCE" in guard.block_reason
        assert "wavelet_hf_energy" in guard.block_reason
        assert "curvature_acceleration" in guard.block_reason

    def test_monotonic_timestamp_and_reset(self):
        guard = Wave455MultiscaleFragilitySynthesizerGuard()
        with pytest.raises(ValueError, match="must be non-negative and finite"):
            guard.update(-0.1, 0.1, 0.1, 0.1, 100.0)

        guard.update(0.1, 0.1, 0.1, 0.1, 100.0)
        with pytest.raises(ValueError, match="timestamp must be strictly monotonic"):
            guard.update(0.1, 0.1, 0.1, 0.1, 100.0)

        guard.reset()
        assert not guard.is_blocked()
        assert guard.composite_fragility == 0.0


class TestWave456JumpDiffusionHazardGuard:
    """Test suite for Wave 456: Jump-Diffusion Hazard Rate Circuit Breaker Guard."""

    def test_init_invalid_params(self):
        with pytest.raises(ValueError, match="window_size must be >= 15"):
            Wave456JumpDiffusionHazardGuard(window_size=10)

        with pytest.raises(ValueError, match="jump_sigma_multiplier must be >= 1.5"):
            Wave456JumpDiffusionHazardGuard(jump_sigma_multiplier=1.0)

        with pytest.raises(ValueError, match="max_jump_intensity must be > 0.1"):
            Wave456JumpDiffusionHazardGuard(max_jump_intensity=0.05)

        with pytest.raises(ValueError, match="max_jump_variance_ratio must be in"):
            Wave456JumpDiffusionHazardGuard(max_jump_variance_ratio=0.05)

    def test_pure_brownian_diffusion_no_block(self):
        guard = Wave456JumpDiffusionHazardGuard(
            window_size=25,
            jump_sigma_multiplier=3.0,
            max_jump_intensity=4.0,
            max_jump_variance_ratio=0.40,
            min_samples=12
        )

        # Pure Gaussian diffusion with constant sigma = 0.001
        np.random.seed(42)
        t = 10.0
        for i in range(20):
            t += 1.0
            r = float(0.001 * np.random.randn())
            guard.update(r, t)

        assert not guard.is_blocked()
        assert not guard.is_entry_blocked("SELL")
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave456JumpDiffusionHazardGuard"
        assert telem["jump_variance_ratio"] < 0.40

    def test_jump_variance_ratio_triggers_block(self):
        guard = Wave456JumpDiffusionHazardGuard(
            window_size=25,
            jump_sigma_multiplier=2.5,
            max_jump_intensity=10.0,  # High to isolate variance ratio
            max_jump_variance_ratio=0.35,
            min_samples=12
        )

        # Baseline tiny returns r = 0.0002
        t = 10.0
        for i in range(15):
            t += 1.0
            guard.update(0.0002 if i % 2 == 0 else -0.0002, t)

        # Inject 2 massive jumps (r = 0.010, which is 50x baseline)
        # 2 * (0.010)^2 = 0.0002 vs 15 * (0.0002)^2 = 0.0000006 => jumps account for > 99% of variance!
        t += 1.0
        guard.update(0.010, t)
        t += 1.0
        guard.update(-0.010, t)

        assert guard.is_blocked()
        assert "DISCONTINUOUS_JUMP_DOMINANCE" in guard.block_reason
        assert guard.jump_variance_ratio > 0.35

    def test_jump_arrival_hazard_burst_triggers_block(self):
        guard = Wave456JumpDiffusionHazardGuard(
            window_size=25,
            jump_sigma_multiplier=2.5,
            max_jump_intensity=3.0,  # 3 jumps/sec cap
            max_jump_variance_ratio=0.90,  # Valid ceiling
            min_samples=12
        )

        # 12 baseline returns
        t = 10.0
        for i in range(12):
            t += 1.0
            guard.update(0.0003 if i % 2 == 0 else -0.0003, t)

        # Burst of 4 jumps occurring within 0.5s -> intensity = 4 / 0.5 = 8.0 jumps/sec > 3.0!
        for _ in range(4):
            t += 0.1
            guard.update(0.005, t)

        assert guard.is_blocked()
        assert "JUMP_ARRIVAL_HAZARD_BURST" in guard.block_reason
        assert guard.jump_intensity_hz > 3.0

    def test_validation_and_reset(self):
        guard = Wave456JumpDiffusionHazardGuard()
        with pytest.raises(ValueError, match="log_return must be finite"):
            guard.update(float("nan"), 1.0)

        guard.update(0.001, 1.0)
        with pytest.raises(ValueError, match="timestamp must be strictly monotonic"):
            guard.update(0.001, 1.0)

        guard.reset()
        assert not guard.is_blocked()
        assert len(guard._returns) == 0
