"""
Batch 346 -- Tests for Wave 441 & Wave 442
==========================================
Wave 441: Realized Microstructural Kernel Volatility Jump Guard
Wave 442: Orderbook Depth Recovery Half-Life Elasticity Guard

Target: 10+ tests, 100% pass rate
"""

import time
import pytest

from wave441_realized_kernel_volatility_jump_guard import (
    Wave441RealizedKernelVolatilityJumpGuard,
)
from wave442_depth_recovery_half_life_guard import (
    Wave442DepthRecoveryHalfLifeGuard,
)


class TestWave441RealizedKernelGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave441RealizedKernelVolatilityJumpGuard(window_size=5, max_lags=4)
        with pytest.raises(ValueError):
            Wave441RealizedKernelVolatilityJumpGuard(max_noise_ratio=-1.0)
        with pytest.raises(ValueError):
            Wave441RealizedKernelVolatilityJumpGuard(critical_kernel_ceiling=0.0)

    def test_healthy_clean_variance_no_block(self):
        guard = Wave441RealizedKernelVolatilityJumpGuard(
            window_size=15, max_lags=3, max_noise_ratio=2.50
        )
        t0 = time.monotonic()
        # Smooth continuous drift without high-frequency bid-ask bounce
        base = 2400.0
        for i in range(20):
            p = base + 0.1 * i
            guard.update(bid=p, ask=p + 0.02, timestamp=t0 + i * 0.1)

        assert not guard.is_blocked()
        assert guard.noise_ratio < 1.0

    def test_noise_contamination_triggers_block(self):
        guard = Wave441RealizedKernelVolatilityJumpGuard(
            window_size=15, max_lags=3, max_noise_ratio=1.20, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Pure 1-tick ping-pong bid-ask bounce: +0.20 then -0.20 every tick
        # This creates massive negative 1st-order autocovariance, making RV >> RK
        base = 2400.0
        for i in range(20):
            p = base + (0.30 if i % 2 == 0 else -0.30)
            guard.update(bid=p, ask=p + 0.02, timestamp=t0 + i * 0.1)

        assert guard.is_blocked(t0 + 2.0)
        assert guard.last_reason == "REALIZED_KERNEL_NOISE_CONTAMINATION"
        assert guard.noise_ratio >= 1.20

    def test_critical_kernel_ceiling_triggers_block(self):
        guard = Wave441RealizedKernelVolatilityJumpGuard(
            window_size=10, max_lags=2, critical_kernel_ceiling=0.010, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Giant persistent trending moves: $10 steps every tick -> sqrt(RK) > 0.010
        base = 2400.0
        for i in range(15):
            p = base + 12.0 * i
            guard.update(bid=p, ask=p + 0.02, timestamp=t0 + i * 0.1)

        assert guard.is_blocked(t0 + 1.5)
        assert guard.last_reason == "KERNEL_VOLATILITY_SUPERNOVA"

    def test_validation_and_reset(self):
        guard = Wave441RealizedKernelVolatilityJumpGuard()
        t0 = time.monotonic()
        guard.update(bid=2400.0, ask=2399.0, timestamp=t0)  # bid > ask
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.noise_ratio == 0.0


class TestWave442DepthHalfLifeGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave442DepthRecoveryHalfLifeGuard(target_equilibrium_depth=40.0, depletion_trigger_depth=50.0)
        with pytest.raises(ValueError):
            Wave442DepthRecoveryHalfLifeGuard(max_half_life_sec=-0.5)

    def test_healthy_fast_half_life_recovery_no_block(self):
        guard = Wave442DepthRecoveryHalfLifeGuard(
            target_equilibrium_depth=100.0, depletion_trigger_depth=50.0, max_half_life_sec=0.50
        )
        t0 = time.monotonic()
        # Depleted to 40 lots
        guard.update(bid_depth=20.0, ask_depth=20.0, timestamp=t0)
        # Fast recovery to 80 lots in 0.08s -> rem_init = 60, rem_curr = 20 -> lambda = ln(3)/0.08 = 13.7 -> t_half = 0.05s < 0.50s
        guard.update(bid_depth=40.0, ask_depth=40.0, timestamp=t0 + 0.08)

        assert not guard.is_blocked()
        assert guard.half_life_sec <= 0.20

    def test_sluggish_recovery_half_life_triggers_block(self):
        guard = Wave442DepthRecoveryHalfLifeGuard(
            target_equilibrium_depth=100.0, depletion_trigger_depth=50.0, max_half_life_sec=0.40, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Depleted to 30 lots
        guard.update(bid_depth=15.0, ask_depth=15.0, timestamp=t0)
        # In 0.50s, depth barely inches up to 32 lots (failing to replenish)
        guard.update(bid_depth=16.0, ask_depth=16.0, timestamp=t0 + 0.50)

        assert guard.is_blocked(t0 + 0.50)
        assert guard.last_reason == "SLUGGISH_DEPTH_RECOVERY_HALF_LIFE"

    def test_emergency_depth_floor_triggers_block(self):
        guard = Wave442DepthRecoveryHalfLifeGuard(critical_floor=12.0, cooldown_seconds=45.0)
        t0 = time.monotonic()
        # Depth drops to 8 < 12.0 floor
        guard.update(bid_depth=4.0, ask_depth=4.0, timestamp=t0)

        assert guard.is_blocked(t0)
        assert guard.last_reason == "EMERGENCY_DEPTH_FLOOR_BREACH"

    def test_validation_and_reset(self):
        guard = Wave442DepthRecoveryHalfLifeGuard()
        t0 = time.monotonic()
        guard.update(-2.0, 50.0, t0)  # negative depth
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.half_life_sec == 0.0
