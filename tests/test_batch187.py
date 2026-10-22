"""
tests/test_batch187.py
-----------------------
Unit tests for Batch 187 wave modules:
  - wave140_order_imbalance_acceleration_guard    (5 tests)
  - wave141_spectral_entropy_guard                (5 tests)

Baseline before this batch: 2,114 collected items (2,113 passed, 1 skipped)
Expected after: 2,124 collected items (2,123 passed, 1 skipped)
"""

import math
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave140_order_imbalance_acceleration_guard as w140
import wave141_spectral_entropy_guard as w141


# ===========================================================================
# wave140 — Order Flow CVD Delta Acceleration Guard (5 tests)
# ===========================================================================

class TestWave140OrderImbalanceAccelerationGuard:

    def setup_method(self):
        w140.reset()

    # -- T1: Steady trade volume arrival produces zero acceleration and does not block --
    def test_steady_flow_not_blocked(self):
        """Constant trade arrival velocity yields accel ~= 0 and does not block."""
        t0 = 1000.0
        w140.record_delta(1.0, ts=t0)
        # 1 lot every 1.0 second: velocity = 1.0, acceleration = 0.0
        for i in range(1, 10):
            w140.record_delta(1.0, ts=t0 + i * 1.0)

        assert abs(w140.get_current_acceleration()) < 1.0
        assert w140.is_entry_blocked() is False
        assert w140.is_blocked() is False

    # -- T2: Violent surge in delta volume arrival triggers acceleration block --
    def test_acceleration_spike_blocks(self):
        """Sudden leap from steady flow to 50 lots in 0.5s creates huge acceleration and blocks."""
        t0 = 1000.0
        w140.record_delta(1.0, ts=t0)
        w140.record_delta(1.0, ts=t0 + 1.0)  # v = 1.0 lot/s

        # Violent surge: 25 lots in 0.5s -> v = 50.0 lots/s -> a = (50 - 1) / 0.5 = 98.0 lots/s^2 >= 5.0
        w140.record_delta(25.0, ts=t0 + 1.5)

        assert abs(w140.get_current_acceleration()) >= 5.0
        assert w140.is_entry_blocked() is True

    # -- T3: update() alias works and detects negative acceleration sweep --
    def test_update_alias_and_negative_accel(self):
        """update() correctly processes sell volume acceleration spike."""
        t0 = 1000.0
        w140.update(-1.0, ts=t0)
        w140.update(-1.0, ts=t0 + 1.0)
        w140.update(-30.0, ts=t0 + 1.5)  # huge aggressive sell sweep

        assert abs(w140.get_current_acceleration()) >= 5.0
        assert w140.is_entry_blocked() is True

    # -- T4: Invalid inputs safely ignored --
    def test_invalid_inputs_ignored(self):
        """Booleans, NaN, Inf do not corrupt state."""
        w140.record_delta(True)
        w140.record_delta(float("nan"))
        w140.record_delta(float("inf"))

        with w140._lock:
            assert w140._prev_time is None
            assert w140._current_acceleration == 0.0

    # -- T5: reset() clears all state and unblocks --
    def test_reset_clears_state(self):
        """reset() clears velocity, acceleration, and unblocks."""
        t0 = 1000.0
        w140.record_delta(1.0, ts=t0)
        w140.record_delta(1.0, ts=t0 + 1.0)
        w140.record_delta(25.0, ts=t0 + 1.5)
        assert w140.is_entry_blocked() is True

        w140.reset()
        assert w140.is_entry_blocked() is False
        assert w140.get_current_acceleration() == 0.0
        with w140._lock:
            assert w140._prev_time is None
            assert w140._blocked_until == 0.0


# ===========================================================================
# wave141 — Fourier Transform Spectral Entropy Guard (5 tests)
# ===========================================================================

class TestWave141SpectralEntropyGuard:

    def setup_method(self):
        w141.reset()

    # -- T1: Broadband white-noise returns yield high SE and do not block --
    def test_broadband_returns_not_blocked(self):
        """Dispersed return spectrum yields SE >= 0.55 and does not block."""
        price = 100.0
        w141.record_price(price)
        # Varied broadband returns
        steps = [0.1, -0.2, 0.3, 0.1, -0.1, 0.2, -0.3, 0.2,
                 -0.1, 0.3, -0.2, 0.1, -0.1, 0.2, -0.2, 0.1]
        for s in steps:
            price += s
            w141.record_price(price)

        se = w141.get_spectral_entropy()
        assert se >= 0.55
        assert w141.is_entry_blocked() is False
        assert w141.is_blocked() is False

    # -- T2: Periodic harmonic cycles collapse SE < 0.55 and block --
    def test_harmonic_cycle_blocks(self):
        """Sinusoidal quote cycle concentrates power in single frequency bin and blocks."""
        price = 100.0
        w141.record_price(price)
        # Discrete sine wave with period 8 (k = 2 in N = 16)
        for i in range(16):
            ret = 0.005 * math.sin(2.0 * math.pi * 2 * i / 16)
            price *= (1.0 + ret)
            w141.record_price(price)

        se = w141.get_spectral_entropy()
        assert se < 0.55
        assert w141.is_entry_blocked() is True

    # -- T3: update() alias works identically --
    def test_update_alias(self):
        """update() functions identically and triggers block on cyclic quote oscillation."""
        price = 100.0
        w141.update(price)
        for i in range(16):
            ret = 0.005 * math.sin(2.0 * math.pi * 2 * i / 16)
            price *= (1.0 + ret)
            w141.update(price)

        assert w141.get_spectral_entropy() < 0.55
        assert w141.is_entry_blocked() is True

    # -- T4: Invalid inputs safely ignored --
    def test_invalid_inputs_ignored(self):
        """Booleans, NaN, Inf, non-positive numbers do not corrupt state."""
        w141.record_price(True)
        w141.record_price(float("nan"))
        w141.record_price(float("inf"))
        w141.record_price(-10.0)
        w141.record_price(0.0)

        with w141._lock:
            assert w141._prev_price is None
            assert len(w141._returns) == 0

    # -- T5: reset() restores default spectral entropy (1.0) and unblocks --
    def test_reset_clears_state(self):
        """reset() empties return buffer, restores default SE (1.0), and unblocks."""
        price = 100.0
        w141.record_price(price)
        for i in range(16):
            ret = 0.005 * math.sin(2.0 * math.pi * 2 * i / 16)
            price *= (1.0 + ret)
            w141.record_price(price)
        assert w141.is_entry_blocked() is True

        w141.reset()
        assert w141.is_entry_blocked() is False
        assert w141.get_spectral_entropy() == 1.0
        with w141._lock:
            assert w141._prev_price is None
            assert len(w141._returns) == 0
            assert w141._blocked_until == 0.0
