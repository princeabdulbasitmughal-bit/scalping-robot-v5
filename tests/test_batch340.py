"""
Batch 340 -- Tests for Wave 431 & Wave 432
==========================================
Wave 431: Liquidity Replenishment Acceleration Decay Guard
Wave 432: Multi-Horizon Volatility Risk Premium Guard

Target: 10+ tests, 100% pass rate
"""

import time
import pytest

from wave431_liquidity_replenishment_acceleration_guard import (
    Wave431LiquidityReplenishmentAccelerationGuard,
)
from wave432_multi_horizon_volatility_risk_premium_guard import (
    Wave432MultiHorizonVolatilityRiskPremiumGuard,
)


class TestWave431ReplenishmentAccelGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave431LiquidityReplenishmentAccelerationGuard(min_acceleration_threshold=10.0)
        with pytest.raises(ValueError):
            Wave431LiquidityReplenishmentAccelerationGuard(critical_floor_threshold=-1.0)
        with pytest.raises(ValueError):
            Wave431LiquidityReplenishmentAccelerationGuard(depth_warning_threshold=5.0, critical_floor_threshold=10.0)

    def test_healthy_steady_replenishment_no_block(self):
        guard = Wave431LiquidityReplenishmentAccelerationGuard(
            min_acceleration_threshold=-100.0, depth_warning_threshold=100.0
        )
        t0 = time.monotonic()
        # Steady replenishment: depth grows smoothly by 5 lots per 0.1s -> velocity = 50, accel = 0
        for i in range(10):
            guard.update(bid_depth=50.0 + i * 2.5, ask_depth=50.0 + i * 2.5, timestamp=t0 + i * 0.1)

        assert not guard.is_blocked()
        assert guard.replenishment_velocity >= 40.0
        assert guard.replenishment_acceleration >= -1.0

    def test_negative_acceleration_collapse_triggers_block(self):
        guard = Wave431LiquidityReplenishmentAccelerationGuard(
            min_acceleration_threshold=-50.0, depth_warning_threshold=100.0, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Step 1: Initial state total 80 lots
        guard.update(bid_depth=40.0, ask_depth=40.0, timestamp=t0)
        # Step 2: Modest replenishment to 85 in 0.1s -> velocity = +50 lots/s
        guard.update(bid_depth=42.5, ask_depth=42.5, timestamp=t0 + 0.1)
        # Step 3: Massive collapse: depth stalls or drops to 70 in 0.1s -> velocity = -150 lots/s
        # Acceleration = (-150 - 50) / 0.1 = -2000 lots/s^2 <= -50.0
        guard.update(bid_depth=35.0, ask_depth=35.0, timestamp=t0 + 0.2)

        assert guard.is_blocked(t0 + 0.2)
        assert guard.last_reason == "REPLENISHMENT_ACCELERATION_COLLAPSE"

    def test_vacuum_liquidity_floor_breach_triggers_block(self):
        guard = Wave431LiquidityReplenishmentAccelerationGuard(
            critical_floor_threshold=15.0, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Total depth 8 < 15.0 floor
        guard.update(bid_depth=4.0, ask_depth=4.0, timestamp=t0)

        assert guard.is_blocked(t0)
        assert guard.last_reason == "VACUUM_LIQUIDITY_FLOOR_BREACH"

    def test_validation_and_reset(self):
        guard = Wave431LiquidityReplenishmentAccelerationGuard()
        t0 = time.monotonic()
        guard.update(-1.0, 50.0, t0)  # negative depth
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.replenishment_velocity == 0.0


class TestWave432MultiHorizonVRPGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave432MultiHorizonVolatilityRiskPremiumGuard(short_window=1)
        with pytest.raises(ValueError):
            Wave432MultiHorizonVolatilityRiskPremiumGuard(short_window=10, medium_window=5)
        with pytest.raises(ValueError):
            Wave432MultiHorizonVolatilityRiskPremiumGuard(max_vrp_ratio=0.5)

    def test_stable_calm_vrp_no_block(self):
        guard = Wave432MultiHorizonVolatilityRiskPremiumGuard(
            short_window=4, medium_window=15, max_vrp_ratio=2.50
        )
        t0 = time.monotonic()
        # Consistent stable tiny variance
        base = 2400.0
        for i in range(25):
            noise = 0.02 if i % 2 == 0 else -0.02
            p = base + noise
            guard.update(bid=p, ask=p + 0.05, timestamp=t0 + i * 0.1)

        assert not guard.is_blocked()
        assert guard.vrp_ratio < 2.0

    def test_explosive_micro_volatility_jump_triggers_block(self):
        guard = Wave432MultiHorizonVolatilityRiskPremiumGuard(
            short_window=4, medium_window=16, max_vrp_ratio=2.20, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # First 16 ticks: ultra-low variance (fluctuating by 0.001)
        base = 2400.0
        for i in range(16):
            p = base + (0.001 if i % 2 == 0 else -0.001)
            guard.update(bid=p, ask=p + 0.02, timestamp=t0 + i * 0.1)

        # Then sudden high variance in short window (fluctuating by 0.50)
        for i in range(16, 22):
            p = base + (0.60 if i % 2 == 0 else -0.60)
            guard.update(bid=p, ask=p + 0.02, timestamp=t0 + i * 0.1)

        assert guard.is_blocked(t0 + 2.2)
        assert guard.last_reason in ["EXPLOSIVE_MICRO_VOLATILITY_JUMP", "VOLATILITY_CEILING_SUPERNOVA"]

    def test_volatility_ceiling_supernova_triggers_block(self):
        guard = Wave432MultiHorizonVolatilityRiskPremiumGuard(
            short_window=3, medium_window=10, critical_vol_ceiling=0.005, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Giant 2% price swings in consecutive ticks
        guard.update(bid=2400.0, ask=2400.1, timestamp=t0)
        guard.update(bid=2450.0, ask=2450.1, timestamp=t0 + 0.1)
        guard.update(bid=2350.0, ask=2350.1, timestamp=t0 + 0.2)
        guard.update(bid=2480.0, ask=2480.1, timestamp=t0 + 0.3)
        guard.update(bid=2340.0, ask=2340.1, timestamp=t0 + 0.4)
        guard.update(bid=2490.0, ask=2490.1, timestamp=t0 + 0.5)
        guard.update(bid=2330.0, ask=2330.1, timestamp=t0 + 0.6)
        guard.update(bid=2500.0, ask=2500.1, timestamp=t0 + 0.7)
        guard.update(bid=2320.0, ask=2320.1, timestamp=t0 + 0.8)
        guard.update(bid=2510.0, ask=2510.1, timestamp=t0 + 0.9)
        guard.update(bid=2310.0, ask=2310.1, timestamp=t0 + 1.0)

        assert guard.is_blocked(t0 + 1.0)
        assert guard.last_reason == "VOLATILITY_CEILING_SUPERNOVA"

    def test_validation_and_reset(self):
        guard = Wave432MultiHorizonVolatilityRiskPremiumGuard()
        t0 = time.monotonic()
        guard.update(2400.0, 2399.0, t0)  # bid > ask
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.vrp_ratio == 1.0
