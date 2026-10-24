"""
Test Suite Batch 291 -- Wave 345: Trade Size Pareto Alpha Decay Guard
"""

import time
import pytest
from wave345_trade_size_pareto_alpha_decay_guard import Wave345TradeSizeParetoAlphaDecayGuard


class TestWave345ParetoAlphaDecayGuard:
    """Comprehensive test suite for Wave 345: Trade Size Pareto Alpha Decay Guard."""

    def _make_guard(self, **kwargs):
        defaults = dict(
            window_size=15,
            top_k=4,
            alpha_decay_threshold=1.20,
            cooldown_seconds=45.0,
        )
        defaults.update(kwargs)
        return Wave345TradeSizeParetoAlphaDecayGuard(**defaults)

    def test_wave345_init_validation(self):
        """Invalid initialization parameters must raise ValueError."""
        with pytest.raises(ValueError):
            Wave345TradeSizeParetoAlphaDecayGuard(window_size=5)
        with pytest.raises(ValueError):
            Wave345TradeSizeParetoAlphaDecayGuard(window_size=15, top_k=15)
        with pytest.raises(ValueError):
            Wave345TradeSizeParetoAlphaDecayGuard(alpha_decay_threshold=0.0)

    def test_wave345_no_block_before_window_fills(self):
        """Guard should not block before window_size trades accumulate."""
        guard = self._make_guard(window_size=12)
        t0 = time.monotonic()
        for i in range(8):
            guard.update(1.0, t0 + i * 0.1)
        assert not guard.is_blocked(t0 + 1.0)

    def test_wave345_normal_small_sizes_no_block(self):
        """Evenly distributed small retail sizes have high Pareto alpha and must not block."""
        guard = self._make_guard(window_size=15, top_k=4, alpha_decay_threshold=1.20)
        t0 = time.monotonic()
        # Sizes between 1.0 and 2.0: ratio of top sizes to threshold is very small -> alpha is large
        for i in range(25):
            guard.update(1.0 + (i % 5) * 0.1, t0 + i * 0.1)
        assert not guard.is_blocked(t0 + 3.0)

    def test_wave345_whale_block_sizes_triggers_decay_block(self):
        """Massive whale block trades (extreme Pareto fat tail) must trigger PARETO_ALPHA_DECAY."""
        guard = self._make_guard(window_size=15, top_k=4, alpha_decay_threshold=1.50)
        t0 = time.monotonic()
        # 11 baseline retail trades of 1 lot
        for i in range(11):
            guard.update(1.0, t0 + i * 0.1)

        # 4 massive institutional block trades (100, 250, 500, 1000 lots)
        whale_sizes = [100.0, 250.0, 500.0, 1000.0]
        ts = t0 + 1.2
        for sz in whale_sizes:
            ts += 0.05
            guard.update(sz, ts)

        assert guard.is_blocked(ts + 0.05)
        assert guard.last_reason == "PARETO_ALPHA_DECAY"

    def test_wave345_negative_size_blocks(self):
        """Non-positive trade size must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(-1.0, t0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave345_zero_size_blocks(self):
        """Zero trade size must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(0.0, t0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave345_bool_inputs_block(self):
        """Boolean inputs must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(True, t0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave345_reset_clears_state(self):
        """Reset must unblock the guard and clear sizes history."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(-1.0, t0)
        assert guard.is_blocked(t0 + 0.1)

        guard.reset()
        assert not guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == ""

    def test_wave345_is_entry_blocked_delegation(self):
        """is_entry_blocked delegates to is_blocked with timestamp."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(-1.0, t0)
        assert guard.is_entry_blocked(2400.0, 2400.20, t0 + 0.1)

    def test_wave345_uniform_sizing_high_alpha_no_block(self):
        """Identical uniform order sizes should produce large alpha and no block."""
        guard = self._make_guard(window_size=12, top_k=3)
        t0 = time.monotonic()
        for i in range(15):
            guard.update(5.0, t0 + i * 0.1)
        assert not guard.is_blocked(t0 + 2.0)
