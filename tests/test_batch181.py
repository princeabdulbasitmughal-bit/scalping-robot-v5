"""
tests/test_batch181.py
-----------------------
Unit tests for Batch 181 wave modules:
  - wave128_tick_entropy_guard           (5 tests)
  - wave129_drawdown_staircase_guard     (5 tests)

Baseline before this batch: 2,054 collected items (2,053 passed, 1 skipped)
Expected after: 2,064 collected items (2,063 passed, 1 skipped)
"""

import math
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave128_tick_entropy_guard as w128
import wave129_drawdown_staircase_guard as w129


# ===========================================================================
# wave128 — Microstructure Tick Direction Shannon Entropy Guard (5 tests)
# ===========================================================================

class TestWave128TickEntropyGuard:

    def setup_method(self):
        w128.reset()

    # -- T1: Dispersed, high-entropy tick directions do not block --
    def test_high_entropy_ticks_not_blocked(self):
        """Evenly distributed upticks, downticks, and flat ticks produce high entropy and do not block."""
        price = 100.0
        # Feed 18 ticks cycling through up, down, flat
        steps = [1.0, -1.0, 0.0, 1.0, -1.0, 0.0, 1.0, -1.0, 0.0,
                 1.0, -1.0, 0.0, 1.0, -1.0, 0.0, 1.0, -1.0, 0.0]
        w128.record_tick(price)
        for s in steps:
            price += s
            w128.record_tick(price)

        assert w128.get_current_entropy() > 1.0
        assert w128.is_entry_blocked() is False
        assert w128.is_blocked() is False

    # -- T2: Monotonic or completely flat ticks yield low entropy and block --
    def test_low_entropy_ticks_block(self):
        """16 consecutive identical directional ticks produce near-zero entropy and block."""
        price = 100.0
        w128.record_tick(price)
        # All upticks (direction = 1 with 100% probability -> entropy = 0.0)
        for _ in range(16):
            price += 1.0
            w128.record_tick(price)

        assert w128.get_current_entropy() < 0.60
        assert w128.is_entry_blocked() is True

    # -- T3: update() functions as alias for record_tick --
    def test_update_alias(self):
        """update() alias correctly computes entropy and triggers block on flat price ticks."""
        price = 50.0
        w128.update(price)
        for _ in range(16):
            w128.update(price)  # flat ticks: diff == 0 -> direction = 0

        assert w128.get_current_entropy() < 0.60
        assert w128.is_entry_blocked() is True

    # -- T4: Invalid inputs safely ignored --
    def test_invalid_inputs_ignored(self):
        """Booleans, NaN, Inf, non-positive numbers do not corrupt state."""
        w128.record_tick(True)
        w128.record_tick(float("nan"))
        w128.record_tick(float("inf"))
        w128.record_tick(-50.0)
        w128.record_tick(0.0)

        with w128._lock:
            assert len(w128._directions) == 0
            assert w128._prev_price is None

    # -- T5: reset() clears all state and active block --
    def test_reset_clears_state(self):
        """reset() restores default entropy, empties history, and unblocks."""
        price = 100.0
        w128.record_tick(price)
        for _ in range(16):
            price += 1.0
            w128.record_tick(price)

        assert w128.is_entry_blocked() is True

        w128.reset()
        assert w128.is_entry_blocked() is False
        assert w128.get_current_entropy() == 1.585
        with w128._lock:
            assert len(w128._directions) == 0
            assert w128._prev_price is None


# ===========================================================================
# wave129 — Drawdown Staircase Guard (5 tests)
# ===========================================================================

class TestWave129DrawdownStaircaseGuard:

    def setup_method(self):
        w129.reset()

    # -- T1: Normal equity gains and flat equity do not block --
    def test_healthy_equity_not_blocked(self):
        """Rising equity without cascading lower peaks does not trigger block."""
        w129.record_equity(1000.0)
        w129.record_equity(1015.0)
        w129.record_equity(1030.0)
        w129.record_equity(1050.0)

        assert w129.is_entry_blocked() is False
        assert w129.is_blocked() is False

    # -- T2: 3 cascading lower peaks trigger staircase block --
    def test_staircase_lower_peaks_block(self):
        """Peak 1 (1000) -> Peak 2 (980) -> Peak 3 (960) triggers protective block."""
        # Baseline equity setup
        w129.record_equity(980.0)   # initial trough

        # Swing 1: bounce to 1000 (bounce >= 10), then roll back to 990 (rollback >= 5) -> Peak 1 = 1000
        w129.record_equity(1000.0)
        w129.record_equity(990.0)

        # Drop to 960 (trough), bounce to 980, roll back to 970 -> Peak 2 = 980
        w129.record_equity(960.0)
        w129.record_equity(980.0)
        w129.record_equity(970.0)

        # Drop to 940 (trough), bounce to 960, roll back to 950 -> Peak 3 = 960
        w129.record_equity(940.0)
        w129.record_equity(960.0)
        w129.record_equity(950.0)

        assert w129.get_staircase_count() == 3
        assert w129.is_entry_blocked() is True

    # -- T3: Breakout above highest recorded peak unblocks and clears staircase --
    def test_breakout_clears_staircase(self):
        """Equity breaking above the highest swing peak unblocks entries."""
        # Establish staircase of 3 lower peaks
        w129.record_equity(980.0)
        w129.record_equity(1000.0)
        w129.record_equity(990.0)

        w129.record_equity(960.0)
        w129.record_equity(980.0)
        w129.record_equity(970.0)

        w129.record_equity(940.0)
        w129.record_equity(960.0)
        w129.record_equity(950.0)

        assert w129.is_entry_blocked() is True

        # Breakout above Peak 1 (1000)
        w129.record_equity(1005.0)

        assert w129.is_entry_blocked() is False
        with w129._lock:
            assert len(w129._peaks) == 0

    # -- T4: update() works as alias for record_equity --
    def test_update_alias_and_peak_count(self):
        """update() correctly registers equity updates and counts peaks."""
        w129.update(980.0)
        w129.update(1000.0)
        w129.update(990.0)
        assert w129.get_staircase_count() == 1

        w129.update(960.0)
        w129.update(980.0)
        w129.update(970.0)
        assert w129.get_staircase_count() == 2

    # -- T5: Invalid inputs ignored and reset() clears all state --
    def test_invalid_inputs_and_reset(self):
        """Booleans, NaN, Inf are ignored; reset() clears all tracking."""
        w129.record_equity(True)
        w129.record_equity(float("nan"))
        w129.record_equity(float("inf"))

        with w129._lock:
            assert w129._trough is None

        # Create staircase and verify reset() clears it
        w129.record_equity(980.0)
        w129.record_equity(1000.0)
        w129.record_equity(990.0)
        w129.record_equity(960.0)
        w129.record_equity(980.0)
        w129.record_equity(970.0)
        w129.record_equity(940.0)
        w129.record_equity(960.0)
        w129.record_equity(950.0)
        assert w129.is_entry_blocked() is True

        w129.reset()
        assert w129.is_entry_blocked() is False
        with w129._lock:
            assert w129._trough is None
            assert len(w129._peaks) == 0
            assert w129._blocked_until == 0.0
