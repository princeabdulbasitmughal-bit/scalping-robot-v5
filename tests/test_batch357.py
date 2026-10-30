"""
Test Batch 357: Wave 463 Discrete Fourier Spectral Guard & Wave 464 Liquidity Drain Velocity Guard
===================================================================================================
Institutional unit test suite verifying Fourier spectral density algorithmic pulses,
high-frequency noise energy ratios, and multi-level volumetric liquidity drain velocity vectors.
"""

import pytest
import math
import numpy as np
from wave463_spectral_density_hft_signature_guard import Wave463SpectralDensityHFTSignatureGuard
from wave464_orderbook_liquidity_drain_velocity_guard import Wave464OrderbookLiquidityDrainVelocityGuard


class TestWave463SpectralDensityHFTSignatureGuard:
    """Test suite for Wave 463: Discrete Fourier Spectral Density HFT Signature Guard."""

    def test_init_validation(self):
        with pytest.raises(ValueError, match="window_size must be >= 16"):
            Wave463SpectralDensityHFTSignatureGuard(window_size=10)

        with pytest.raises(ValueError, match="max_hf_energy_ratio must be in"):
            Wave463SpectralDensityHFTSignatureGuard(max_hf_energy_ratio=0.20)
        with pytest.raises(ValueError, match="max_hf_energy_ratio must be in"):
            Wave463SpectralDensityHFTSignatureGuard(max_hf_energy_ratio=0.95)

        with pytest.raises(ValueError, match="max_peak_prominence must be > 1.50"):
            Wave463SpectralDensityHFTSignatureGuard(max_peak_prominence=1.20)

        with pytest.raises(ValueError, match="min_samples must be >= 12"):
            Wave463SpectralDensityHFTSignatureGuard(min_samples=8)

        with pytest.raises(ValueError, match="cooldown_sec must be >= 0.1"):
            Wave463SpectralDensityHFTSignatureGuard(cooldown_sec=0.05)

    def test_insufficient_samples(self):
        guard = Wave463SpectralDensityHFTSignatureGuard(min_samples=14)
        for i in range(10):
            blocked = guard.update(float(i), timestamp=10.0 + i)
            assert not blocked
            assert not guard.is_blocked()
            assert guard.block_reason == "INSUFFICIENT_SAMPLES"

    def test_calm_broadband_noise_no_block(self):
        guard = Wave463SpectralDensityHFTSignatureGuard(
            window_size=32,
            min_samples=16,
            max_peak_prominence=4.50,
            max_hf_energy_ratio=0.70
        )

        # Feed broad-band mild pseudo-random noise
        np.random.seed(42)
        noise = np.random.normal(0.0, 1.0, size=32)
        for i, val in enumerate(noise):
            guard.update(float(val), timestamp=100.0 + i * 0.1)

        assert not guard.is_blocked()
        assert not guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert guard.peak_prominence < 4.0
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave463SpectralDensityHFTSignatureGuard"

    def test_periodic_algorithmic_pulse_triggers_block(self):
        guard = Wave463SpectralDensityHFTSignatureGuard(
            window_size=32,
            min_samples=20,
            max_peak_prominence=3.50
        )

        # Pure sinusoidal pulse: 4 ticks per cycle (frequency = 0.25 cycles/sample)
        # S(f) forms a massive delta peak
        for i in range(25):
            val = math.sin(2.0 * math.pi * 0.25 * i)
            guard.update(val, timestamp=100.0 + i * 0.05)

        assert guard.is_blocked()
        assert guard.is_entry_blocked("BUY")
        assert guard.is_entry_blocked("SELL")
        assert "HFT_PERIODIC_SPECTRAL_PULSE" in guard.block_reason
        assert guard.peak_prominence > 3.50

    def test_hf_noise_energy_dominance(self):
        guard = Wave463SpectralDensityHFTSignatureGuard(
            window_size=32,
            min_samples=20,
            max_hf_energy_ratio=0.65,
            max_peak_prominence=20.0 # High so hf_dominance triggers
        )

        # High frequency alternating signal (+1, -1, +1, -1) sitting at Nyquist frequency (f = 0.50)
        for i in range(25):
            val = 1.0 if i % 2 == 0 else -1.0
            guard.update(val, timestamp=200.0 + i * 0.05)

        assert guard.is_blocked()
        assert "HF_NOISE_ENERGY_DOMINANCE" in guard.block_reason
        assert guard.hf_energy_ratio > 0.80

    def test_cooldown_and_reset(self):
        guard = Wave463SpectralDensityHFTSignatureGuard(
            window_size=32,
            min_samples=16,
            max_peak_prominence=3.0,
            cooldown_sec=2.0
        )
        for i in range(20):
            val = math.sin(2.0 * math.pi * 0.25 * i)
            guard.update(val, timestamp=10.0 + i * 0.05)
        assert guard.is_blocked()

        # Update within cooldown
        blocked = guard.update(0.0, timestamp=15.0)
        assert blocked
        assert guard.is_blocked()

        # Reset
        guard.reset()
        assert not guard.is_blocked()
        assert guard.hf_energy_ratio == 0.0
        assert guard.peak_prominence == 1.0
        assert guard.block_reason == ""

    def test_input_validation(self):
        guard = Wave463SpectralDensityHFTSignatureGuard()
        with pytest.raises(ValueError, match="value must be finite"):
            guard.update(float("nan"), timestamp=10.0)

        with pytest.raises(ValueError, match="timestamp must be strictly monotonic"):
            guard.update(1.0, timestamp=10.0)
            guard.update(1.0, timestamp=10.0)


