"""
tests/test_batch173.py
-----------------------
Unit tests for Batch 173 wave modules:
  - wave112_drawdown_duration_guard     (5 tests)
  - wave113_max_consecutive_ticks_guard (5 tests)

Baseline before this batch: 1,974 collected items
Expected after: 1,984 collected items
"""

import math
import time
import threading
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave112_drawdown_duration_guard as w112
import wave113_max_consecutive_ticks_guard as w113


# ===========================================================================
# wave112 — Prolonged Drawdown Duration Guard (5 tests)
# ===========================================================================

class TestWave112DrawdownDurationGuard:

    def setup_method(self):
        w112.reset()

    # -- T1: Initial equity sets HWM; not blocked --
    def test_initial_equity_sets_hwm(self):
        """First equity value sets HWM baseline and must not block."""
        w112.update(10000.0)
        assert w112.is_entry_blocked() is False
        assert w112._hwm == 10000.0

    # -- T2: New HWM resets underwater timer --
    def test_new_hwm_clears_underwater_timer(self):
        """Reaching or exceeding previous HWM clears underwater timer."""
        w112.update(10000.0)
        w112.update(9500.0)   # underwater starts
        assert w112._underwater_since > 0.0

        w112.update(10500.0)  # new peak
        assert w112._hwm == 10500.0
        assert w112._underwater_since == -1.0
        assert w112.is_entry_blocked() is False

    # -- T3: Blocked when continuously underwater > MAX_UNDERWATER_SECONDS --
    def test_blocked_prolonged_underwater(self):
        """Being underwater longer than MAX_UNDERWATER_SECONDS triggers block."""
        w112.update(10000.0)
        w112.update(9800.0)

        # Simulate prolonged underwater duration
        with w112._lock:
            w112._underwater_since = time.monotonic() - (w112.MAX_UNDERWATER_SECONDS + 10.0)

        # Trigger check with another update
        w112.update(9750.0)
        assert w112.is_entry_blocked() is True

    # -- T4: Not blocked during brief drawdown --
    def test_not_blocked_brief_drawdown(self):
        """Brief dip in equity well below duration limit must not block."""
        w112.update(10000.0)
        w112.update(9900.0)
        assert w112.is_entry_blocked() is False

    # -- T5: Invalid inputs ignored; reset() clears all state --
    def test_invalid_inputs_and_reset(self):
        """Invalid inputs rejected; reset() clears HWM and block status."""
        w112.update(True)
        w112.update(float("nan"))
        w112.update(-100.0)
        w112.update("10000")
        assert w112._hwm == 0.0

        # Trigger block then reset
        with w112._lock:
            w112._blocked_until = time.monotonic() + 500.0
        assert w112.is_entry_blocked() is True
        w112.reset()
        assert w112.is_entry_blocked() is False
        assert w112._hwm == 0.0
        assert w112._underwater_since == -1.0


# ===========================================================================
# wave113 — Consecutive Directional Tick Run Guard (5 tests)
# ===========================================================================

class TestWave113MaxConsecutiveTicksGuard:

    def setup_method(self):
        w113.reset()

    # -- T1: Normal oscillating ticks do not block --
    def test_oscillating_ticks_not_blocked(self):
        """Normal bidirectional ticks reset run counter and do not block."""
        prices = [100.0, 100.1, 100.0, 100.2, 100.1, 100.3]
        for p in prices:
            w113.update(p)
        assert w113.is_entry_blocked() is False

    # -- T2: 8 consecutive up-ticks triggers block --
    def test_consecutive_up_ticks_blocked(self):
        """8 consecutive higher ticks reaches MAX_CONSECUTIVE_RUN and blocks."""
        w113.update(100.0)  # baseline
        for i in range(1, 9):
            w113.update(100.0 + i * 0.1)
        assert w113.is_entry_blocked() is True

    # -- T3: 8 consecutive down-ticks triggers block --
    def test_consecutive_down_ticks_blocked(self):
        """8 consecutive lower ticks reaches MAX_CONSECUTIVE_RUN and blocks."""
        w113.update(200.0)  # baseline
        for i in range(1, 9):
            w113.update(200.0 - i * 0.1)
        assert w113.is_entry_blocked() is True

    # -- T4: Reversal resets run counter --
    def test_run_reversal_resets_count(self):
        """A tick in the opposite direction resets the run counter."""
        w113.update(100.0)
        for i in range(1, 6):  # 5 up-ticks
            w113.update(100.0 + i * 0.1)
        w113.update(100.4)     # 1 down-tick: reverses direction
        assert w113._current_direction == -1
        assert w113._run_count == 1
        assert w113.is_entry_blocked() is False

    # -- T5: Invalid inputs ignored; reset() clears all state --
    def test_invalid_inputs_and_reset(self):
        """Booleans, NaN, Inf, and non-positive prices ignored; reset() clears."""
        w113.update(True)
        w113.update(float("nan"))
        w113.update(float("inf"))
        w113.update(-5.0)
        assert w113._last_price == -1.0

        # Force block then reset
        with w113._lock:
            w113._blocked_until = time.monotonic() + 100.0
        assert w113.is_entry_blocked() is True
        w113.reset()
        assert w113.is_entry_blocked() is False
        assert w113._last_price == -1.0
        assert w113._run_count == 0
