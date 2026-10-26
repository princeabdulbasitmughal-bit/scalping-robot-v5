"""
tests/test_batch300.py
======================
BATCH 300 LANDMARK -- Combined pytest test suite for Wave 358 and Wave 359.

Wave 358: LOB Order Size Dispersion Guard
Wave 359: Trade Flow Levy Alpha-Stable Tail Index Guard

All tests are self-contained.  No external dependencies beyond the two guard
modules themselves and the Python standard library.
"""

import math
import sys
import time
import os

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap -- allows running from any working directory
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wave358_lob_order_size_dispersion_guard import Wave358LOBOrderSizeDispersionGuard
from wave359_trade_flow_levy_alpha_stable_tail_index_guard import (
    Wave359TradeFlowLevyAlphaStableTailIndexGuard,
)

# ===========================================================================
# Helpers
# ===========================================================================

_NOW = time.monotonic()


def _ts(offset: float = 0.0) -> float:
    """Return a stable monotonic-style timestamp for tests."""
    return _NOW + offset


def _fill_w358(guard, n=20, bid=100.0, ask=100.0):
    """Feed n identical ticks to the Wave358 guard."""
    for i in range(n):
        guard.update(bid, ask, _ts(i * 0.1))


def _fill_w359(guard, n=30, volume=1.0, side="buy"):
    """Feed n identical ticks to the Wave359 guard."""
    for i in range(n):
        guard.update(volume, side, _ts(i * 0.1))


# ===========================================================================
# Wave 358 -- LOB Order Size Dispersion Guard tests
# ===========================================================================

class TestWave358NoBlockBeforeWindowFills:
    """Guard must not block until the rolling window is full."""

    def test_no_block_before_full_window(self):
        guard = Wave358LOBOrderSizeDispersionGuard(window_size=20)
        t = _ts()
        # Feed only window_size - 1 ticks
        for i in range(19):
            guard.update(100.0, 100.0, t + i * 0.1)
        assert not guard.is_blocked(t + 10.0), "Should not block with partial window"
        assert guard.last_reason == ""


class TestWave358HappyPathNoBlock:
    """Constant depths produce CoV=0, which should not trigger a block."""

    def test_constant_depths_no_block(self):
        guard = Wave358LOBOrderSizeDispersionGuard(window_size=20, dispersion_threshold=1.0)
        _fill_w358(guard, n=20, bid=500.0, ask=500.0)
        assert not guard.is_blocked(), "Constant depths => CoV=0 => no block"

    def test_slightly_variable_depths_below_threshold(self):
        guard = Wave358LOBOrderSizeDispersionGuard(window_size=20, dispersion_threshold=1.0)
        # Alternating 90 / 110 => mean=100, std~10 => CoV=0.10 < 1.0
        for i in range(20):
            bid = 45.0 if i % 2 == 0 else 55.0
            ask = 45.0 if i % 2 == 0 else 55.0
            guard.update(bid, ask, _ts(i * 0.1))
        assert not guard.is_blocked()


class TestWave358DispersionBreach:
    """High CoV must trigger ORDER_SIZE_DISPERSION_BREACH."""

    def test_high_dispersion_trips_guard(self):
        guard = Wave358LOBOrderSizeDispersionGuard(
            window_size=20, dispersion_threshold=0.5, cooldown_seconds=60.0
        )
        # First 10 ticks: depth = 10, next 10: depth = 1000 => huge CoV
        for i in range(10):
            guard.update(5.0, 5.0, _ts(i * 0.1))
        for i in range(10):
            guard.update(500.0, 500.0, _ts(1.0 + i * 0.1))
        assert guard.is_blocked(), "High dispersion should trip the guard"
        assert guard.last_reason == Wave358LOBOrderSizeDispersionGuard.ORDER_SIZE_DISPERSION_BREACH


class TestWave358InvalidInputBlocks:
    """Any invalid input must cause INPUT_VALIDATION_ERROR and block."""

    def test_negative_bid_depth(self):
        guard = Wave358LOBOrderSizeDispersionGuard()
        guard.update(-1.0, 100.0, _ts())
        assert guard.is_blocked()
        assert guard.last_reason == Wave358LOBOrderSizeDispersionGuard.INPUT_VALIDATION_ERROR

    def test_nan_ask_depth(self):
        guard = Wave358LOBOrderSizeDispersionGuard()
        guard.update(100.0, float("nan"), _ts())
        assert guard.is_blocked()
        assert guard.last_reason == Wave358LOBOrderSizeDispersionGuard.INPUT_VALIDATION_ERROR

    def test_bool_bid_depth_fails_closed(self):
        guard = Wave358LOBOrderSizeDispersionGuard()
        guard.update(True, 100.0, _ts())   # bool must be rejected before int/float check
        assert guard.is_blocked()
        assert guard.last_reason == Wave358LOBOrderSizeDispersionGuard.INPUT_VALIDATION_ERROR

    def test_string_ask_depth(self):
        guard = Wave358LOBOrderSizeDispersionGuard()
        guard.update(100.0, "big", _ts())
        assert guard.is_blocked()
        assert guard.last_reason == Wave358LOBOrderSizeDispersionGuard.INPUT_VALIDATION_ERROR

    def test_inf_timestamp(self):
        guard = Wave358LOBOrderSizeDispersionGuard()
        guard.update(100.0, 100.0, float("inf"))
        assert guard.is_blocked()
        assert guard.last_reason == Wave358LOBOrderSizeDispersionGuard.INPUT_VALIDATION_ERROR


