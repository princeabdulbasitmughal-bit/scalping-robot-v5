"""
Batch 319 -- Tests for Wave 396 and Wave 397
=============================================
Wave 396: Microstructure Burst Kurtosis Guard
Wave 397: Multi-Level Order Book Entropy Drift Guard

Target: 14+ tests, 0 failures
"""

import time
import pytest

from wave396_microstructure_burst_kurtosis_guard import (
    Wave396MicrostructureBurstKurtosisGuard,
)
from wave397_multilevel_lob_entropy_drift_guard import (
    Wave397MultilevelLOBEntropyDriftGuard,
)


class TestWave396BurstKurtosis:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave396MicrostructureBurstKurtosisGuard(window_size=5)
        with pytest.raises(ValueError):
            Wave396MicrostructureBurstKurtosisGuard(kurtosis_threshold=0.5)

    def test_normal_returns_no_block(self):
        guard = Wave396MicrostructureBurstKurtosisGuard(
            window_size=10, kurtosis_threshold=8.0
        )
        t0 = time.monotonic()
        # Small alternating returns
        for i in range(15):
            p = 100.0 + (0.01 if i % 2 == 0 else -0.01)
            guard.update(bid=p, ask=p + 0.1, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_extreme_outlier_triggers_kurtosis_block(self):
        guard = Wave396MicrostructureBurstKurtosisGuard(
            window_size=10, kurtosis_threshold=5.0
        )
        t0 = time.monotonic()
        # 10 baseline steps to fill buffer, then 1 massive 25% jump -> huge kurtosis
        for i in range(10):
            guard.update(bid=100.0 + i * 0.001, ask=100.1 + i * 0.001, timestamp=t0 + i)
        guard.update(bid=125.0, ask=125.1, timestamp=t0 + 10.0)
        assert guard.is_blocked()
        assert guard.last_reason == "SUPERCRITICAL_RETURN_KURTOSIS"

    def test_zero_variance_no_block(self):
        guard = Wave396MicrostructureBurstKurtosisGuard(window_size=10)
        t0 = time.monotonic()
        for i in range(12):
            guard.update(bid=100.0, ask=100.1, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_invalid_input_validation(self):
        guard = Wave396MicrostructureBurstKurtosisGuard()
        guard.update(bid=-10.0, ask=10.0, timestamp=1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_entry_blocked(self):
        guard = Wave396MicrostructureBurstKurtosisGuard()
        guard.update(bid=100.0, ask=100.1, timestamp=5.0)
        guard.update(bid=100.0, ask=100.1, timestamp=4.0)  # non-monotonic
        assert guard.is_blocked()
        assert guard.is_entry_blocked(100.0, 100.1, 6.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""


class TestWave397MultilevelEntropy:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave397MultilevelLOBEntropyDriftGuard(min_normalized_entropy=-0.1)
        with pytest.raises(ValueError):
            Wave397MultilevelLOBEntropyDriftGuard(max_entropy_drift=1.5)

    def test_uniform_depth_no_block(self):
        guard = Wave397MultilevelLOBEntropyDriftGuard(
            min_normalized_entropy=0.30, max_entropy_drift=0.60
        )
        t0 = time.monotonic()
        # Perfectly uniform 5 levels -> maximum entropy = 1.0
        depths = [100.0, 100.0, 100.0, 100.0, 100.0]
        for i in range(5):
            guard.update(depths=depths, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_collapsed_entropy_triggers_block(self):
        guard = Wave397MultilevelLOBEntropyDriftGuard(
            min_normalized_entropy=0.40
        )
        t0 = time.monotonic()
        # 99.9% of volume at 1 level -> entropy near 0
        depths = [10000.0, 0.1, 0.1, 0.1, 0.1]
        guard.update(depths=depths, timestamp=t0)
        assert guard.is_blocked()
        assert guard.last_reason == "LOB_ENTROPY_COLLAPSE"

    def test_extreme_entropy_drift_triggers_block(self):
        guard = Wave397MultilevelLOBEntropyDriftGuard(
            min_normalized_entropy=0.10, max_entropy_drift=0.30
        )
        t0 = time.monotonic()
        # Step 1: uniform
        guard.update(depths=[100.0, 100.0, 100.0, 100.0], timestamp=t0)
        assert not guard.is_blocked()
        # Step 2: sudden shift to asymmetric
        guard.update(depths=[1000.0, 10.0, 10.0, 10.0], timestamp=t0 + 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "LOB_ENTROPY_COLLAPSE"

    def test_invalid_depth_inputs(self):
        guard = Wave397MultilevelLOBEntropyDriftGuard()
        guard.update(depths=[100.0, 100.0], timestamp=1.0)  # only 2 levels (< 3)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(depths=[100.0, -5.0, 10.0], timestamp=1.0)  # negative depth
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_entry_blocked(self):
        guard = Wave397MultilevelLOBEntropyDriftGuard()
        guard.update(depths="bad_input", timestamp=1.0)
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 2.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""
