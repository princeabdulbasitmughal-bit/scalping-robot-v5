"""
Batch 329 -- Tests for Wave 413 & Wave 414
==========================================
Wave 413: Midprice Acceleration Curvature Guard
Wave 414: Hasbrouck Permanent-Transitory Information Share Guard

Target: 10+ tests, 100% pass rate
"""

import time
import pytest

from wave413_midprice_acceleration_curvature_guard import (
    Wave413MidpriceAccelerationCurvatureGuard,
)
from wave414_hasbrouck_information_share_guard import (
    Wave414HasbrouckInformationShareGuard,
)


class TestWave413AccelerationCurvatureGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave413MidpriceAccelerationCurvatureGuard(max_acceleration=-1.0)
        with pytest.raises(ValueError):
            Wave413MidpriceAccelerationCurvatureGuard(max_curvature=0.0)

    def test_linear_constant_velocity_no_block(self):
        guard = Wave413MidpriceAccelerationCurvatureGuard(
            max_acceleration=20.0, max_curvature=15.0
        )
        t0 = time.monotonic()
        # Constant velocity movement: P = 100 + 0.1 * i -> vel = 1.0, accel = 0.0
        for i in range(10):
            p = 100.0 + 0.1 * i
            guard.update(bid=p, ask=p + 0.02, timestamp=t0 + i * 0.1)

        assert not guard.is_blocked()
        assert abs(guard.current_acceleration) < 0.01
        assert abs(guard.current_curvature) < 0.01

    def test_acceleration_spike_triggers_block(self):
        guard = Wave413MidpriceAccelerationCurvatureGuard(
            max_acceleration=25.0, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        guard.update(bid=100.0, ask=100.02, timestamp=t0)
        # vel = (100.01 - 100.0)/0.1 = 0.1
        guard.update(bid=100.01, ask=100.03, timestamp=t0 + 0.1)
        # Sudden huge jump: (105.0 - 100.01)/0.1 = 49.9 -> accel = (49.9 - 0.1)/0.1 = 498 >> 25
        guard.update(bid=105.0, ask=105.02, timestamp=t0 + 0.2)

        assert guard.is_blocked(t0 + 0.2)
        assert guard.last_reason == "MIDPRICE_ACCELERATION_SPIKE"

    def test_validation_and_reset(self):
        guard = Wave413MidpriceAccelerationCurvatureGuard()
        t0 = time.monotonic()
        guard.update(bid=-10.0, ask=10.0, timestamp=t0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""


class TestWave414InformationShareGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave414HasbrouckInformationShareGuard(window_size=3)
        with pytest.raises(ValueError):
            Wave414HasbrouckInformationShareGuard(max_noise_ratio=1.5)
        with pytest.raises(ValueError):
            Wave414HasbrouckInformationShareGuard(min_info_share=-0.1)

    def test_trending_fundamental_flow_high_info_share(self):
        guard = Wave414HasbrouckInformationShareGuard(
            window_size=10, max_noise_ratio=0.70, min_info_share=0.30
        )
        t0 = time.monotonic()
        # Steady permanent price trend with zero negative bounce (gamma_1 >= 0 -> noise = 0)
        p = 100.0
        for i in range(15):
            p += 0.05
            guard.update(bid=p, ask=p + 0.02, timestamp=t0 + i * 0.1)

        assert not guard.is_blocked()
        assert guard.noise_ratio < 0.10
        assert guard.information_share >= 0.90

    def test_transitory_bid_ask_bounce_triggers_noise_dominance(self):
        guard = Wave414HasbrouckInformationShareGuard(
            window_size=10, max_noise_ratio=0.70, min_info_share=0.20, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Pure bid-ask bounce noise: alternating price oscillation with zero net drift
        p = 100.0
        for i in range(15):
            delta = 0.05 if i % 2 == 0 else -0.05
            p += delta
            guard.update(bid=p, ask=p + 0.02, timestamp=t0 + i * 0.1)

        assert guard.is_blocked(t0 + 1.5)
        assert guard.last_reason in [
            "MICROSTRUCTURE_NOISE_DOMINANCE",
            "INFORMATION_SHARE_COLLAPSE",
        ]
        assert guard.noise_ratio >= 0.70

    def test_validation_and_reset(self):
        guard = Wave414HasbrouckInformationShareGuard(window_size=6)
        t0 = time.monotonic()
        guard.update(100.0, 99.0, t0)  # bid > ask
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""
