"""
Batch 325 -- Tests for Wave 406 & Wave 407
==========================================
Wave 406: Sovereign Liquidity Replenishment Velocity Decay Guard
Wave 407: Volume-Synchronized Probability of Toxicity (VPIN) Acceleration Guard

Target: 12+ tests, 100% pass rate
"""

import time
import pytest

from wave406_liquidity_replenishment_velocity_decay_guard import (
    Wave406LiquidityReplenishmentVelocityDecayGuard,
)
from wave407_vpin_flow_toxicity_acceleration_guard import (
    Wave407VpinFlowToxicityAccelerationGuard,
)


class TestWave406LiquidityReplenishmentGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave406LiquidityReplenishmentVelocityDecayGuard(window_size=2)
        with pytest.raises(ValueError):
            Wave406LiquidityReplenishmentVelocityDecayGuard(depletion_fraction=1.5)
        with pytest.raises(ValueError):
            Wave406LiquidityReplenishmentVelocityDecayGuard(min_velocity_threshold=-1.0)

    def test_normal_replenishment_no_block(self):
        guard = Wave406LiquidityReplenishmentVelocityDecayGuard(
            window_size=5, depletion_fraction=0.30, min_velocity_threshold=10.0, max_latency_sec=2.0
        )
        t0 = time.monotonic()
        # Steady baseline
        guard.update(50.0, 50.0, t0)  # Total 100
        guard.update(50.0, 50.0, t0 + 0.1)

        # Depletion shock (100 -> 60) (40% drop > 30%)
        guard.update(30.0, 30.0, t0 + 0.2)

        # Fast replenishment in 0.1s back to 100 (40 units / 0.1s = 400 > 10)
        guard.update(50.0, 50.0, t0 + 0.3)

        assert not guard.is_blocked()

    def test_slow_velocity_decay_triggers_block(self):
        guard = Wave406LiquidityReplenishmentVelocityDecayGuard(
            window_size=5, depletion_fraction=0.25, min_velocity_threshold=50.0, max_latency_sec=3.0, cooldown_seconds=30.0
        )
        t0 = time.monotonic()
        guard.update(100.0, 100.0, t0)
        # Shock drop: 200 -> 100 (50% drop)
        guard.update(50.0, 50.0, t0 + 0.1)
        # Slow recovery: recovers 100 units over 2.5 seconds (velocity = 100 / 2.5 = 40 < 50)
        guard.update(95.0, 95.0, t0 + 2.6)

        assert guard.is_blocked(t0 + 2.6)
        assert guard.last_reason == "LIQUIDITY_REPLENISHMENT_DECAY"

    def test_latency_spike_triggers_block(self):
        guard = Wave406LiquidityReplenishmentVelocityDecayGuard(
            window_size=5, depletion_fraction=0.25, max_latency_sec=1.0, cooldown_seconds=30.0
        )
        t0 = time.monotonic()
        guard.update(100.0, 100.0, t0)
        # Shock drop: 200 -> 100
        guard.update(50.0, 50.0, t0 + 0.1)
        # Remains depleted for 1.5s (> 1.0s)
        guard.update(50.0, 50.0, t0 + 1.7)

        assert guard.is_blocked(t0 + 1.7)
        assert guard.last_reason == "REPLENISHMENT_LATENCY_SPIKE"

    def test_validation_and_reset(self):
        guard = Wave406LiquidityReplenishmentVelocityDecayGuard(window_size=5)
        t0 = time.monotonic()
        guard.update(-10.0, 50.0, t0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""


class TestWave407VpinGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave407VpinFlowToxicityAccelerationGuard(bucket_size=-5.0)
        with pytest.raises(ValueError):
            Wave407VpinFlowToxicityAccelerationGuard(num_buckets=2)
        with pytest.raises(ValueError):
            Wave407VpinFlowToxicityAccelerationGuard(max_vpin_threshold=1.5)

    def test_balanced_flow_low_vpin(self):
        guard = Wave407VpinFlowToxicityAccelerationGuard(
            bucket_size=50.0, num_buckets=5, max_vpin_threshold=0.60
        )
        t0 = time.monotonic()
        # Balanced alternating trades: buy 25, sell 25 -> imbalance = 0
        for i in range(15):
            guard.update(volume=25.0, is_buy=(i % 2 == 0), timestamp=t0 + i * 0.1)

        assert not guard.is_blocked()
        assert guard.current_vpin < 0.30

    def test_unidirectional_toxic_flow_triggers_high_vpin(self):
        guard = Wave407VpinFlowToxicityAccelerationGuard(
            bucket_size=50.0, num_buckets=4, max_vpin_threshold=0.70, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Strictly buy sweeps (imbalance = 1.0 > 0.70)
        for i in range(8):
            guard.update(volume=50.0, is_buy=True, timestamp=t0 + i * 0.1)

        assert guard.is_blocked(t0 + 1.0)
        assert guard.last_reason == "HIGH_VPIN_TOXIC_FLOW"
        assert guard.current_vpin >= 0.90

    def test_vpin_acceleration_triggers_block(self):
        guard = Wave407VpinFlowToxicityAccelerationGuard(
            bucket_size=50.0, num_buckets=4, max_vpin_threshold=0.90, max_vpin_acceleration=0.20, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # First 4 balanced buckets: VPIN = 0.0
        for i in range(4):
            guard.update(volume=25.0, is_buy=True, timestamp=t0 + i * 0.2)
            guard.update(volume=25.0, is_buy=False, timestamp=t0 + i * 0.2 + 0.05)

        assert guard.current_vpin < 0.10

        # Sudden single massive imbalance bucket (imbalance = 1.0), delta VPIN = 1.0 / 4 = 0.25 >= 0.20
        guard.update(volume=50.0, is_buy=True, timestamp=t0 + 2.0)

        assert guard.is_blocked(t0 + 2.0)
        assert guard.last_reason == "VPIN_RAPID_ACCELERATION"

    def test_validation_and_reset(self):
        guard = Wave407VpinFlowToxicityAccelerationGuard(bucket_size=50.0)
        t0 = time.monotonic()
        guard.update(volume=-10.0, is_buy=True, timestamp=t0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.current_vpin == 0.0
