"""
Batch 338 -- Tests for Wave 428 & Wave 429
==========================================
Wave 428: Price Drift Velocity & Trend Exhaustion Guard
Wave 429: Orderbook Queue Thickness Depletion Half-Life Guard

Target: 10+ tests, 100% pass rate
"""

import time
import pytest

from wave428_price_drift_velocity_exhaustion_guard import (
    Wave428PriceDriftVelocityExhaustionGuard,
)
from wave429_queue_thickness_depletion_half_life_guard import (
    Wave429QueueThicknessDepletionHalfLifeGuard,
)


class TestWave428PriceDriftGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave428PriceDriftVelocityExhaustionGuard(max_drift_velocity=-1.0)
        with pytest.raises(ValueError):
            Wave428PriceDriftVelocityExhaustionGuard(min_exhaustion_accel=0.0)

    def test_moderate_orderly_drift_no_block(self):
        guard = Wave428PriceDriftVelocityExhaustionGuard(
            max_drift_velocity=10.0, min_exhaustion_accel=20.0
        )
        t0 = time.monotonic()
        # Normal steady drift: 0.1 pips per 0.1s -> velocity = 1.0 < 10.0
        for i in range(10):
            p = 100.0 + 0.1 * i
            guard.update(bid=p, ask=p + 0.02, timestamp=t0 + i * 0.1)

        assert not guard.is_blocked()
        assert abs(guard.current_velocity - 1.0) < 0.10

    def test_parabolic_exhaustion_triggers_block(self):
        guard = Wave428PriceDriftVelocityExhaustionGuard(
            max_drift_velocity=8.0, min_exhaustion_accel=15.0, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Step 1: baseline
        guard.update(bid=100.0, ask=100.02, timestamp=t0)
        # Step 2: fast surge (1.0 in 0.1s -> vel = 10.0 > 8.0)
        guard.update(bid=101.0, ask=101.02, timestamp=t0 + 0.1)
        # Step 3: sharp stall / reversal (drops by 0.5 in 0.05s -> vel = -10.0, accel = (-10 - 10)/0.05 = -400)
        guard.update(bid=100.5, ask=100.52, timestamp=t0 + 0.15)

        assert guard.is_blocked(t0 + 0.15)
        assert guard.last_reason == "PARABOLIC_DRIFT_EXHAUSTION"

    def test_validation_and_reset(self):
        guard = Wave428PriceDriftVelocityExhaustionGuard()
        t0 = time.monotonic()
        guard.update(100.0, 99.0, t0)  # bid > ask
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.current_velocity == 0.0


class TestWave429QueueDepletionGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave429QueueThicknessDepletionHalfLifeGuard(min_half_life_sec=-0.01)

    def test_stable_queue_no_block(self):
        guard = Wave429QueueThicknessDepletionHalfLifeGuard(min_half_life_sec=0.08)
        t0 = time.monotonic()
        # Stable thick queue: 100 on bid, 100 on ask (slight gradual changes)
        for i in range(10):
            guard.update(bid_queue=100.0 - i * 0.5, ask_queue=100.0 - i * 0.5, timestamp=t0 + i * 0.1)

        assert not guard.is_blocked()
        assert guard.half_life_sec > 1.0

    def test_rapid_half_life_collapse_triggers_block(self):
        guard = Wave429QueueThicknessDepletionHalfLifeGuard(
            min_half_life_sec=0.10, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        guard.update(bid_queue=100.0, ask_queue=100.0, timestamp=t0)  # Total 200
        # Depth drops from 200 to 100 in 0.04s -> lambda = ln(2) / 0.04 = 17.32 -> t_half = 0.04s <= 0.10s
        guard.update(bid_queue=50.0, ask_queue=50.0, timestamp=t0 + 0.04)

        assert guard.is_blocked(t0 + 0.04)
        assert guard.last_reason in [
            "RAPID_QUEUE_HALF_LIFE_COLLAPSE",
            "VAPORIZING_QUEUE_DEPTH",
        ]
        assert guard.half_life_sec <= 0.06

    def test_vaporizing_queue_depth_triggers_block(self):
        guard = Wave429QueueThicknessDepletionHalfLifeGuard(
            min_half_life_sec=0.01, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        guard.update(bid_queue=100.0, ask_queue=100.0, timestamp=t0)  # Total 200
        # Depth collapses to 20 (< 25% of 200 = 50) in 0.10s
        guard.update(bid_queue=10.0, ask_queue=10.0, timestamp=t0 + 0.10)

        assert guard.is_blocked(t0 + 0.10)
        assert guard.last_reason == "VAPORIZING_QUEUE_DEPTH"

    def test_validation_and_reset(self):
        guard = Wave429QueueThicknessDepletionHalfLifeGuard()
        t0 = time.monotonic()
        guard.update(-10.0, 50.0, t0)  # negative queue
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.half_life_sec == 10.0
