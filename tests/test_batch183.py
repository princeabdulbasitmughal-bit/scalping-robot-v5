"""
tests/test_batch183.py
-----------------------
Unit tests for Batch 183 wave modules:
  - wave132_tick_run_length_guard              (5 tests)
  - wave133_rolling_beta_instability_guard     (5 tests)

Baseline before this batch: 2,074 collected items (2,073 passed, 1 skipped)
Expected after: 2,084 collected items (2,083 passed, 1 skipped)
"""

import math
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave132_tick_run_length_guard as w132
import wave133_rolling_beta_instability_guard as w133


# ===========================================================================
# wave132 — Microstructure Directional Run Length Guard (5 tests)
# ===========================================================================

class TestWave132TickRunLengthGuard:

    def setup_method(self):
        w132.reset()

    # -- T1: Alternating ticks do not build extended runs or block --
    def test_alternating_ticks_not_blocked(self):
        """Oscillating tick sequence resets run streak and does not block."""
        price = 100.0
        w132.record_tick(price)
        for _ in range(10):
            price += 1.0
            w132.record_tick(price)
            price -= 1.0
            w132.record_tick(price)

        assert abs(w132.get_current_run()) <= 1
        assert w132.is_entry_blocked() is False
        assert w132.is_blocked() is False

    # -- T2: 8 consecutive directional ticks trigger protective block --
    def test_monotonic_run_blocks(self):
        """8 strictly positive consecutive ticks trigger run length block."""
        price = 100.0
        w132.record_tick(price)
        for _ in range(8):
            price += 0.50
            w132.record_tick(price)

        assert w132.get_current_run() == 8
        assert w132.is_entry_blocked() is True

    # -- T3: Flat tick resets run streak to zero --
    def test_flat_tick_resets_run(self):
        """A flat tick (price == prev_price) breaks directional streak."""
        price = 100.0
        w132.record_tick(price)
        for _ in range(5):
            price += 0.50
            w132.record_tick(price)

        assert w132.get_current_run() == 5
        w132.record_tick(price)  # flat tick
        assert w132.get_current_run() == 0
        assert w132.is_entry_blocked() is False

    # -- T4: Invalid inputs safely ignored --
    def test_invalid_inputs_ignored(self):
        """Booleans, NaN, Inf, non-positive numbers do not affect state."""
        w132.record_tick(True)
        w132.record_tick(float("nan"))
        w132.record_tick(float("inf"))
        w132.record_tick(-10.0)
        w132.record_tick(0.0)

        with w132._lock:
            assert w132._prev_price is None
            assert w132._current_run == 0

    # -- T5: update() alias works and reset() clears all state --
    def test_update_alias_and_reset(self):
        """update() correctly increments negative run; reset() clears all."""
        price = 100.0
        w132.update(price)
        for _ in range(8):
            price -= 0.50
            w132.update(price)

        assert w132.get_current_run() == -8
        assert w132.is_entry_blocked() is True

        w132.reset()
        assert w132.get_current_run() == 0
        assert w132.is_entry_blocked() is False
        with w132._lock:
            assert w132._prev_price is None


# ===========================================================================
# wave133 — Rolling Beta Instability Guard (5 tests)
# ===========================================================================

class TestWave133RollingBetaInstabilityGuard:

    def setup_method(self):
        w133.reset()

    # -- T1: Normal co-movement with beta ~ 1.0 does not block --
    def test_stable_beta_not_blocked(self):
        """Proportional price moves maintain beta close to 1.0 without blocking."""
        pa = 100.0
        pb = 100.0
        w133.record_prices(pa, pb)

        # 18 moves where Asset A moves almost identical to Asset B
        for i in range(18):
            delta = 1.0 if (i % 2 == 0) else -1.0
            pa += delta
            pb += delta
            w133.record_prices(pa, pb)

        assert abs(w133.get_current_beta() - 1.0) < 0.20
        assert w133.is_entry_blocked() is False
        assert w133.is_blocked() is False

    # -- T2: Severe beta drift triggers protective block --
    def test_beta_drift_blocks(self):
        """Inverted/negative beta movement breaches MAX_BETA_DRIFT and blocks."""
        pa = 100.0
        pb = 100.0
        w133.record_prices(pa, pb)

        # 18 moves where Asset A moves INVERSELY to Asset B (beta ~ -1.0, drift = 2.0 >= 1.5)
        for i in range(18):
            delta = 1.0 if (i % 2 == 0) else -1.0
            pa -= delta
            pb += delta
            w133.record_prices(pa, pb)

        assert w133.get_current_beta() < 0.0
        assert w133.is_entry_blocked() is True

    # -- T3: update() alias works identically --
    def test_update_alias(self):
        """update() correctly routes dual prices and detects high beta multiplier."""
        pa = 100.0
        pb = 100.0
        w133.update(pa, pb)

        # Asset A moves 3x more aggressively than Asset B (beta ~ 3.0, drift = 2.0 >= 1.5)
        for i in range(18):
            delta = 0.5 if (i % 2 == 0) else -0.5
            pa += delta * 3.0
            pb += delta
            w133.update(pa, pb)

        assert w133.get_current_beta() > 2.5
        assert w133.is_entry_blocked() is True

    # -- T4: Invalid inputs for either price are safely ignored --
    def test_invalid_inputs_ignored(self):
        """Booleans, NaN, Inf, non-positive numbers in either asset ignored."""
        w133.record_prices(True, 100.0)
        w133.record_prices(100.0, False)
        w133.record_prices(float("nan"), 100.0)
        w133.record_prices(100.0, float("inf"))
        w133.record_prices(-50.0, 100.0)
        w133.record_prices(100.0, 0.0)

        with w133._lock:
            assert w133._prev_a is None
            assert len(w133._returns_a) == 0

    # -- T5: reset() clears all state and restores default beta --
    def test_reset_clears_state(self):
        """reset() empties return buffers, restores equilibrium beta, and unblocks."""
        pa = 100.0
        pb = 100.0
        w133.record_prices(pa, pb)
        for i in range(18):
            delta = 1.0 if (i % 2 == 0) else -1.0
            pa -= delta
            pb += delta
            w133.record_prices(pa, pb)
        assert w133.is_entry_blocked() is True

        w133.reset()
        assert w133.is_entry_blocked() is False
        assert w133.get_current_beta() == 1.0
        with w133._lock:
            assert w133._prev_a is None
            assert len(w133._returns_a) == 0
            assert w133._blocked_until == 0.0
