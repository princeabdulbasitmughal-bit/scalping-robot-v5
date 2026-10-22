"""
tests/test_batch179.py
-----------------------
Unit tests for Batch 179 wave modules:
  - wave124_tick_acceleration_guard   (5 tests)
  - wave125_order_size_drift_guard    (5 tests)

Baseline before this batch: 2,034 collected items
Expected after: 2,044 collected items
"""

import math
import time
import threading
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave124_tick_acceleration_guard as w124
import wave125_order_size_drift_guard as w125


# ===========================================================================
# wave124 — Tick Price Acceleration (2nd Derivative) Guard (5 tests)
# ===========================================================================

class TestWave124TickAccelerationGuard:

    def setup_method(self):
        w124.reset()

    # -- T1: Constant velocity produces zero acceleration; not blocked --
    def test_constant_velocity_not_blocked(self):
        """Constant speed moves have zero acceleration and must not block."""
        t = 1000.0
        p = 100.0
        for _ in range(5):
            w124.record_tick(price=p, ts=t)
            t += 1.0
            p += 0.5   # steady +0.5 per sec -> v=0.5, a=0.0
        assert w124.is_entry_blocked() is False

    # -- T2: Explosive acceleration spike triggers block --
    def test_acceleration_spike_triggers_block(self):
        """Sudden leap in velocity from 0.1 to 10.0 in 1 second triggers block."""
        w124.record_tick(price=100.0, ts=1000.0)
        w124.record_tick(price=100.1, ts=1001.0) # v1 = 0.1
        w124.record_tick(price=110.1, ts=1002.0) # v2 = 10.0 -> a = 9.9 >= 5.0
        assert w124.is_entry_blocked() is True

    # -- T3: Sub-millisecond duplicate ticks are ignored safely --
    def test_duplicate_sub_ms_ticks_ignored(self):
        """Ticks with dt <= 0.0001s do not produce division-by-zero crashes."""
        w124.record_tick(price=100.0, ts=1000.0)
        w124.record_tick(price=100.0, ts=1000.00001) # dt = 0.00001
        assert w124._prev_price == 100.0

    # -- T4: update() works as alias for record_tick --
    def test_update_alias(self):
        """update() functions identically to record_tick()."""
        w124.update(price=50.0, ts=10.0)
        w124.update(price=50.1, ts=11.0)
        with w124._lock:
            assert w124._prev_price == 50.1

    # -- T5: Invalid inputs ignored; reset() clears all state --
    def test_invalid_inputs_and_reset(self):
        """Booleans, NaN, Inf, non-positive values ignored; reset() clears."""
        w124.record_tick(price=True)
        w124.record_tick(price=float("nan"))
        w124.record_tick(price=-10.0)
        assert w124._prev_time == -1.0

        with w124._lock:
            w124._blocked_until = time.monotonic() + 100.0
        assert w124.is_entry_blocked() is True
        w124.reset()
        assert w124.is_entry_blocked() is False
        assert w124._prev_time == -1.0
        assert w124._has_prev_velocity is False


# ===========================================================================
# wave125 — Dynamic Order Size Drift Guard (5 tests)
# ===========================================================================

class TestWave125OrderSizeDriftGuard:

    def setup_method(self):
        w125.reset()

    # -- T1: Warmup requires MIN_SAMPLES before drift checks activate --
    def test_warmup_requires_min_samples(self):
        """Fewer than MIN_SAMPLES orders do not trigger drift block."""
        for _ in range(w125.MIN_SAMPLES - 1):
            w125.record_order(1.0)
        # Even a 10.0 order during warmup does not trigger
        w125.record_order(10.0)
        assert w125.is_entry_blocked() is False

    # -- T2: Normal sizes matching average do not block --
    def test_normal_sizes_not_blocked(self):
        """Orders near average (e.g. 1.0 lots) do not block."""
        for _ in range(10):
            w125.record_order(1.0)
        assert w125.is_entry_blocked() is False
        assert w125.check_order(1.5) is True

    # -- T3: Large size >= 3x average triggers block --
    def test_large_size_triggers_block(self):
        """Submitting a 3.5 lot order when average is 1.0 (3.5x >= 3.0x) triggers block."""
        for _ in range(5):
            w125.record_order(1.0)
        assert w125.check_order(3.5) is False
        w125.record_order(3.5)
        assert w125.is_entry_blocked() is True

    # -- T4: update() works as alias for record_order --
    def test_update_alias(self):
        """update() functions identically to record_order()."""
        w125.update(2.0)
        with w125._lock:
            assert len(w125._order_sizes) == 1
            assert w125._order_sizes[0] == 2.0

    # -- T5: Invalid inputs ignored; reset() clears all state --
    def test_invalid_inputs_and_reset(self):
        """Booleans, NaN, Inf, non-positive sizes ignored; reset() clears."""
        w125.record_order(True)
        w125.record_order(float("nan"))
        w125.record_order(-1.0)
        with w125._lock:
            assert len(w125._order_sizes) == 0

        with w125._lock:
            w125._blocked_until = time.monotonic() + 100.0
        assert w125.is_entry_blocked() is True
        w125.reset()
        assert w125.is_entry_blocked() is False
        with w125._lock:
            assert len(w125._order_sizes) == 0
