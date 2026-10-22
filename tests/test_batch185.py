"""
tests/test_batch185.py
-----------------------
Unit tests for Batch 185 wave modules:
  - wave136_autocorrelation_shock_guard        (5 tests)
  - wave137_skewness_fat_tail_guard            (5 tests)

Baseline before this batch: 2,094 collected items (2,093 passed, 1 skipped)
Expected after: 2,104 collected items (2,103 passed, 1 skipped)
"""

import math
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave136_autocorrelation_shock_guard as w136
import wave137_skewness_fat_tail_guard as w137


# ===========================================================================
# wave136 — Lag-1 Tick Return Autocorrelation Shock Guard (5 tests)
# ===========================================================================

class TestWave136AutocorrelationShockGuard:

    def setup_method(self):
        w136.reset()

    # -- T1: Normal mild negative autocorrelation does not block --
    def test_normal_autocorrelation_not_blocked(self):
        """Natural mixed tick directions maintain mild correlation (-0.33) and do not block."""
        price = 100.0
        w136.record_tick(price)
        # Moderate balanced movement with normal mild bounce
        steps = [0.1, 0.1, -0.1, 0.1, -0.1, -0.1, 0.1, -0.1, 0.1, 0.1,
                 -0.1, -0.1, 0.1, 0.1, -0.1, 0.1, -0.1, -0.1, 0.1]
        for s in steps:
            price += s
            w136.record_tick(price)

        rho = w136.get_current_autocorrelation()
        assert -0.70 < rho < 0.40
        assert w136.is_entry_blocked() is False
        assert w136.is_blocked() is False

    # -- T2: Strong positive momentum autocorrelation blocks --
    def test_positive_autocorrelation_blocks(self):
        """Serial positive momentum continuation (rho >= 0.40) triggers block."""
        price = 100.0
        w136.record_tick(price)
        # Persistent escalating runs of 2-3 ticks in same direction
        steps = [0.1, 0.2, 0.3, -0.1, -0.2, -0.3] * 4
        for s in steps:
            price += s
            w136.record_tick(price)

        rho = w136.get_current_autocorrelation()
        assert rho >= 0.40
        assert w136.is_entry_blocked() is True

    # -- T3: Hyper-negative ping-pong whipsaw autocorrelation blocks --
    def test_hyper_negative_autocorrelation_blocks(self):
        """Alternating tick sequence produces rho <= -0.70 and triggers block."""
        price = 100.0
        w136.record_tick(price)
        # Strict ping-pong alternating: +0.2, -0.2, +0.2, -0.2
        for i in range(20):
            delta = 0.2 if (i % 2 == 0) else -0.2
            price += delta
            w136.record_tick(price)

        rho = w136.get_current_autocorrelation()
        assert rho <= -0.70
        assert w136.is_entry_blocked() is True

    # -- T4: Invalid inputs safely ignored --
    def test_invalid_inputs_ignored(self):
        """Booleans, NaN, Inf, non-positive numbers do not corrupt state."""
        w136.record_tick(True)
        w136.record_tick(float("nan"))
        w136.record_tick(float("inf"))
        w136.record_tick(-50.0)
        w136.record_tick(0.0)

        with w136._lock:
            assert w136._prev_price is None
            assert len(w136._returns) == 0

    # -- T5: update() alias works and reset() clears all state --
    def test_update_alias_and_reset(self):
        """update() functions identically; reset() restores default rho and unblocks."""
        price = 100.0
        w136.update(price)
        for i in range(20):
            delta = 0.2 if (i % 2 == 0) else -0.2
            price += delta
            w136.update(price)

        assert w136.is_entry_blocked() is True

        w136.reset()
        assert w136.is_entry_blocked() is False
        assert w136.get_current_autocorrelation() == -0.10
        with w136._lock:
            assert w136._prev_price is None
            assert len(w136._returns) == 0


# ===========================================================================
# wave137 — Microstructure Return Skewness & Tail Asymmetry Guard (5 tests)
# ===========================================================================

class TestWave137SkewnessFatTailGuard:

    def setup_method(self):
        w137.reset()

    # -- T1: Symmetric price moves produce low skewness and do not block --
    def test_symmetric_moves_not_blocked(self):
        """Balanced positive and negative returns maintain low skewness."""
        price = 100.0
        w137.record_tick(price)
        # Evenly balanced steps
        for i in range(20):
            delta = 0.10 if (i % 2 == 0) else -0.10
            price += delta
            w137.record_tick(price)

        assert abs(w137.get_current_skewness()) < 1.0
        assert w137.is_entry_blocked() is False
        assert w137.is_blocked() is False

    # -- T2: Outlier flash crash step drives negative skewness and blocks --
    def test_negative_skewness_blocks(self):
        """A single massive downward outlier creates extreme negative skew (|skew| >= 2.50)."""
        price = 100.0
        w137.record_tick(price)
        # 18 tiny upward / neutral steps
        for _ in range(18):
            price += 0.02
            w137.record_tick(price)

        # Huge sudden negative shock
        price -= 2.00
        w137.record_tick(price)

        skew = w137.get_current_skewness()
        assert skew <= -2.50
        assert w137.is_entry_blocked() is True

    # -- T3: Outlier flash squeeze jump drives positive skewness and blocks --
    def test_positive_skewness_blocks(self):
        """A single massive upward outlier creates extreme positive skew (skew >= 2.50)."""
        price = 100.0
        w137.record_tick(price)
        # 18 tiny downward steps
        for _ in range(18):
            price -= 0.02
            w137.record_tick(price)

        # Huge sudden positive squeeze jump
        price += 2.00
        w137.record_tick(price)

        skew = w137.get_current_skewness()
        assert skew >= 2.50
        assert w137.is_entry_blocked() is True

    # -- T4: Invalid inputs safely ignored --
    def test_invalid_inputs_ignored(self):
        """Booleans, NaN, Inf, non-positive numbers do not corrupt state."""
        w137.record_tick(True)
        w137.record_tick(float("nan"))
        w137.record_tick(float("inf"))
        w137.record_tick(-10.0)
        w137.record_tick(0.0)

        with w137._lock:
            assert w137._prev_price is None
            assert len(w137._returns) == 0

    # -- T5: update() alias works and reset() clears all state --
    def test_update_alias_and_reset(self):
        """update() correctly evaluates returns; reset() zeroes skewness and unblocks."""
        price = 100.0
        w137.update(price)
        for _ in range(18):
            price += 0.02
            w137.update(price)
        price -= 2.00
        w137.update(price)
        assert w137.is_entry_blocked() is True

        w137.reset()
        assert w137.is_entry_blocked() is False
        assert w137.get_current_skewness() == 0.0
        with w137._lock:
            assert w137._prev_price is None
            assert len(w137._returns) == 0
            assert w137._blocked_until == 0.0
