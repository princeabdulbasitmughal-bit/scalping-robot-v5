"""
Batch 320 -- Tests for Wave 398 and Wave 399
=============================================
Wave 398: Fractional Brownian Motion Roughness Guard
Wave 399: Limit Order Fill Hazard Guard

Target: 14+ tests, 0 failures
"""

import time
import pytest

from wave398_fbm_roughness_guard import Wave398FBMRoughnessGuard
from wave399_limit_order_fill_hazard_guard import Wave399LimitOrderFillHazardGuard


class TestWave398FBMRoughness:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave398FBMRoughnessGuard(window_size=5)
        with pytest.raises(ValueError):
            Wave398FBMRoughnessGuard(min_hurst=0.8, max_hurst=0.2)

    def test_diffusive_motion_no_block(self):
        guard = Wave398FBMRoughnessGuard(window_size=15, min_hurst=0.10, max_hurst=0.90)
        t0 = time.monotonic()
        # Simulated standard Brownian walk: V(2) ~ 2 * V(1) -> ratio ~ 2 -> H ~ 0.5
        import random
        random.seed(42)
        p = 100.0
        for i in range(25):
            p += random.choice([-0.1, 0.1])
            guard.update(bid=p, ask=p + 0.05, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_ultra_rough_antipersistent_triggers_block(self):
        guard = Wave398FBMRoughnessGuard(window_size=15, min_hurst=0.30, max_hurst=0.80)
        t0 = time.monotonic()
        # Alternating strictly +/- 0.5:
        # delta_1 = +1.0 or -1.0 -> delta_1^2 = 1.0 -> V(1) = 1.0
        # delta_2 = (p_t - p_{t-2}) = 0.0 -> V(2) = 0.0 -> ratio -> 0 -> H -> -inf < min_hurst
        for i in range(20):
            p = 100.0 + (0.5 if i % 2 == 0 else -0.5)
            guard.update(bid=p, ask=p + 0.05, timestamp=t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "ROUGH_VOLATILITY_ANOMALY"

    def test_invalid_input_validation(self):
        guard = Wave398FBMRoughnessGuard()
        guard.update(bid=100.5, ask=100.1, timestamp=1.0)  # bid > ask
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_entry_blocked(self):
        guard = Wave398FBMRoughnessGuard()
        guard.update(bid=100.0, ask=100.1, timestamp=5.0)
        guard.update(bid=100.0, ask=100.1, timestamp=4.0)  # non-monotonic
        assert guard.is_blocked()
        assert guard.is_entry_blocked(100.0, 100.1, 6.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""


class TestWave399LimitOrderFillHazard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave399LimitOrderFillHazardGuard(window_size=2)
        with pytest.raises(ValueError):
            Wave399LimitOrderFillHazardGuard(hazard_threshold=-1.0)

    def test_benign_fills_no_block(self):
        guard = Wave399LimitOrderFillHazardGuard(window_size=5, hazard_threshold=1.0)
        t0 = time.monotonic()
        # Non-adverse fills with long survival time
        for i in range(10):
            guard.update(survival_sec=10.0, is_adverse=False, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_toxic_fills_rapid_hazard_triggers_block(self):
        guard = Wave399LimitOrderFillHazardGuard(window_size=5, hazard_threshold=2.0)
        t0 = time.monotonic()
        # All adverse fills with very short 0.1s survival time:
        # p_adv = 1.0, mean_t = 0.1 -> hazard = 1.0 / 0.1 = 10.0 >= 2.0
        for i in range(5):
            guard.update(survival_sec=0.1, is_adverse=True, timestamp=t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "TOXIC_FILL_HAZARD"

    def test_invalid_input_validation(self):
        guard = Wave399LimitOrderFillHazardGuard()
        guard.update(survival_sec=-5.0, is_adverse=True, timestamp=1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(survival_sec=1.0, is_adverse="yes", timestamp=1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_entry_blocked(self):
        guard = Wave399LimitOrderFillHazardGuard()
        guard.update(survival_sec=True, is_adverse=False, timestamp=1.0)  # bool duration
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 2.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""