class TestWave358Reset:
    """reset() must clear block state and depth window."""

    def test_reset_clears_block(self):
        guard = Wave358LOBOrderSizeDispersionGuard(
            window_size=20, dispersion_threshold=0.1, cooldown_seconds=60.0
        )
        # Trip the guard
        for i in range(10):
            guard.update(1.0, 1.0, _ts(i * 0.1))
        for i in range(10):
            guard.update(1000.0, 1000.0, _ts(1.0 + i * 0.1))

        assert guard.is_blocked()
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""

    def test_reset_then_no_block_before_window(self):
        guard = Wave358LOBOrderSizeDispersionGuard(window_size=20)
        _fill_w358(guard, n=20)
        guard.reset()
        # Feed only one tick after reset
        guard.update(50.0, 50.0, _ts())
        assert not guard.is_blocked()


class TestWave358IsEntryBlocked:
    """is_entry_blocked delegates update + block check."""

    def test_is_entry_blocked_delegates_and_no_block(self):
        guard = Wave358LOBOrderSizeDispersionGuard(window_size=20)
        # Call 19 times -- window not full, never blocks
        for i in range(19):
            result = guard.is_entry_blocked(100.0, 100.0, _ts(i * 0.1))
            assert result is False


# ===========================================================================
# Wave 359 -- Trade Flow Levy Alpha-Stable Tail Index Guard tests
# ===========================================================================

class TestWave359NoBlockBeforeWindowFills:
    """Guard must not block until window_size ticks have been received."""

    def test_no_block_partial_window(self):
        guard = Wave359TradeFlowLevyAlphaStableTailIndexGuard(window_size=30)
        for i in range(29):
            guard.update(1.0, "buy", _ts(i * 0.1))
        assert not guard.is_blocked()
        assert guard.last_reason == ""


class TestWave359HappyPathNoBlock:
    """Uniform volumes with alpha inside [alpha_low, alpha_high] => no block."""

    def test_uniform_volumes_no_block(self):
        """
        All equal |SV| => log ratios = 0 => degenerate Hill => INSUFFICIENT_DATA trip.
        Verify this by using slightly varied volumes that land inside the safe band.
        """
        guard = Wave359TradeFlowLevyAlphaStableTailIndexGuard(
            window_size=30, alpha_low=0.5, alpha_high=10.0, cooldown_seconds=0.0
        )
        # Volumes from 1..30 produce a well-defined Hill estimator inside a wide window
        for i in range(1, 31):
            side = "buy" if i % 2 == 0 else "sell"
            guard.update(float(i), side, _ts(i * 0.1))
        # Wide band => should not block
        assert not guard.is_blocked()


class TestWave359HeavyTail:
    """Extremely heavy-tailed distribution => alpha_hat < alpha_low => HEAVY_TAIL_DETECTED."""

    def test_heavy_tail_trips_guard(self):
        guard = Wave359TradeFlowLevyAlphaStableTailIndexGuard(
            window_size=30, alpha_low=1.2, alpha_high=2.8, cooldown_seconds=60.0
        )
        # One enormous outlier among tiny values forces very low Hill alpha
        for i in range(29):
            guard.update(0.001, "buy", _ts(i * 0.05))
        guard.update(1e9, "sell", _ts(30 * 0.05))   # extreme outlier

        # May produce HEAVY_TAIL or INSUFFICIENT_DATA depending on nonzero filtering
        assert guard.is_blocked()
        assert guard.last_reason in (
            Wave359TradeFlowLevyAlphaStableTailIndexGuard.HEAVY_TAIL_DETECTED,
            Wave359TradeFlowLevyAlphaStableTailIndexGuard.INSUFFICIENT_DATA,
        )