class TestWave464OrderbookLiquidityDrainVelocityGuard:
    """Test suite for Wave 464: Multi-Level Volumetric Liquidity Drain Velocity Guard."""

    def test_init_validation(self):
        with pytest.raises(ValueError, match="max_drain_velocity must be > 0.50"):
            Wave464OrderbookLiquidityDrainVelocityGuard(max_drain_velocity=0.30)

        with pytest.raises(ValueError, match="max_drain_acceleration must be > 0.50"):
            Wave464OrderbookLiquidityDrainVelocityGuard(max_drain_acceleration=0.20)

        with pytest.raises(ValueError, match="cooldown_sec must be >= 0.1"):
            Wave464OrderbookLiquidityDrainVelocityGuard(cooldown_sec=0.05)

    def test_initialization_step(self):
        guard = Wave464OrderbookLiquidityDrainVelocityGuard()
        depths = [100.0, 200.0, 300.0, 400.0, 500.0]
        blocked = guard.update(depths, timestamp=10.0)
        assert not blocked
        assert not guard.is_blocked()
        assert guard.block_reason == "INITIALIZING"

    def test_calm_stable_depth_no_block(self):
        guard = Wave464OrderbookLiquidityDrainVelocityGuard(max_drain_velocity=2.20)

        # Initial snapshot
        guard.update([100.0, 200.0, 300.0, 400.0, 500.0], timestamp=100.0)

        # Depth slightly increases or fluctuates mildly (replenishment)
        blocked = guard.update([105.0, 210.0, 298.0, 405.0, 502.0], timestamp=100.5)
        assert not blocked
        assert not guard.is_blocked()
        assert not guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert guard.drain_velocity < 0.10
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave464OrderbookLiquidityDrainVelocityGuard"

    def test_flash_liquidity_evacuation_triggers_block(self):
        guard = Wave464OrderbookLiquidityDrainVelocityGuard(max_drain_velocity=2.20)

        # Initial depth: 100 on tier 1, 200 on tier 2, etc.
        guard.update([100.0, 200.0, 300.0, 400.0, 500.0], timestamp=100.0)

        # Sudden flash drain across top tiers: T1 drops from 100 to 20, T2 from 200 to 50 in dt=0.1s
        # T1 evacuation = (100 - 20) / 0.1 = 800 / 100 = 8.0 s^-1
        # Weighted drain velocity easily exceeds 2.20 s^-1
        blocked = guard.update([20.0, 50.0, 100.0, 200.0, 300.0], timestamp=100.1)
        assert blocked
        assert guard.is_blocked()
        assert "FLASH_LIQUIDITY_EVACUATION" in guard.block_reason
        assert guard.drain_velocity > 2.20

    def test_exponential_drain_acceleration_triggers_block(self):
        guard = Wave464OrderbookLiquidityDrainVelocityGuard(
            max_drain_velocity=10.0, # High so acceleration triggers
            max_drain_acceleration=3.50
        )

        # Step 0: Baseline
        guard.update([100.0, 100.0, 100.0, 100.0, 100.0], timestamp=100.0)

        # Step 1: Gentle mild drain (drop from 100 to 98 in dt=0.5s -> low accel 0.08/s^2)
        blocked1 = guard.update([98.0, 98.0, 98.0, 98.0, 98.0], timestamp=100.5)
        assert not blocked1
        assert not guard.is_blocked()

        # Step 2: Severe acceleration in drain: drops from 98 to 40 in dt=0.1s
        # Accel = 58.78/s^2 > 3.50/s^2 and velocity = 5.92/s > 1.20/s
        blocked2 = guard.update([40.0, 40.0, 40.0, 40.0, 40.0], timestamp=100.6)
        assert blocked2
        assert guard.is_blocked()
        assert "EXPONENTIAL_DRAIN_ACCELERATION" in guard.block_reason

    def test_cooldown_and_reset(self):
        guard = Wave464OrderbookLiquidityDrainVelocityGuard(max_drain_velocity=2.0, cooldown_sec=2.0)
        guard.update([100.0, 100.0, 100.0, 100.0, 100.0], timestamp=10.0)
        guard.update([10.0, 10.0, 10.0, 10.0, 10.0], timestamp=10.1)
        assert guard.is_blocked()

        # Update within cooldown
        blocked = guard.update([100.0, 100.0, 100.0, 100.0, 100.0], timestamp=11.0)
        assert blocked
        assert guard.is_blocked()

        # Reset
        guard.reset()
        assert not guard.is_blocked()
        assert guard.drain_velocity == 0.0
        assert guard.block_reason == ""

    def test_input_validation(self):
        guard = Wave464OrderbookLiquidityDrainVelocityGuard()
        with pytest.raises(ValueError, match="at least 5 levels"):
            guard.update([100.0, 100.0, 100.0], timestamp=10.0)

        with pytest.raises(ValueError, match="non-negative and finite"):
            guard.update([-10.0, 100.0, 100.0, 100.0, 100.0], timestamp=10.0)

        with pytest.raises(ValueError, match="timestamp must be strictly monotonic"):
            guard.update([100.0, 100.0, 100.0, 100.0, 100.0], timestamp=10.0)
            guard.update([100.0, 100.0, 100.0, 100.0, 100.0], timestamp=10.0)
