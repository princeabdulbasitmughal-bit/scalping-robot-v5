"""
Test Suite Batch 288 -- Wave 342: LOB Spread Convexity Burst Guard
"""

import time
import pytest
from wave342_lob_spread_convexity_burst_guard import Wave342LOBSpreadConvexityBurstGuard


class TestWave342SpreadConvexityBurstGuard:
    """Comprehensive test suite for Wave 342: LOB Spread Convexity Burst Guard."""

    def _make_guard(self, **kwargs):
        defaults = dict(
            window_size=8,
            convexity_threshold=2.5,
            cooldown_seconds=45.0,
        )
        defaults.update(kwargs)
        return Wave342LOBSpreadConvexityBurstGuard(**defaults)

    def test_wave342_init_validation(self):
        """Invalid initialization parameters must raise ValueError."""
        with pytest.raises(ValueError):
            Wave342LOBSpreadConvexityBurstGuard(window_size=4)
        with pytest.raises(ValueError):
            Wave342LOBSpreadConvexityBurstGuard(convexity_threshold=0.0)

    def test_wave342_no_block_before_window_fills(self):
        """Guard should not block before the convexity history fills to window_size."""
        guard = self._make_guard(window_size=8)
        t0 = time.monotonic()
        for i in range(5):
            guard.update(2400.0, 2400.20, t0 + i * 0.1)
        assert not guard.is_blocked(t0 + 1.0)

    def test_wave342_stable_spread_no_block(self):
        """Constant or linear spread expansion should produce zero convexity and never block."""
        guard = self._make_guard(window_size=8)
        t0 = time.monotonic()
        # Linear spread expansion: delta S is constant, convexity delta^2 S = 0
        for i in range(20):
            spread = 0.20 + i * 0.01
            guard.update(2400.0, 2400.0 + spread, t0 + i * 0.1)
        assert not guard.is_blocked(t0 + 5.0)

    def test_wave342_convexity_burst_triggers_block(self):
        """Explosive sudden acceleration in spread must trigger SPREAD_CONVEXITY_BURST."""
        guard = self._make_guard(window_size=8, convexity_threshold=2.0)
        t0 = time.monotonic()
        # Stable tight spread baseline
        for i in range(12):
            guard.update(2400.0, 2400.20, t0 + i * 0.1)

        # Sudden massive quadratic/explosive blowout (acceleration jump)
        t_blowout = t0 + 1.3
        guard.update(2400.0, 2405.00, t_blowout)  # spread blows from 0.20 to 5.00!

        assert guard.is_blocked(t_blowout + 0.05)
        assert guard.last_reason == "SPREAD_CONVEXITY_BURST"

    def test_wave342_crossed_quotes_blocks(self):
        """Crossed book (bid >= ask) must immediately trigger CROSSED_QUOTES_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(2400.50, 2400.20, t0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "CROSSED_QUOTES_ERROR"

    def test_wave342_negative_bid_blocks(self):
        """Non-positive bid must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(-1.0, 2400.20, t0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave342_negative_ask_blocks(self):
        """Non-positive ask must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(2400.0, 0.0, t0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave342_bool_input_blocks(self):
        """Boolean inputs must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(True, 2400.20, t0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave342_reset_clears_state(self):
        """Calling reset() must unblock the guard and clear last_reason."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(2400.50, 2400.20, t0)  # crossed
        assert guard.is_blocked(t0 + 0.1)

        guard.reset()
        assert not guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == ""

    def test_wave342_is_entry_blocked_delegation(self):
        """is_entry_blocked should delegate to is_blocked with timestamp."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(2400.50, 2400.20, t0)  # crossed
        assert guard.is_entry_blocked(2400.0, 2400.20, t0 + 0.1)
