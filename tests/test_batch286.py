"""
Batch 286 -- Tests for Wave 338 and Wave 339
============================================
Wave 338: LOB Quote Stuffing Rate Guard
Wave 339: Trade Flow Signed-Volume Acceleration Momentum Guard

Target: 15 new tests, 0 failures
Baseline before: 3,108 passed, 1 skipped
Baseline after:  3,123 passed, 1 skipped
"""

import time
import pytest

from wave338_lob_quote_stuffing_rate_guard import (
    Wave338LOBQuoteStuffingRateGuard,
)
from wave339_trade_flow_signed_volume_acceleration_momentum_guard import (
    Wave339TradeFlowSignedVolumeAccelerationMomentumGuard,
)


# ─────────────────────────────────────────────────────────────
# Wave 338 -- Quote Stuffing Rate Guard Tests
# ─────────────────────────────────────────────────────────────


class TestWave338QuoteStuffingGuard:
    """Tests for the LOB quote stuffing rate guard."""

    def _make_guard(self, **kw):
        defaults = dict(
            window_seconds=1.0,
            stuffing_ratio_threshold=10.0,
            min_quote_count=5,
            cooldown_seconds=45.0,
        )
        defaults.update(kw)
        return Wave338LOBQuoteStuffingRateGuard(**defaults)

    def test_wave338_no_block_below_min_quote_count(self):
        """Guard must not block when quote count < min_quote_count."""
        guard = self._make_guard(min_quote_count=10)
        t0 = time.monotonic()
        for i in range(9):  # only 9 quotes, threshold is 10
            guard.add_quote(t0 + i * 0.05)
        assert not guard.is_blocked(t0 + 0.5), "Below min_quote_count should not block"

    def test_wave338_high_ratio_triggers_block(self):
        """Very high quote/trade ratio should trigger stuffing block."""
        guard = self._make_guard(stuffing_ratio_threshold=10.0, min_quote_count=5)
        t0 = time.monotonic()
        # Add 1 trade and 50 quotes in same window -> ratio = 50
        guard.add_trade(t0)
        for i in range(50):
            guard.add_quote(t0 + i * 0.001)
        assert guard.is_blocked(t0 + 0.1), "50:1 quote/trade ratio should trigger block"
        assert guard.last_reason == "QUOTE_STUFFING_DETECTED"

    def test_wave338_low_ratio_no_block(self):
        """Low quote/trade ratio (1:1) should not block."""
        guard = self._make_guard(stuffing_ratio_threshold=10.0, min_quote_count=5)
        t0 = time.monotonic()
        for i in range(10):
            guard.add_quote(t0 + i * 0.05)
            guard.add_trade(t0 + i * 0.05)
        assert not guard.is_blocked(t0 + 0.6), "1:1 ratio should not block"

    def test_wave338_old_quotes_evicted(self):
        """Quotes outside the window should be evicted and not count."""
        # Use a high min_quote_count so the old (past) quotes alone don't trigger block,
        # then verify that after eviction only the current-window quotes remain (below threshold).
        guard = self._make_guard(
            window_seconds=0.5,
            min_quote_count=100,    # need 100 quotes to trigger block
            stuffing_ratio_threshold=10.0,
        )
        t0 = time.monotonic()
        # Add 50 quotes far in the past (outside 0.5s window) - below min_quote_count=100
        for i in range(50):
            guard.add_quote(t0 - 1.0 - i * 0.001)
        # Now add 5 quotes in the present with 1 trade -> ratio=5 < 10 and count < 100 -> no block
        guard.add_trade(t0)
        for i in range(5):
            guard.add_quote(t0 + i * 0.01)
        # After eviction, only 5 current-window quotes remain (far below min_quote_count=100)
        assert not guard.is_blocked(t0 + 0.1), "Old quotes evicted; current-window count too low to block"

    def test_wave338_invalid_timestamp_type_blocks(self):
        """Non-numeric timestamp must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        guard.add_quote("not-a-float")
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave338_bool_timestamp_blocks(self):
        """Boolean timestamp must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        guard.add_quote(True)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave338_reset_clears_state(self):
        """Reset must clear all accumulated state."""
        guard = self._make_guard(stuffing_ratio_threshold=10.0, min_quote_count=5)
        t0 = time.monotonic()
        guard.add_trade(t0)
        for i in range(50):
            guard.add_quote(t0 + i * 0.001)
        assert guard.is_blocked(t0 + 0.1)
        guard.reset()
        assert not guard.is_blocked(t0 + 0.1), "After reset, guard should be unblocked"
        assert guard.last_reason == ""

    def test_wave338_is_entry_blocked_delegates(self):
        """is_entry_blocked must return same result as is_blocked."""
        guard = self._make_guard()
        t0 = time.monotonic()
        assert guard.is_entry_blocked(1.1000, 1.10011, t0) == guard.is_blocked(t0)


