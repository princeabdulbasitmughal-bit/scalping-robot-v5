"""
tests/test_batch176.py
-----------------------
Unit tests for Batch 176 wave modules:
  - wave118_tick_jitter_guard         (5 tests)
  - wave119_margin_utilization_guard  (5 tests)

Baseline before this batch: 2,004 collected items
Expected after: 2,014 collected items
"""

import math
import time
import threading
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave118_tick_jitter_guard as w118
import wave119_margin_utilization_guard as w119


# ===========================================================================
# wave118 — Tick Arrival Jitter Guard (5 tests)
# ===========================================================================

class TestWave118TickJitterGuard:

    def setup_method(self):
        w118.reset()

    # -- T1: Warmup prevents premature block --
    def test_warmup_prevents_premature_block(self):
        """Fewer than MIN_SAMPLES intervals must not trigger a block."""
        t = 1000.0
        for _ in range(w118.MIN_SAMPLES - 1):
            w118.record_tick(ts=t)
            t += 1.0
        assert w118.is_entry_blocked() is False

    # -- T2: Uniform tick arrival times have zero jitter; not blocked --
    def test_uniform_intervals_not_blocked(self):
        """Uniform 0.10s tick intervals have std-dev=0.0 < 0.50s threshold."""
        t = 1000.0
        for _ in range(w118.MIN_SAMPLES + 5):
            w118.record_tick(ts=t)
            t += 0.10
        assert w118.is_entry_blocked() is False

    # -- T3: Extreme jitter in arrival times triggers block --
    def test_high_jitter_triggers_block(self):
        """Alternating intervals of 0.05s and 1.5s produce std-dev > 0.50s -> block."""
        t = 1000.0
        w118.record_tick(ts=t)
        for i in range(w118.MIN_SAMPLES + 2):
            interval = 1.50 if (i % 2 == 0) else 0.05
            t += interval
            w118.record_tick(ts=t)
        assert w118.is_entry_blocked() is True

    # -- T4: update() works as alias for record_tick --
    def test_update_alias(self):
        """update() functions identically to record_tick()."""
        w118.update(ts=100.0)
        w118.update(ts=100.1)
        with w118._lock:
            assert len(w118._intervals) == 1

    # -- T5: Invalid inputs ignored; reset() clears all state --
    def test_invalid_inputs_and_reset(self):
        """Booleans, NaN, Inf, negative timestamps ignored; reset() clears."""
        w118.record_tick(ts=True)
        w118.record_tick(ts=float("nan"))
        w118.record_tick(ts=-10.0)
        assert w118._last_tick_time == -1.0

        with w118._lock:
            w118._blocked_until = time.monotonic() + 100.0
            w118._intervals.append(0.5)
        assert w118.is_entry_blocked() is True
        w118.reset()
        assert w118.is_entry_blocked() is False
        assert len(w118._intervals) == 0


# ===========================================================================
# wave119 — Dynamic Margin Utilization Guard (5 tests)
# ===========================================================================

class TestWave119MarginUtilizationGuard:

    def setup_method(self):
        w119.reset()

    # -- T1: Normal low utilization does not block --
    def test_low_utilization_not_blocked(self):
        """$2,000 used margin on $10,000 equity (20% utilization) < 40% does not block."""
        w119.record_margin(used_margin=2000.0, equity=10000.0)
        assert w119.is_entry_blocked() is False

    # -- T2: High utilization >= 40% triggers block --
    def test_high_utilization_blocked(self):
        """$4,500 used margin on $10,000 equity (45% utilization) >= 40% triggers block."""
        w119.record_margin(used_margin=4500.0, equity=10000.0)
        assert w119.is_entry_blocked() is True

    # -- T3: Insolvent or zero equity blocks --
    def test_zero_equity_blocked(self):
        """Zero equity triggers block immediately."""
        w119.record_margin(used_margin=0.0, equity=0.0)
        assert w119.is_entry_blocked() is True

    # -- T4: update() works as alias for record_margin --
    def test_update_alias(self):
        """update() functions identically to record_margin()."""
        w119.update(used_margin=5000.0, equity=10000.0)
        assert w119.is_entry_blocked() is True

    # -- T5: Invalid inputs ignored; reset() clears all state --
    def test_invalid_inputs_and_reset(self):
        """Invalid inputs rejected; reset() restores default baseline."""
        w119.record_margin(used_margin=True, equity=10000.0)
        w119.record_margin(used_margin=100.0, equity=float("nan"))
        w119.record_margin(used_margin=-50.0, equity=10000.0)
        assert w119._used_margin == 0.0

        # Set block then reset
        w119.record_margin(used_margin=6000.0, equity=10000.0)
        assert w119.is_entry_blocked() is True
        w119.reset()
        assert w119.is_entry_blocked() is False
        assert w119._used_margin == 0.0
        assert w119._equity == 10000.0
