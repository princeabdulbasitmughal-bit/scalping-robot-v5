"""
Test Suite Batch 289 -- Wave 343: Trade Flow Volume Clock Jump-Diffusion Guard
"""

import time
import pytest
from wave343_trade_flow_volume_clock_jump_diffusion_guard import Wave343TradeFlowVolumeClockJumpDiffusionGuard


class TestWave343VolumeClockJumpDiffusionGuard:
    """Comprehensive test suite for Wave 343: Volume Clock Jump-Diffusion Guard."""

    def _make_guard(self, **kwargs):
        defaults = dict(
            bucket_volume=20.0,
            window_buckets=6,
            jump_ratio_threshold=0.60,
            cooldown_seconds=45.0,
        )
        defaults.update(kwargs)
        return Wave343TradeFlowVolumeClockJumpDiffusionGuard(**defaults)

    def test_wave343_init_validation(self):
        """Invalid initialization parameters must raise ValueError."""
        with pytest.raises(ValueError):
            Wave343TradeFlowVolumeClockJumpDiffusionGuard(bucket_volume=0.0)
        with pytest.raises(ValueError):
            Wave343TradeFlowVolumeClockJumpDiffusionGuard(window_buckets=3)
        with pytest.raises(ValueError):
            Wave343TradeFlowVolumeClockJumpDiffusionGuard(jump_ratio_threshold=1.5)

    def test_wave343_no_block_before_window_fills(self):
        """Guard should not block before window_buckets have accumulated."""
        guard = self._make_guard(bucket_volume=10.0, window_buckets=6)
        t0 = time.monotonic()
        # Only 3 buckets completed
        for i in range(3):
            guard.update(2400.0 + i * 0.1, 10.0, t0 + i * 0.1)
        assert not guard.is_blocked(t0 + 1.0)

    def test_wave343_continuous_diffusion_no_block(self):
        """Steady continuous diffusion with regular symmetric returns should not trigger jump block."""
        guard = self._make_guard(bucket_volume=10.0, window_buckets=6, jump_ratio_threshold=0.60)
        t0 = time.monotonic()
        p = 2400.0
        # Continuous smooth increments: BPV closely tracks RV, jump component is near 0
        for i in range(15):
            p += 0.05 if i % 2 == 0 else -0.05
            guard.update(p, 10.0, t0 + i * 0.1)
        assert not guard.is_blocked(t0 + 2.0)

    def test_wave343_jump_diffusion_triggers_block(self):
        """Discontinuous isolated price shock amidst tiny noise should trigger VOLUME_CLOCK_JUMP_DIFFUSION."""
        guard = self._make_guard(bucket_volume=10.0, window_buckets=6, jump_ratio_threshold=0.50)
        t0 = time.monotonic()
        # 6 buckets of near-zero noise
        for i in range(6):
            guard.update(2400.0 + (i % 2) * 0.001, 10.0, t0 + i * 0.1)

        # 7th bucket has massive isolated jump blowout: 2400 -> 2450 (+50.0)
        t_jump = t0 + 0.8
        guard.update(2450.0, 10.0, t_jump)

        assert guard.is_blocked(t_jump + 0.05)
        assert guard.last_reason == "VOLUME_CLOCK_JUMP_DIFFUSION"

    def test_wave343_negative_price_blocks(self):
        """Non-positive price must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(-2400.0, 10.0, t0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave343_zero_volume_blocks(self):
        """Non-positive volume must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(2400.0, 0.0, t0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave343_bool_inputs_block(self):
        """Boolean inputs must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(True, 10.0, t0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave343_reset_clears_state(self):
        """Reset must clear bucket accumulator, history, and block status."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(-2400.0, 10.0, t0)  # error
        assert guard.is_blocked(t0 + 0.1)

        guard.reset()
        assert not guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == ""

    def test_wave343_is_entry_blocked_delegation(self):
        """is_entry_blocked delegates to is_blocked with timestamp."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(-2400.0, 10.0, t0)
        assert guard.is_entry_blocked(2400.0, 2400.20, t0 + 0.1)

    def test_wave343_fractional_volume_accumulation(self):
        """Guard should correctly aggregate fractional trade volume across multiple ticks."""
        guard = self._make_guard(bucket_volume=10.0, window_buckets=5)
        t0 = time.monotonic()
        # 10 ticks of 1.0 vol each = 1 full bucket of 10.0 vol
        for i in range(10):
            guard.update(2400.0, 1.0, t0 + i * 0.01)
        assert len(guard._bucket_returns) == 1
