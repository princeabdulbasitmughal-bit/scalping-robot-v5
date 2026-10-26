"""
Batch 318 -- Tests for Wave 394 and Wave 395
=============================================
Wave 394: Cross-Impact Queue Disbalance Guard
Wave 395: Non-Linear Midprice Acceleration Guard

Target: 14+ tests, 0 failures
"""

import time
import pytest

from wave394_cross_impact_queue_disbalance_guard import (
    Wave394CrossImpactQueueDisbalanceGuard,
)
from wave395_nonlinear_midprice_acceleration_guard import (
    Wave395NonlinearMidpriceAccelerationGuard,
)


class TestWave394QueueDisbalance:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave394CrossImpactQueueDisbalanceGuard(window_size=2)
        with pytest.raises(ValueError):
            Wave394CrossImpactQueueDisbalanceGuard(high_ratio_threshold=0.2, low_ratio_threshold=0.8)

    def test_balanced_queues_no_block(self):
        guard = Wave394CrossImpactQueueDisbalanceGuard(
            window_size=10, high_ratio_threshold=0.85, low_ratio_threshold=0.15
        )
        t0 = time.monotonic()
        for i in range(15):
            guard.update(bid_queue=100.0, ask_queue=100.0, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_high_bid_asymmetry_triggers_block(self):
        guard = Wave394CrossImpactQueueDisbalanceGuard(
            window_size=5, high_ratio_threshold=0.80, low_ratio_threshold=0.20
        )
        t0 = time.monotonic()
        for i in range(5):
            guard.update(bid_queue=900.0, ask_queue=100.0, timestamp=t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "EXTREME_QUEUE_ASYMMETRY"

    def test_low_bid_asymmetry_triggers_block(self):
        guard = Wave394CrossImpactQueueDisbalanceGuard(
            window_size=5, high_ratio_threshold=0.80, low_ratio_threshold=0.20
        )
        t0 = time.monotonic()
        for i in range(5):
            guard.update(bid_queue=100.0, ask_queue=900.0, timestamp=t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "EXTREME_QUEUE_ASYMMETRY"

    def test_invalid_input_validation(self):
        guard = Wave394CrossImpactQueueDisbalanceGuard()
        guard.update(-10.0, 100.0, 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(0.0, 0.0, 1.0)  # zero total depth
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_entry_blocked(self):
        guard = Wave394CrossImpactQueueDisbalanceGuard()
        guard.update(True, 100.0, 1.0)  # boolean check
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 1.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""


class TestWave395MidpriceAcceleration:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave395NonlinearMidpriceAccelerationGuard(acceleration_threshold=-1.0)
        with pytest.raises(ValueError):
            Wave395NonlinearMidpriceAccelerationGuard(cooldown_seconds=0.0)

    def test_constant_velocity_no_block(self):
        guard = Wave395NonlinearMidpriceAccelerationGuard(acceleration_threshold=10.0)
        t0 = time.monotonic()
        # Price increases by 1.0 every second -> velocity = 1.0 -> acceleration = 0.0
        for i in range(5):
            guard.update(bid=100.0 + i, ask=100.2 + i, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_supercritical_acceleration_triggers_block(self):
        guard = Wave395NonlinearMidpriceAccelerationGuard(acceleration_threshold=20.0)
        t0 = time.monotonic()
        # t0: mid = 100.0
        guard.update(bid=99.9, ask=100.1, timestamp=t0)
        # t1: mid = 101.0 -> velocity = 1.0
        guard.update(bid=100.9, ask=101.1, timestamp=t0 + 1.0)
        # t2: mid = 150.0 -> velocity = 49.0 -> accel = (49 - 1) / 1 = 48.0 >= 20.0
        guard.update(bid=149.9, ask=150.1, timestamp=t0 + 2.0)
        assert guard.is_blocked()
        assert guard.last_reason == "MIDPRICE_SUPERCRITICAL_ACCELERATION"

    def test_invalid_price_spread_validation(self):
        guard = Wave395NonlinearMidpriceAccelerationGuard()
        # bid >= ask
        guard.update(bid=100.5, ask=100.2, timestamp=1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_non_monotonic_timestamp(self):
        guard = Wave395NonlinearMidpriceAccelerationGuard()
        guard.update(bid=100.0, ask=100.2, timestamp=10.0)
        guard.update(bid=100.1, ask=100.3, timestamp=9.0)  # backwards time
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_entry_blocked(self):
        guard = Wave395NonlinearMidpriceAccelerationGuard()
        guard.update(bid=100.0, ask=100.2, timestamp=1.0)
        guard.update(bid=100.0, ask=100.2, timestamp=1.0)  # dt = 0
        assert guard.is_blocked()
        assert guard.is_entry_blocked(100.0, 100.2, 2.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""
