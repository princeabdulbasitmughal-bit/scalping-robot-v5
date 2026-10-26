"""
Test Suite Batch 296 -- Wave 350: Market Depth Entropy Spectral Density Guard (Jubilee Wave)
"""

import time
import pytest
from wave350_market_depth_entropy_spectral_density_guard import Wave350MarketDepthEntropySpectralDensityGuard


class TestWave350MarketDepthEntropyGuard:
    """Comprehensive test suite for Wave 350: Market Depth Entropy Guard."""

    def _make_guard(self, **kwargs):
        defaults = dict(
            window_size=6,
            min_entropy_threshold=0.60,
            cooldown_seconds=45.0,
        )
        defaults.update(kwargs)
        return Wave350MarketDepthEntropySpectralDensityGuard(**defaults)

    def test_wave350_init_validation(self):
        """Invalid initialization parameters must raise ValueError."""
        with pytest.raises(ValueError):
            Wave350MarketDepthEntropySpectralDensityGuard(window_size=3)
        with pytest.raises(ValueError):
            Wave350MarketDepthEntropySpectralDensityGuard(min_entropy_threshold=0.0)
        with pytest.raises(ValueError):
            Wave350MarketDepthEntropySpectralDensityGuard(min_entropy_threshold=1.0)

    def test_wave350_no_block_before_window_fills(self):
        """Guard should not block before window_size observations accumulate."""
        guard = self._make_guard(window_size=6)
        t0 = time.monotonic()
        for i in range(4):
            guard.update([10.0, 10.0, 10.0], t0 + i * 0.1)
        assert not guard.is_blocked(t0 + 1.0)

    def test_wave350_uniform_distribution_high_entropy_no_block(self):
        """Uniform distribution across orderbook depth has H_norm = 1.0 and must not block."""
        guard = self._make_guard(window_size=6, min_entropy_threshold=0.60)
        t0 = time.monotonic()
        # Perfectly uniform depth: 5 levels of 100 lots each -> H_norm = 1.0
        for i in range(12):
            guard.update([100.0, 100.0, 100.0, 100.0, 100.0], t0 + i * 0.1)
        assert not guard.is_blocked(t0 + 2.0)

    def test_wave350_extreme_concentration_triggers_collapse_block(self):
        """Extreme liquidity concentration on a single level triggers DEPTH_ENTROPY_COLLAPSE."""
        guard = self._make_guard(window_size=5, min_entropy_threshold=0.50)
        t0 = time.monotonic()
        # 1 level has 10,000 lots, other 4 levels have only 0.01 lots
        # p_1 ~ 1.0, others ~ 0 -> H ~ 0 -> H_norm ~ 0 <= 0.50
        ts = t0
        for i in range(6):
            ts += 0.1
            guard.update([10000.0, 0.01, 0.01, 0.01, 0.01], ts)

        assert guard.is_blocked(ts + 0.05)
        assert guard.last_reason == "DEPTH_ENTROPY_COLLAPSE"

    def test_wave350_empty_depth_list_blocks(self):
        """Empty depth list must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update([], t0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave350_single_element_list_blocks(self):
        """Single element depth list (< 2 levels) must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update([100.0], t0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave350_non_positive_element_blocks(self):
        """Non-positive depth sizes in list must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update([100.0, -5.0], t0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave350_bool_inputs_block(self):
        """Boolean inputs must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update([True, 100.0], t0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave350_reset_clears_state(self):
        """Reset must unblock the guard and clear entropies history."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update([], t0)
        assert guard.is_blocked(t0 + 0.1)

        guard.reset()
        assert not guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == ""

    def test_wave350_is_entry_blocked_delegation(self):
        """is_entry_blocked delegates to is_blocked with timestamp."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update([], t0)
        assert guard.is_entry_blocked(2400.0, 2400.20, t0 + 0.1)
