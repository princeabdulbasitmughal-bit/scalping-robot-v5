"""
tests/test_batch178.py
-----------------------
Unit tests for Batch 178 wave modules:
  - wave122_tick_reversal_intensity_guard    (5 tests)
  - wave123_order_cancellation_ratio_guard   (5 tests)

Baseline before this batch: 2,024 collected items
Expected after: 2,034 collected items
"""

import math
import time
import threading
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave122_tick_reversal_intensity_guard as w122
import wave123_order_cancellation_ratio_guard as w123


# ===========================================================================
# wave122 — High-Frequency Reversal Intensity Guard (5 tests)
# ===========================================================================

class TestWave122TickReversalIntensityGuard:

    def setup_method(self):
        w122.reset()

    # -- T1: Warmup prevents premature block --
    def test_warmup_prevents_premature_block(self):
        """Fewer than MIN_SAMPLES transitions must not trigger a block."""
        # 5 alternating ticks = 4 transitions < 10
        prices = [100.0, 100.1, 100.0, 100.1, 100.0]
        for p in prices:
            w122.update(p)
        assert w122.is_entry_blocked() is False

    # -- T2: Steady trend has zero reversals; not blocked --
    def test_trending_ticks_zero_reversals(self):
        """Monotonic price increases have zero reversals -> not blocked."""
        for i in range(15):
            w122.update(100.0 + i * 0.1)
        assert w122.is_entry_blocked() is False

    # -- T3: Rapid ping-pong chop (100% reversals) triggers block --
    def test_ping_pong_chop_triggers_block(self):
        """15 alternating ticks (up/down/up/down) produces 100% reversal rate -> blocks."""
        w122.update(100.0)  # baseline
        for i in range(1, 15):
            p = 100.1 if (i % 2 == 1) else 100.0
            w122.update(p)
        assert w122.is_entry_blocked() is True

    # -- T4: Flat ticks are ignored and do not corrupt direction --
    def test_flat_ticks_ignored(self):
        """Flat ticks (same price) are ignored without breaking transition tracking."""
        w122.update(100.0)
        w122.update(100.0)  # flat
        w122.update(100.1)  # up
        w122.update(100.1)  # flat
        assert w122._last_direction == 1

    # -- T5: Invalid inputs ignored; reset() clears all state --
    def test_invalid_inputs_and_reset(self):
        """Booleans, NaN, Inf, non-positive values ignored; reset() clears."""
        w122.update(True)
        w122.update(float("nan"))
        w122.update(-1.0)
        assert w122._last_price == -1.0

        with w122._lock:
            w122._blocked_until = time.monotonic() + 100.0
        assert w122.is_entry_blocked() is True
        w122.reset()
        assert w122.is_entry_blocked() is False
        assert w122._last_price == -1.0
        assert len(w122._reversals) == 0


# ===========================================================================
# wave123 — Order Cancellation & Rejection Ratio Guard (5 tests)
# ===========================================================================

class TestWave123OrderCancellationRatioGuard:

    def setup_method(self):
        w123.reset()

    # -- T1: Warmup requires MIN_SAMPLES before evaluation --
    def test_warmup_requires_min_samples(self):
        """Fewer than MIN_SAMPLES orders do not trigger block even if all rejected."""
        for _ in range(w123.MIN_SAMPLES - 1):
            w123.record_order(True)  # rejects
        assert w123.is_entry_blocked() is False

    # -- T2: Healthy order execution (0% rejects) does not block --
    def test_healthy_orders_not_blocked(self):
        """All filled orders (0 rejects) do not block."""
        for _ in range(w123.MIN_SAMPLES):
            w123.record_order(False)  # fills
        assert w123.is_entry_blocked() is False

    # -- T3: High reject ratio (>= 30%) triggers block --
    def test_high_reject_ratio_triggers_block(self):
        """2 rejects out of 5 orders = 40% reject ratio >= 30% -> blocks."""
        w123.record_order(True)   # reject 1
        w123.record_order(False)  # fill 1
        w123.record_order(True)   # reject 2
        w123.record_order(False)  # fill 2
        w123.record_order(False)  # fill 3
        # 2 / 5 = 0.40 >= 0.30 -> blocked
        assert w123.is_entry_blocked() is True

    # -- T4: update() works as alias for record_order --
    def test_update_alias(self):
        """update() functions identically to record_order()."""
        w123.update(False)
        with w123._lock:
            assert len(w123._order_outcomes) == 1
            assert w123._order_outcomes[0] == 0

    # -- T5: Invalid inputs ignored; reset() clears all state --
    def test_invalid_inputs_and_reset(self):
        """Non-boolean inputs rejected; reset() clears history."""
        w123.record_order("reject")  # string rejected
        w123.record_order(1)         # int rejected
        w123.record_order(0)         # int rejected
        with w123._lock:
            assert len(w123._order_outcomes) == 0

        # Set block then reset
        with w123._lock:
            w123._blocked_until = time.monotonic() + 100.0
        assert w123.is_entry_blocked() is True
        w123.reset()
        assert w123.is_entry_blocked() is False
        with w123._lock:
            assert len(w123._order_outcomes) == 0
