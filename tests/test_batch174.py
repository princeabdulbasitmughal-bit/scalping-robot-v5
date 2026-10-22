"""
tests/test_batch174.py
-----------------------
Unit tests for Batch 174 wave modules:
  - wave114_profit_giveback_guard           (5 tests)
  - wave115_tick_frequency_anomaly_guard   (5 tests)

Baseline before this batch: 1,984 collected items
Expected after: 1,994 collected items
"""

import math
import time
import threading
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave114_profit_giveback_guard as w114
import wave115_tick_frequency_anomaly_guard as w115


# ===========================================================================
# wave114 — Peak Floating Profit Giveback Guard (5 tests)
# ===========================================================================

class TestWave114ProfitGivebackGuard:

    def setup_method(self):
        w114.reset()

    # -- T1: Profit below MIN_PROFIT_TRIGGER_USD does not trigger giveback rule --
    def test_low_profit_no_giveback_trigger(self):
        """Floating profit reaching $30 (< $50 trigger) then dropping to $10 does not block."""
        w114.update(30.0)
        w114.update(10.0)  # >50% drop, but peak was below trigger
        assert w114.is_entry_blocked() is False

    # -- T2: 50% giveback from peak >= $50 triggers block --
    def test_blocked_on_severe_giveback(self):
        """Peak of $100 giving back to $45 (55% giveback >= 50%) blocks entries."""
        w114.update(100.0)  # peak established >= 50
        w114.update(45.0)   # 55% giveback
        assert w114.is_entry_blocked() is True

    # -- T3: Modest giveback (< 50%) does not block --
    def test_not_blocked_modest_giveback(self):
        """Peak of $100 dropping to $60 (40% giveback < 50%) does not block."""
        w114.update(100.0)
        w114.update(60.0)
        assert w114.is_entry_blocked() is False

    # -- T4: Negative PnL clears peak profit tracking --
    def test_negative_pnl_resets_peak(self):
        """When positions close or PnL dips into negative, peak is reset to zero."""
        w114.update(80.0)
        w114.update(-5.0)
        assert w114._peak_floating_pnl == 0.0

    # -- T5: Invalid inputs ignored; reset() clears all state --
    def test_invalid_inputs_and_reset(self):
        """Boolean, NaN, Inf inputs ignored; reset() restores baseline."""
        w114.update(True)
        w114.update(float("nan"))
        w114.update(float("inf"))
        assert w114._peak_floating_pnl == 0.0

        # Trigger block then reset
        with w114._lock:
            w114._blocked_until = time.monotonic() + 100.0
        assert w114.is_entry_blocked() is True
        w114.reset()
        assert w114.is_entry_blocked() is False
        assert w114._peak_floating_pnl == 0.0


# ===========================================================================
# wave115 — High-Frequency Tick Burst Anomaly Guard (5 tests)
# ===========================================================================

class TestWave115TickFrequencyAnomalyGuard:

    def setup_method(self):
        w115.reset()

    # -- T1: Normal tick frequency does not block --
    def test_normal_frequency_not_blocked(self):
        """Recording 10 ticks over a simulated 5s window does not exceed 25 ticks/sec."""
        for _ in range(10):
            w115.record_tick()
        assert w115.is_entry_blocked() is False

    # -- T2: Burst of ticks exceeding MAX_TICKS_PER_SEC triggers block --
    def test_burst_frequency_blocked(self):
        """Injecting 130 ticks in the same window (>= 25 ticks/sec) blocks entries."""
        now = time.monotonic()
        with w115._lock:
            # Pre-populate 124 ticks in window
            for i in range(124):
                w115._tick_times.append(now - 1.0)
        # 125th tick triggers threshold
        w115.record_tick()
        assert w115.is_entry_blocked() is True

    # -- T3: Old ticks are pruned from the evaluation window --
    def test_old_ticks_pruned(self):
        """Ticks older than WINDOW_SECONDS must be pruned and not count toward rate."""
        now = time.monotonic()
        with w115._lock:
            for _ in range(200):
                w115._tick_times.append(now - 10.0)  # old timestamps
        w115.record_tick()  # triggers prune
        with w115._lock:
            assert len(w115._tick_times) == 1
        assert w115.is_entry_blocked() is False

    # -- T4: update() alias works identically to record_tick --
    def test_update_alias(self):
        """update() functions identically to record_tick()."""
        w115.update()
        with w115._lock:
            assert len(w115._tick_times) == 1

    # -- T5: reset() clears all timestamps and active block --
    def test_reset_clears_state(self):
        """reset() restores unblocked empty state."""
        with w115._lock:
            w115._blocked_until = time.monotonic() + 100.0
            w115._tick_times.append(time.monotonic())
        assert w115.is_entry_blocked() is True
        w115.reset()
        assert w115.is_entry_blocked() is False
        with w115._lock:
            assert len(w115._tick_times) == 0
