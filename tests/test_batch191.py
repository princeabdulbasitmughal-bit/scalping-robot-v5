"""
tests/test_batch191.py
-----------------------
Unit tests for Batch 191 wave modules:
  - wave148_microstructure_resiliency_guard       (5 tests)
  - wave149_tick_volatility_clustering_guard      (5 tests)

Baseline before this batch: 2,154 collected items (2,153 passed, 1 skipped)
Expected after: 2,164 collected items (2,163 passed, 1 skipped)
"""

import math
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave148_microstructure_resiliency_guard as w148
import wave149_tick_volatility_clustering_guard as w149


# ===========================================================================
# wave148 — Order Book Resiliency & Replenishment Latency Guard (5 tests)
# ===========================================================================

class TestWave148MicrostructureResiliencyGuard:

    def setup_method(self):
        w148.reset()

    # -- T1: Normal depth and fast replenishment do not block --
    def test_fast_replenishment_not_blocked(self):
        """When depth drops but recovers to >= 50% within 2s, no block is triggered."""
        t0 = 1000.0
        # Baseline depth = 10 lots
        w148.record_depth(5.0, 5.0, ts=t0)

        # Shock at t = 1001.0: depth drops to 3 lots (< 4.0 = 40% of 10)
        w148.record_depth(1.5, 1.5, ts=t0 + 1.0)
        assert w148.is_entry_blocked() is False

        # Fast recovery at t = 1001.5 (0.5s later): depth bounces to 8 lots (>= 5.0)
        w148.record_depth(4.0, 4.0, ts=t0 + 1.5)

        assert w148.is_entry_blocked() is False
        assert w148.is_blocked() is False

    # -- T2: Lingering unreplenished depth triggers resiliency block --
    def test_resiliency_failure_blocks(self):
        """Depth dropping < 40% and remaining < 50% for >= 2.0s triggers block."""
        t0 = 1000.0
        w148.record_depth(5.0, 5.0, ts=t0)          # baseline = 10.0

        # Shock at t = 1001.0: drops to 2.0 lots
        w148.record_depth(1.0, 1.0, ts=t0 + 1.0)

        # Still drained 2.5s later at t = 1003.5: depth is still only 2.0 lots
        w148.record_depth(1.0, 1.0, ts=t0 + 3.5)

        assert w148.is_entry_blocked() is True

    # -- T3: update() alias works identically --
    def test_update_alias(self):
        """update() correctly evaluates resiliency latency."""
        t0 = 1000.0
        w148.update(5.0, 5.0, ts=t0)
        w148.update(1.0, 1.0, ts=t0 + 1.0)
        w148.update(1.0, 1.0, ts=t0 + 3.5)

        assert w148.is_entry_blocked() is True

    # -- T4: Invalid inputs safely ignored --
    def test_invalid_inputs_ignored(self):
        """Booleans, NaN, Inf, negative numbers do not corrupt state."""
        w148.record_depth(True, 5.0)
        w148.record_depth(5.0, False)
        w148.record_depth(float("nan"), 5.0)
        w148.record_depth(5.0, float("inf"))
        w148.record_depth(-5.0, 5.0)
        w148.record_depth(0.0, 0.0)

        assert w148.get_resiliency_ratio() == 1.0

    # -- T5: reset() clears all state and unblocks --
    def test_reset_clears_state(self):
        """reset() clears shock timers, restores baseline, and unblocks."""
        t0 = 1000.0
        w148.record_depth(5.0, 5.0, ts=t0)
        w148.record_depth(1.0, 1.0, ts=t0 + 1.0)
        w148.record_depth(1.0, 1.0, ts=t0 + 3.5)
        assert w148.is_entry_blocked() is True

        w148.reset()
        assert w148.is_entry_blocked() is False
        assert w148.get_resiliency_ratio() == 1.0
        with w148._lock:
            assert w148._shock_timestamp is None
            assert w148._blocked_until == 0.0


# ===========================================================================
# wave149 — ARCH Volatility Clustering Guard (5 tests)
# ===========================================================================

class TestWave149TickVolatilityClusteringGuard:

    def setup_method(self):
        w149.reset()

    # -- T1: Constant/independent variance does not block --
    def test_independent_variance_not_blocked(self):
        """Uniformly noisy price series has zero ARCH correlation and does not block."""
        price = 100.0
        w149.record_tick(price)
        # Uniform magnitude steps of 0.10: R^2 is constant -> correlation = 0.0
        for i in range(20):
            delta = 0.10 if (i % 2 == 0) else -0.10
            price += delta
            w149.record_tick(price)

        corr = w149.get_volatility_clustering_corr()
        assert corr < 0.50
        assert w149.is_entry_blocked() is False
        assert w149.is_blocked() is False

    # -- T2: Strong volatility clustering triggers protective block --
    def test_volatility_clustering_blocks(self):
        """Consecutive large jumps followed by consecutive tiny steps create strong ARCH clustering."""
        price = 100.0
        w149.record_tick(price)
        # Bursts of large returns (8 large steps) followed by quiet regimes (8 tiny steps)
        # Repeats to produce high serial persistence in R^2
        steps = [1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0,
                 0.01, -0.01, 0.01, -0.01, 0.01, -0.01, 0.01, -0.01,
                 1.0, -1.0, 1.0, -1.0]
        for s in steps:
            price += s
            w149.record_tick(price)

        corr = w149.get_volatility_clustering_corr()
        assert corr >= 0.50
        assert w149.is_entry_blocked() is True

    # -- T3: update() alias works identically --
    def test_update_alias(self):
        """update() correctly evaluates ARCH clustering on squared returns."""
        price = 100.0
        w149.update(price)
        steps = [1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0,
                 0.01, -0.01, 0.01, -0.01, 0.01, -0.01, 0.01, -0.01,
                 1.0, -1.0, 1.0, -1.0]
        for s in steps:
            price += s
            w149.update(price)

        assert w149.get_volatility_clustering_corr() >= 0.50
        assert w149.is_entry_blocked() is True

    # -- T4: Invalid inputs safely ignored --
    def test_invalid_inputs_ignored(self):
        """Booleans, NaN, Inf, non-positive numbers do not corrupt state."""
        w149.record_tick(True)
        w149.record_tick(float("nan"))
        w149.record_tick(float("inf"))
        w149.record_tick(-50.0)
        w149.record_tick(0.0)

        with w149._lock:
            assert w149._prev_price is None
            assert len(w149._sq_returns) == 0

    # -- T5: reset() clears all state and unblocks --
    def test_reset_clears_state(self):
        """reset() empties return buffer, zeroes correlation, and unblocks."""
        price = 100.0
        w149.record_tick(price)
        steps = [1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0,
                 0.01, -0.01, 0.01, -0.01, 0.01, -0.01, 0.01, -0.01,
                 1.0, -1.0, 1.0, -1.0]
        for s in steps:
            price += s
            w149.record_tick(price)
        assert w149.is_entry_blocked() is True

        w149.reset()
        assert w149.is_entry_blocked() is False
        assert w149.get_volatility_clustering_corr() == 0.0
        with w149._lock:
            assert w149._prev_price is None
            assert len(w149._sq_returns) == 0
            assert w149._blocked_until == 0.0
