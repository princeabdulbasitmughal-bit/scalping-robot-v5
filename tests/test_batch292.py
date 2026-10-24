"""
Test Suite Batch 292 -- Wave 346: LOB Spread Elasticity Recovery Latency Guard
"""

import time
import pytest
from wave346_lob_spread_elasticity_recovery_latency_guard import Wave346LOBSpreadElasticityRecoveryLatencyGuard


class TestWave346SpreadElasticityRecoveryLatencyGuard:
    """Comprehensive test suite for Wave 346: LOB Spread Elasticity Recovery Latency Guard."""

    def _make_guard(self, **kwargs):
        defaults = dict(
            baseline_window=8,
            expansion_ratio=2.0,
            max_recovery_latency_sec=0.40,
            cooldown_seconds=45.0,
        )
        defaults.update(kwargs)
        return Wave346LOBSpreadElasticityRecoveryLatencyGuard(**defaults)

    def test_wave346_init_validation(self):
        """Invalid initialization parameters must raise ValueError."""
        with pytest.raises(ValueError):
            Wave346LOBSpreadElasticityRecoveryLatencyGuard(baseline_window=4)
        with pytest.raises(ValueError):
            Wave346LOBSpreadElasticityRecoveryLatencyGuard(expansion_ratio=1.0)
        with pytest.raises(ValueError):
            Wave346LOBSpreadElasticityRecoveryLatencyGuard(max_recovery_latency_sec=0.0)

    def test_wave346_no_block_before_baseline_fills(self):
        """Guard should not block before baseline history fills."""
        guard = self._make_guard(baseline_window=8)
        t0 = time.monotonic()
        for i in range(5):
            guard.update(2400.0, 2400.20, t0 + i * 0.1)
        assert not guard.is_blocked(t0 + 1.0)

    def test_wave346_fast_recovery_no_block(self):
        """Spread shock that contracts back within max_recovery_latency_sec must not block."""
        guard = self._make_guard(baseline_window=8, expansion_ratio=2.0, max_recovery_latency_sec=0.40)
        t0 = time.monotonic()
        # 8 baseline updates with tight 0.20 spread
        for i in range(8):
            guard.update(2400.0, 2400.20, t0 + i * 0.1)

        # Spread shock: expands to 0.60 (3x baseline) at t0 + 0.9s
        t_shock = t0 + 0.9
        guard.update(2400.0, 2400.60, t_shock)

        # Rapid recovery after only 0.20s (elapsed 0.20 < max 0.40s)
        t_rec = t_shock + 0.20
        guard.update(2400.0, 2400.20, t_rec)

        assert not guard.is_blocked(t_rec + 0.1)

    def test_wave346_slow_recovery_triggers_timeout_block(self):
        """Spread shock remaining blown out past max_recovery_latency_sec triggers timeout block."""
        guard = self._make_guard(baseline_window=8, expansion_ratio=2.0, max_recovery_latency_sec=0.40)
        t0 = time.monotonic()
        for i in range(8):
            guard.update(2400.0, 2400.20, t0 + i * 0.1)

        # Spread shock at t0 + 0.9s
        t_shock = t0 + 0.9
        guard.update(2400.0, 2400.60, t_shock)

        # Still blown out at t_shock + 0.45s (0.45s >= 0.40s max latency)
        t_timeout = t_shock + 0.45
        guard.update(2400.0, 2400.65, t_timeout)

        assert guard.is_blocked(t_timeout + 0.05)
        assert guard.last_reason == "SPREAD_ELASTICITY_RECOVERY_TIMEOUT"

    def test_wave346_crossed_quotes_blocks(self):
        """Crossed book (bid >= ask) must trigger CROSSED_QUOTES_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(2400.50, 2400.20, t0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "CROSSED_QUOTES_ERROR"

    def test_wave346_negative_bid_blocks(self):
        """Non-positive bid must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(-1.0, 2400.20, t0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave346_negative_ask_blocks(self):
        """Non-positive ask must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(2400.0, -5.0, t0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave346_bool_inputs_block(self):
        """Boolean inputs must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(True, 2400.20, t0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave346_reset_clears_state(self):
        """Reset must unblock the guard and clear shock timestamp."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(2400.50, 2400.20, t0)
        assert guard.is_blocked(t0 + 0.1)

        guard.reset()
        assert not guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == ""

    def test_wave346_is_entry_blocked_delegation(self):
        """is_entry_blocked delegates to is_blocked with timestamp."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(2400.50, 2400.20, t0)
        assert guard.is_entry_blocked(2400.0, 2400.20, t0 + 0.1)
