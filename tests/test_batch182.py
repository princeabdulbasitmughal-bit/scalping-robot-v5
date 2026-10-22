"""
tests/test_batch182.py
-----------------------
Unit tests for Batch 182 wave modules:
  - wave130_volume_clock_tick_guard           (5 tests)
  - wave131_cross_market_lead_lag_guard       (5 tests)

Baseline before this batch: 2,064 collected items (2,063 passed, 1 skipped)
Expected after: 2,074 collected items (2,073 passed, 1 skipped)
"""

import math
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave130_volume_clock_tick_guard as w130
import wave131_cross_market_lead_lag_guard as w131


# ===========================================================================
# wave130 — Volume Clock Trade Volume Acceleration Guard (5 tests)
# ===========================================================================

class TestWave130VolumeClockTickGuard:

    def setup_method(self):
        w130.reset()

    # -- T1: Steady volume rate does not block --
    def test_steady_volume_not_blocked(self):
        """Uniform volume execution yields surge ratio ~ 1.0 and does not block."""
        t0 = 1000.0
        # Feed 1 lot every 2 seconds for 50 seconds
        for i in range(25):
            w130.record_volume(1.0, ts=t0 + i * 2.0)

        assert w130.get_volume_surge_ratio() < 2.0
        assert w130.is_entry_blocked() is False
        assert w130.is_blocked() is False

    # -- T2: Extreme volume surge triggers block --
    def test_volume_surge_blocks(self):
        """A burst of volume over short window exceeding 4x baseline triggers block."""
        t0 = 1000.0
        # Establish baseline: 0.2 lots/sec over 50 seconds
        for i in range(25):
            w130.record_volume(0.4, ts=t0 + i * 2.0)

        # Sudden surge: 50 lots within 5 seconds
        w130.record_volume(50.0, ts=t0 + 52.0)

        assert w130.get_volume_surge_ratio() >= 4.0
        assert w130.is_entry_blocked() is True

    # -- T3: update() alias works identically and provides surge ratio --
    def test_update_alias_and_ratio(self):
        """update() alias functions identically to record_volume()."""
        t0 = 1000.0
        for i in range(25):
            w130.update(0.4, ts=t0 + i * 2.0)
        w130.update(60.0, ts=t0 + 52.0)

        assert w130.get_volume_surge_ratio() >= 4.0
        assert w130.is_entry_blocked() is True

    # -- T4: Invalid inputs safely ignored --
    def test_invalid_inputs_ignored(self):
        """Booleans, NaN, Inf, non-positive volumes do not corrupt state."""
        w130.record_volume(True)
        w130.record_volume(float("nan"))
        w130.record_volume(float("inf"))
        w130.record_volume(-5.0)
        w130.record_volume(0.0)

        with w130._lock:
            assert len(w130._history) == 0

    # -- T5: reset() clears all state and unblocks --
    def test_reset_clears_state(self):
        """reset() empties history, unblocks, and resets ratio to 1.0."""
        t0 = 1000.0
        for i in range(25):
            w130.record_volume(0.4, ts=t0 + i * 2.0)
        w130.record_volume(50.0, ts=t0 + 52.0)
        assert w130.is_entry_blocked() is True

        w130.reset()
        assert w130.is_entry_blocked() is False
        assert w130.get_volume_surge_ratio() == 1.0
        with w130._lock:
            assert len(w130._history) == 0
            assert w130._blocked_until == 0.0


# ===========================================================================
# wave131 — Cross-Asset Lead-Lag Divergence Z-Score Guard (5 tests)
# ===========================================================================

class TestWave131CrossMarketLeadLagGuard:

    def setup_method(self):
        w131.reset()

    # -- T1: Cointegrated, steady pair prices do not block --
    def test_cointegrated_pair_not_blocked(self):
        """Prices maintaining stable ratio do not exceed z-score threshold."""
        # Pair ratio roughly constant ~ 1.05 with minor noise
        for i in range(20):
            pa = 100.0 + (i % 3) * 0.01
            pb = 95.0 + (i % 3) * 0.01
            w131.record_prices(pa, pb)

        assert w131.get_divergence_zscore() < 3.0
        assert w131.is_entry_blocked() is False
        assert w131.is_blocked() is False

    # -- T2: Sudden divergence spike triggers block --
    def test_divergence_spike_blocks(self):
        """A sudden 3+ sigma divergence blow-out activates protective block."""
        # Establish stable spread across 20 observations
        for i in range(20):
            w131.record_prices(100.0 + (i % 2) * 0.02, 100.0)

        # Huge sudden dislocation in price_a relative to price_b
        w131.record_prices(115.0, 100.0)

        assert w131.get_divergence_zscore() >= 3.0
        assert w131.is_entry_blocked() is True

    # -- T3: update() alias works identically and records z-score --
    def test_update_alias_and_zscore(self):
        """update() correctly routes both asset prices."""
        for i in range(20):
            w131.update(100.0 + (i % 2) * 0.02, 100.0)
        w131.update(120.0, 100.0)

        assert w131.get_divergence_zscore() >= 3.0
        assert w131.is_entry_blocked() is True

    # -- T4: Invalid inputs for either price are safely ignored --
    def test_invalid_inputs_ignored(self):
        """Booleans, NaN, Inf, non-positive numbers in either asset ignored."""
        w131.record_prices(True, 100.0)
        w131.record_prices(100.0, False)
        w131.record_prices(float("nan"), 100.0)
        w131.record_prices(100.0, float("inf"))
        w131.record_prices(-50.0, 100.0)
        w131.record_prices(100.0, 0.0)

        with w131._lock:
            assert len(w131._spreads) == 0

    # -- T5: reset() clears spread history and unblocks --
    def test_reset_clears_state(self):
        """reset() zeroes z-score, empties spreads, and clears active block."""
        for i in range(20):
            w131.record_prices(100.0 + (i % 2) * 0.02, 100.0)
        w131.record_prices(115.0, 100.0)
        assert w131.is_entry_blocked() is True

        w131.reset()
        assert w131.is_entry_blocked() is False
        assert w131.get_divergence_zscore() == 0.0
        with w131._lock:
            assert len(w131._spreads) == 0
            assert w131._blocked_until == 0.0