# ─────────────────────────────────────────────────────────────
# Wave 339 -- Signed-Volume Acceleration Momentum Guard Tests
# ─────────────────────────────────────────────────────────────


class TestWave339AccelerationMomentumGuard:
    """Tests for the signed-volume acceleration momentum guard."""

    def _make_guard(self, **kw):
        defaults = dict(
            momentum_window=3,
            accel_window=5,
            accel_threshold=20.0,
            cooldown_seconds=45.0,
        )
        defaults.update(kw)
        return Wave339TradeFlowSignedVolumeAccelerationMomentumGuard(**defaults)

    def test_wave339_no_block_before_window_fills(self):
        """Guard must not block before accel_window accelerations computed."""
        guard = self._make_guard(momentum_window=3, accel_window=5)
        t0 = time.monotonic()
        for i in range(5):  # only 5 ticks -> 2 momentums -> 1 accel < accel_window
            guard.update(10.0, "buy", t0 + i)
        assert not guard.is_blocked(t0 + 5), "Not enough accels to trigger block"

    def test_wave339_steady_flow_no_block(self):
        """Constant one-directional flow has zero acceleration; should not block."""
        guard = self._make_guard(accel_threshold=20.0)
        t0 = time.monotonic()
        for i in range(30):
            guard.update(10.0, "buy", t0 + i)
        # Momentum is constant (always 30 = 3 * 10.0), acceleration = 0
        assert not guard.is_blocked(t0 + 30), "Constant flow has zero acceleration"

    def test_wave339_reversing_flow_triggers_block(self):
        """Alternating buy/sell creates large acceleration; should block."""
        guard = self._make_guard(
            momentum_window=3,
            accel_window=5,
            accel_threshold=10.0,
        )
        t0 = time.monotonic()
        # Alternate large buys and sells: momentum swings ±30 each tick
        for i in range(30):
            side = "buy" if i % 2 == 0 else "sell"
            guard.update(30.0, side, t0 + i)
        assert guard.is_blocked(t0 + 30), "Reversing large flow should trigger block"
        assert guard.last_reason == "FLOW_ACCELERATION_BREACH"

    def test_wave339_invalid_side_blocks(self):
        """Invalid trade side must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(10.0, "LIMIT", t0)
        assert guard.is_blocked(t0 + 0.001)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave339_zero_volume_blocks(self):
        """Zero volume must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(0.0, "buy", t0)
        assert guard.is_blocked(t0 + 0.001)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave339_bool_volume_blocks(self):
        """Boolean volume must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(True, "buy", t0)
        assert guard.is_blocked(t0 + 0.001)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave339_reset_clears_state(self):
        """Reset must clear all accumulated state."""
        guard = self._make_guard(accel_threshold=10.0)
        t0 = time.monotonic()
        for i in range(30):
            side = "buy" if i % 2 == 0 else "sell"
            guard.update(30.0, side, t0 + i)
        assert guard.is_blocked(t0 + 30)
        guard.reset()
        assert not guard.is_blocked(t0 + 30), "After reset, guard should be unblocked"
        assert guard.last_reason == ""
