"""
Test Suite Batch 294 -- Wave 348: LOB Depth Slope Gradient Decay Guard
"""

import time
import pytest
from wave348_lob_depth_slope_gradient_decay_guard import Wave348LOBDepthSlopeGradientDecayGuard


class TestWave348DepthSlopeGradientDecayGuard:
    """Comprehensive test suite for Wave 348: LOB Depth Slope Gradient Decay Guard."""

    def _make_guard(self, **kwargs):
        defaults = dict(
            window_size=8,
            min_gradient_threshold=100.0,
            cooldown_seconds=45.0,
        )
        defaults.update(kwargs)
        return Wave348LOBDepthSlopeGradientDecayGuard(**defaults)

    def test_wave348_init_validation(self):
        """Invalid initialization parameters must raise ValueError."""
        with pytest.raises(ValueError):
            Wave348LOBDepthSlopeGradientDecayGuard(window_size=3)
        with pytest.raises(ValueError):
            Wave348LOBDepthSlopeGradientDecayGuard(min_gradient_threshold=0.0)

    def test_wave348_no_block_before_window_fills(self):
        """Guard should not block before window_size observations accumulate."""
        guard = self._make_guard(window_size=8)
        t0 = time.monotonic()
        for i in range(5):
            guard.update(10.0, 20.0, 0.1, t0 + i * 0.1)
        assert not guard.is_blocked(t0 + 1.0)

    def test_wave348_thick_depth_gradient_no_block(self):
        """Thick depth density (G >> min_gradient_threshold) must not block."""
        guard = self._make_guard(window_size=8, min_gradient_threshold=100.0)
        t0 = time.monotonic()
        # q1=50, q2=100, dp=0.1 -> G = 150 / 0.1 = 1500 >> 100
        for i in range(15):
            guard.update(50.0, 100.0, 0.1, t0 + i * 0.1)
        assert not guard.is_blocked(t0 + 2.0)

    def test_wave348_thin_gradient_triggers_decay_block(self):
        """Thin depth density / air pocket (G <= min_gradient_threshold) triggers DEPTH_SLOPE_GRADIENT_DECAY."""
        guard = self._make_guard(window_size=6, min_gradient_threshold=500.0)
        t0 = time.monotonic()
        # q1=1.0, q2=2.0, dp=0.1 -> G = 3.0 / 0.1 = 30.0 <= 500.0
        ts = t0
        for i in range(8):
            ts += 0.1
            guard.update(1.0, 2.0, 0.1, ts)

        assert guard.is_blocked(ts + 0.05)
        assert guard.last_reason == "DEPTH_SLOPE_GRADIENT_DECAY"

    def test_wave348_non_positive_depth_blocks(self):
        """Non-positive depth size must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(-1.0, 10.0, 0.1, t0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave348_non_positive_delta_blocks(self):
        """Non-positive price delta must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(10.0, 10.0, 0.0, t0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave348_bool_inputs_block(self):
        """Boolean inputs must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(True, 10.0, 0.1, t0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave348_reset_clears_state(self):
        """Reset must unblock the guard and clear history."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(-1.0, 10.0, 0.1, t0)
        assert guard.is_blocked(t0 + 0.1)

        guard.reset()
        assert not guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == ""

    def test_wave348_is_entry_blocked_delegation(self):
        """is_entry_blocked delegates to is_blocked with timestamp."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(-1.0, 10.0, 0.1, t0)
        assert guard.is_entry_blocked(2400.0, 2400.20, t0 + 0.1)

    def test_wave348_wide_spread_reduces_gradient(self):
        """Wide price delta flattens the gradient and triggers block."""
        guard = self._make_guard(window_size=5, min_gradient_threshold=200.0)
        t0 = time.monotonic()
        # q1=10, q2=10, dp=1.0 -> G = 20 / 1.0 = 20 <= 200
        ts = t0
        for i in range(6):
            ts += 0.1
            guard.update(10.0, 10.0, 1.0, ts)
        assert guard.is_blocked(ts + 0.05)
        assert guard.last_reason == "DEPTH_SLOPE_GRADIENT_DECAY"
