"""
Test Batch 358: Wave 465 Queue Imbalance Drift & Wave 466 Spread Widening Guard
================================================================================
Institutional unit test suite verifying Markovian top-of-book queue imbalance drift velocity,
boundary depletion hazard, and dynamic bid-ask spread expansion velocity/acceleration.
"""

import pytest
import math
import numpy as np
from wave465_queue_imbalance_drift_hazard_guard import Wave465QueueImbalanceDriftHazardGuard
from wave466_spread_widening_velocity_acceleration_guard import Wave466SpreadWideningVelocityAccelerationGuard


class TestWave465QueueImbalanceDriftHazardGuard:
    """Test suite for Wave 465: Markovian Queue Imbalance Drift & Replenishment Boundary Hazard Guard."""

    def test_init_validation(self):
        with pytest.raises(ValueError, match="critical_imbalance must be in"):
            Wave465QueueImbalanceDriftHazardGuard(critical_imbalance=0.40)
        with pytest.raises(ValueError, match="critical_imbalance must be in"):
            Wave465QueueImbalanceDriftHazardGuard(critical_imbalance=0.99)

        with pytest.raises(ValueError, match="max_drift_velocity must be > 0.50"):
            Wave465QueueImbalanceDriftHazardGuard(max_drift_velocity=0.30)

        with pytest.raises(ValueError, match="min_queue_size must be >= 1.0"):
            Wave465QueueImbalanceDriftHazardGuard(min_queue_size=0.5)

        with pytest.raises(ValueError, match="cooldown_sec must be >= 0.1"):
            Wave465QueueImbalanceDriftHazardGuard(cooldown_sec=0.05)

    def test_initialization_step(self):
        guard = Wave465QueueImbalanceDriftHazardGuard()
        blocked = guard.update(50.0, 50.0, timestamp=10.0)
        assert not blocked
        assert not guard.is_blocked()
        assert guard.block_reason == "INITIALIZING"

    def test_calm_balanced_queues_no_block(self):
        guard = Wave465QueueImbalanceDriftHazardGuard(critical_imbalance=0.85)

        # Baseline
        guard.update(50.0, 50.0, timestamp=100.0)

        # Calm, symmetric updates
        blocked = guard.update(55.0, 52.0, timestamp=100.5)
        assert not blocked
        assert not guard.is_blocked()
        assert not guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert abs(guard.current_imbalance) < 0.10
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave465QueueImbalanceDriftHazardGuard"

    def test_rapid_drift_towards_ask_depletion_blocks_sell(self):
        guard = Wave465QueueImbalanceDriftHazardGuard(
            critical_imbalance=0.85,
            max_drift_velocity=3.00
        )

        # Baseline: balanced (50 bid, 50 ask -> I = 0)
        guard.update(50.0, 50.0, timestamp=100.0)

        # Sudden sweep: ask drained to 5, bids swell to 95 in dt=0.1s
        # I = (95 - 5) / 100 = 0.90
        # v_I = (0.90 - 0.0) / 0.1 = 9.0 s^-1 > 3.0 s^-1
        blocked = guard.update(95.0, 5.0, timestamp=100.1)
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "SELL" # Ask is depleted, buying pressure -> shorting is toxic
        assert guard.is_entry_blocked("SELL")
        assert not guard.is_entry_blocked("BUY")
        assert "QUEUE_IMBALANCE_RAPID_DRIFT" in guard.block_reason

    def test_rapid_drift_towards_bid_depletion_blocks_buy(self):
        guard = Wave465QueueImbalanceDriftHazardGuard(
            critical_imbalance=0.85,
            max_drift_velocity=3.00
        )

        guard.update(50.0, 50.0, timestamp=100.0)

        # Severe sell sweep: bid drained to 5, ask swells to 95 in dt=0.1s
        # I = -0.90, v_I = -9.0 s^-1
        blocked = guard.update(5.0, 95.0, timestamp=100.1)
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "BUY" # Bid is depleted -> going long is toxic
        assert guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")

    def test_critical_queue_depletion_hazard(self):
        guard = Wave465QueueImbalanceDriftHazardGuard(
            critical_imbalance=0.80,
            min_queue_size=5.0
        )

        # Baseline
        guard.update(100.0, 2.0, timestamp=100.0)
        # Even with zero drift velocity, extreme imbalance + thin queue triggers boundary hazard
        blocked = guard.update(100.0, 2.0, timestamp=101.0)
        assert blocked
        assert guard.is_blocked()
        assert "CRITICAL_QUEUE_DEPLETION_HAZARD" in guard.block_reason

    def test_cooldown_and_reset(self):
        guard = Wave465QueueImbalanceDriftHazardGuard(cooldown_sec=2.0)
        guard.update(50.0, 50.0, timestamp=10.0)
        guard.update(95.0, 5.0, timestamp=10.1)
        assert guard.is_blocked()

        # Update within cooldown
        blocked = guard.update(50.0, 50.0, timestamp=11.0)
        assert blocked
        assert guard.is_blocked()

        # Reset
        guard.reset()
        assert not guard.is_blocked()
        assert guard.current_imbalance == 0.0
        assert guard.block_reason == ""

    def test_input_validation(self):
        guard = Wave465QueueImbalanceDriftHazardGuard()
        with pytest.raises(ValueError, match="must be non-negative"):
            guard.update(-5.0, 50.0, timestamp=10.0)

        with pytest.raises(ValueError, match="timestamp must be strictly monotonic"):
            guard.update(50.0, 50.0, timestamp=10.0)
            guard.update(50.0, 50.0, timestamp=10.0)


