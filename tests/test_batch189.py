"""
tests/test_batch189.py
-----------------------
Unit tests for Batch 189 wave modules:
  - wave144_quote_stuffing_burst_guard           (5 tests)
  - wave145_drawdown_velocity_expansion_guard    (5 tests)

Baseline before this batch: 2,134 collected items (2,133 passed, 1 skipped)
Expected after: 2,144 collected items (2,143 passed, 1 skipped)
"""

import math
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave144_quote_stuffing_burst_guard as w144
import wave145_drawdown_velocity_expansion_guard as w145


# ===========================================================================
# wave144 — Order Book Quote Stuffing Burst Guard (5 tests)
# ===========================================================================

class TestWave144QuoteStuffingBurstGuard:

    def setup_method(self):
        w144.reset()

    # -- T1: Normal quote frequency does not block --
    def test_normal_frequency_not_blocked(self):
        """Moderate quote updates (5 per second) yield rate < 40 and do not block."""
        t0 = 1000.0
        for i in range(5):
            w144.record_quote(1.0000, 1.0002, ts=t0 + i * 0.20)

        assert w144.get_current_quote_rate() < 10.0
        assert w144.is_entry_blocked() is False
        assert w144.is_blocked() is False

    # -- T2: Extreme burst of 45 quotes within 1s triggers block --
    def test_quote_stuffing_blocks(self):
        """High-frequency quote update burst exceeding 40 quotes/sec triggers block."""
        t0 = 1000.0
        # 45 quotes in 0.9 seconds
        for i in range(45):
            w144.record_quote(1.0000, 1.0002, ts=t0 + i * 0.02)

        assert w144.get_current_quote_rate() >= 40.0
        assert w144.is_entry_blocked() is True

    # -- T3: update() alias works identically and provides rate --
    def test_update_alias_and_rate(self):
        """update() functions identically to record_quote()."""
        t0 = 1000.0
        for i in range(42):
            w144.update(1.0000, 1.0002, ts=t0 + i * 0.02)

        assert w144.get_current_quote_rate() >= 40.0
        assert w144.is_entry_blocked() is True

    # -- T4: Crossed quotes or invalid numbers safely rejected --
    def test_invalid_and_crossed_quotes_rejected(self):
        """ask <= bid or invalid numbers are ignored."""
        w144.record_quote(1.0005, 1.0000)  # crossed
        w144.record_quote(1.0000, 1.0000)  # locked
        w144.record_quote(True, 1.0002)
        w144.record_quote(1.0000, False)
        w144.record_quote(float("nan"), 1.0002)
        w144.record_quote(1.0000, float("inf"))
        w144.record_quote(-1.0, 1.0002)

        with w144._lock:
            assert len(w144._timestamps) == 0

    # -- T5: reset() clears all state and unblocks --
    def test_reset_clears_state(self):
        """reset() clears timestamps, unblocks, and restores rate to 1.0."""
        t0 = 1000.0
        for i in range(45):
            w144.record_quote(1.0000, 1.0002, ts=t0 + i * 0.02)
        assert w144.is_entry_blocked() is True

        w144.reset()
        assert w144.is_entry_blocked() is False
        assert w144.get_current_quote_rate() == 1.0
        with w144._lock:
            assert len(w144._timestamps) == 0
            assert w144._blocked_until == 0.0


# ===========================================================================
# wave145 — Drawdown Velocity Expansion & Acceleration Guard (5 tests)
# ===========================================================================

class TestWave145DrawdownVelocityExpansionGuard:

    def setup_method(self):
        w145.reset()

    # -- T1: Steady equity gains or flat equity do not block --
    def test_healthy_equity_not_blocked(self):
        """Rising equity produces zero drawdown and does not block."""
        t0 = 1000.0
        w145.record_equity(1000.0, ts=t0)
        w145.record_equity(1010.0, ts=t0 + 1.0)
        w145.record_equity(1020.0, ts=t0 + 2.0)

        assert w145.get_drawdown_acceleration() == 0.0
        assert w145.is_entry_blocked() is False
        assert w145.is_blocked() is False

    # -- T2: Sudden accelerating drop triggers protective block --
    def test_drawdown_acceleration_blocks(self):
        """Loss velocity accelerating >= 4.0 USD/s^2 triggers block."""
        t0 = 1000.0
        w145.record_equity(1000.0, ts=t0)         # HWM = 1000
        w145.record_equity(999.0, ts=t0 + 1.0)     # dd = 1.0, v = 1.0 USD/s

        # Sudden steep cliff: equity drops from 999 to 980 in 0.5s
        # dd = 20.0, dt = 0.5, v = (20 - 1) / 0.5 = 38.0 USD/s
        # a = (38.0 - 1.0) / 0.5 = 74.0 USD/s^2 >= 4.0
        w145.record_equity(980.0, ts=t0 + 1.5)

        assert w145.get_drawdown_acceleration() >= 4.0
        assert w145.is_entry_blocked() is True

    # -- T3: update() alias works and tracks acceleration --
    def test_update_alias(self):
        """update() correctly routes equity snapshots."""
        t0 = 1000.0
        w145.update(1000.0, ts=t0)
        w145.update(999.0, ts=t0 + 1.0)
        w145.update(980.0, ts=t0 + 1.5)

        assert w145.get_drawdown_acceleration() >= 4.0
        assert w145.is_entry_blocked() is True

    # -- T4: Invalid inputs safely ignored --
    def test_invalid_inputs_ignored(self):
        """Booleans, NaN, Inf do not corrupt state."""
        w145.record_equity(True)
        w145.record_equity(float("nan"))
        w145.record_equity(float("inf"))

        with w145._lock:
            assert w145._hwm is None
            assert w145._current_acceleration == 0.0

    # -- T5: reset() clears all state and unblocks --
    def test_reset_clears_state(self):
        """reset() zeroes HWM, acceleration, and clears active block."""
        t0 = 1000.0
        w145.record_equity(1000.0, ts=t0)
        w145.record_equity(999.0, ts=t0 + 1.0)
        w145.record_equity(980.0, ts=t0 + 1.5)
        assert w145.is_entry_blocked() is True

        w145.reset()
        assert w145.is_entry_blocked() is False
        assert w145.get_drawdown_acceleration() == 0.0
        with w145._lock:
            assert w145._hwm is None
            assert w145._prev_time is None
            assert w145._blocked_until == 0.0