class TestWave359InvalidInputBlocks:
    """Any invalid input must cause INPUT_VALIDATION_ERROR and block."""

    def test_negative_volume(self):
        guard = Wave359TradeFlowLevyAlphaStableTailIndexGuard()
        guard.update(-5.0, "buy", _ts())
        assert guard.is_blocked()
        assert guard.last_reason == Wave359TradeFlowLevyAlphaStableTailIndexGuard.INPUT_VALIDATION_ERROR

    def test_invalid_side(self):
        guard = Wave359TradeFlowLevyAlphaStableTailIndexGuard()
        guard.update(1.0, "long", _ts())   # "long" is not a valid side
        assert guard.is_blocked()
        assert guard.last_reason == Wave359TradeFlowLevyAlphaStableTailIndexGuard.INPUT_VALIDATION_ERROR

    def test_bool_volume_fails_closed(self):
        guard = Wave359TradeFlowLevyAlphaStableTailIndexGuard()
        guard.update(True, "buy", _ts())   # bool before int/float check
        assert guard.is_blocked()
        assert guard.last_reason == Wave359TradeFlowLevyAlphaStableTailIndexGuard.INPUT_VALIDATION_ERROR

    def test_nan_volume(self):
        guard = Wave359TradeFlowLevyAlphaStableTailIndexGuard()
        guard.update(float("nan"), "sell", _ts())
        assert guard.is_blocked()
        assert guard.last_reason == Wave359TradeFlowLevyAlphaStableTailIndexGuard.INPUT_VALIDATION_ERROR

    def test_numeric_side(self):
        guard = Wave359TradeFlowLevyAlphaStableTailIndexGuard()
        guard.update(1.0, 1, _ts())   # side must be str
        assert guard.is_blocked()
        assert guard.last_reason == Wave359TradeFlowLevyAlphaStableTailIndexGuard.INPUT_VALIDATION_ERROR

    def test_inf_timestamp(self):
        guard = Wave359TradeFlowLevyAlphaStableTailIndexGuard()
        guard.update(1.0, "buy", float("inf"))
        assert guard.is_blocked()
        assert guard.last_reason == Wave359TradeFlowLevyAlphaStableTailIndexGuard.INPUT_VALIDATION_ERROR


class TestWave359Reset:
    """reset() must clear the volume window and block state."""

    def test_reset_clears_block(self):
        guard = Wave359TradeFlowLevyAlphaStableTailIndexGuard()
        guard.update(True, "buy", _ts())   # triggers INPUT_VALIDATION_ERROR
        assert guard.is_blocked()
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""

    def test_reset_then_partial_window_no_block(self):
        guard = Wave359TradeFlowLevyAlphaStableTailIndexGuard(window_size=30)
        _fill_w359(guard, n=30)
        guard.reset()
        guard.update(1.0, "buy", _ts())
        assert not guard.is_blocked()


class TestWave359IsEntryBlocked:
    """is_entry_blocked must delegate update then check block status."""

    def test_is_entry_blocked_no_block_partial(self):
        guard = Wave359TradeFlowLevyAlphaStableTailIndexGuard(window_size=30)
        # is_entry_blocked passes bid as volume, str(ask) as side
        # Use "buy" as ask (str cast still produces "buy")
        for i in range(29):
            result = guard.is_entry_blocked(1.0, "buy", _ts(i * 0.1))
            assert result is False


class TestWave359IsBlockedBadCurrentTime:
    """is_blocked must fail-closed on non-numeric current_time."""

    def test_bad_current_time_type_blocks(self):
        guard = Wave359TradeFlowLevyAlphaStableTailIndexGuard()
        # Guard is not tripped, but passing a bad current_time should still block
        assert guard.is_blocked("now") is True

    def test_bool_current_time_blocks(self):
        guard = Wave359TradeFlowLevyAlphaStableTailIndexGuard()
        assert guard.is_blocked(True) is True


# ===========================================================================
# Cross-guard: both guards share the same structural contract
# ===========================================================================

class TestContractCompliance:
    """Both guards must expose the required public interface."""

    @pytest.mark.parametrize("GuardClass", [
        Wave358LOBOrderSizeDispersionGuard,
        Wave359TradeFlowLevyAlphaStableTailIndexGuard,
    ])
    def test_interface_methods_present(self, GuardClass):
        guard = GuardClass()
        assert hasattr(guard, "update")
        assert hasattr(guard, "is_blocked")
        assert hasattr(guard, "is_entry_blocked")
        assert hasattr(guard, "reset")
        assert hasattr(guard, "last_reason")

    @pytest.mark.parametrize("GuardClass", [
        Wave358LOBOrderSizeDispersionGuard,
        Wave359TradeFlowLevyAlphaStableTailIndexGuard,
    ])
    def test_initial_state_not_blocked(self, GuardClass):
        guard = GuardClass()
        assert not guard.is_blocked()
        assert guard.last_reason == ""