class TestWave466SpreadWideningVelocityAccelerationGuard:
    """Test suite for Wave 466: Dynamic Bid-Ask Spread Widening Velocity & Acceleration Guard."""

    def test_init_validation(self):
        with pytest.raises(ValueError, match="baseline_spread_pips must be > 0.1"):
            Wave466SpreadWideningVelocityAccelerationGuard(baseline_spread_pips=0.05)

        with pytest.raises(ValueError, match="max_spread_velocity must be > 1.0"):
            Wave466SpreadWideningVelocityAccelerationGuard(max_spread_velocity=0.5)

        with pytest.raises(ValueError, match="max_spread_acceleration must be > 2.0"):
            Wave466SpreadWideningVelocityAccelerationGuard(max_spread_acceleration=1.0)

        with pytest.raises(ValueError, match="max_absolute_spread_pips must be > baseline_spread_pips"):
            Wave466SpreadWideningVelocityAccelerationGuard(baseline_spread_pips=5.0, max_absolute_spread_pips=4.0)

        with pytest.raises(ValueError, match="cooldown_sec must be >= 0.1"):
            Wave466SpreadWideningVelocityAccelerationGuard(cooldown_sec=0.05)

    def test_initialization_step(self):
        guard = Wave466SpreadWideningVelocityAccelerationGuard()
        blocked = guard.update(2.0, timestamp=10.0)
        assert not blocked
        assert not guard.is_blocked()
        assert guard.block_reason == "INITIALIZING"

    def test_calm_tight_spread_no_block(self):
        guard = Wave466SpreadWideningVelocityAccelerationGuard(baseline_spread_pips=2.0)

        guard.update(2.0, timestamp=100.0)
        blocked = guard.update(2.1, timestamp=100.5)
        assert not blocked
        assert not guard.is_blocked()
        assert not guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert guard.spread_velocity < 1.0
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave466SpreadWideningVelocityAccelerationGuard"

    def test_flash_spread_widening_velocity_triggers_block(self):
        guard = Wave466SpreadWideningVelocityAccelerationGuard(
            baseline_spread_pips=2.0,
            max_spread_velocity=12.0
        )

        guard.update(2.0, timestamp=100.0)

        # Spread widens from 2.0 to 5.0 in dt=0.1s
        # Velocity = (5.0 - 2.0) / 0.1 = 30.0 pips/s > 12.0 pips/s
        # Multiple = 5.0 / 2.0 = 2.5x > 2.0x
        blocked = guard.update(5.0, timestamp=100.1)
        assert blocked
        assert guard.is_blocked()
        assert "SPREAD_EXPLOSION_VELOCITY" in guard.block_reason

    def test_exponential_spread_acceleration_triggers_block(self):
        guard = Wave466SpreadWideningVelocityAccelerationGuard(
            baseline_spread_pips=2.0,
            max_spread_velocity=50.0, # High so acceleration triggers first
            max_spread_acceleration=25.0
        )

        # Step 0: Baseline 2.0
        guard.update(2.0, timestamp=100.0)

        # Step 1: Gentle widen: 2.0 to 2.2 in dt=0.5s -> v = 0.4 pips/s, accel = 0.8
        blocked1 = guard.update(2.2, timestamp=100.5)
        assert not blocked1
        assert not guard.is_blocked()

        # Step 2: Sudden violent acceleration: 2.2 to 4.5 in dt=0.1s
        # v2 = (4.5 - 2.2) / 0.1 = 23.0 pips/s
        # a = (23.0 - 0.4) / 0.1 = 226.0 pips/s^2 > 25.0 pips/s^2
        # Multiple = 4.5 / 2.0 = 2.25x > 1.8x
        blocked2 = guard.update(4.5, timestamp=100.6)
        assert blocked2
        assert guard.is_blocked()
        assert "EXPONENTIAL_SPREAD_ACCELERATION" in guard.block_reason

    def test_hard_spread_ceiling_breach(self):
        guard = Wave466SpreadWideningVelocityAccelerationGuard(
            baseline_spread_pips=2.0,
            max_absolute_spread_pips=8.0
        )

        guard.update(2.0, timestamp=100.0)
        blocked = guard.update(9.5, timestamp=105.0) # 9.5 pips > 8.0 ceiling
        assert blocked
        assert guard.is_blocked()
        assert "HARD_SPREAD_CEILING_BREACH" in guard.block_reason

    def test_cooldown_and_reset(self):
        guard = Wave466SpreadWideningVelocityAccelerationGuard(cooldown_sec=2.0)
        guard.update(2.0, timestamp=10.0)
        guard.update(6.0, timestamp=10.1)
        assert guard.is_blocked()

        # Update within cooldown
        blocked = guard.update(2.0, timestamp=11.0)
        assert blocked
        assert guard.is_blocked()

        # Reset
        guard.reset()
        assert not guard.is_blocked()
        assert guard.current_spread == 0.0
        assert guard.block_reason == ""

    def test_input_validation(self):
        guard = Wave466SpreadWideningVelocityAccelerationGuard()
        with pytest.raises(ValueError, match="spread_pips must be non-negative"):
            guard.update(-1.0, timestamp=10.0)

        with pytest.raises(ValueError, match="timestamp must be strictly monotonic"):
            guard.update(2.0, timestamp=10.0)
            guard.update(2.0, timestamp=10.0)
