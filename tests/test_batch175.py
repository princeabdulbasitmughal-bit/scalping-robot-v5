"""
tests/test_batch175.py
-----------------------
Unit tests for Batch 175 wave modules:
  - wave116_market_depth_imbalance_guard    (5 tests)
  - wave117_volatility_of_volatility_guard  (5 tests)

Baseline before this batch: 1,994 collected items
Expected after: 2,004 collected items (2,000+ Milestone Crossed!)
"""

import math
import time
import threading
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave116_market_depth_imbalance_guard as w116
import wave117_volatility_of_volatility_guard as w117


# ===========================================================================
# wave116 — Market Depth Imbalance Guard (5 tests)
# ===========================================================================

class TestWave116MarketDepthImbalanceGuard:

    def setup_method(self):
        w116.reset()

    # -- T1: Balanced book does not block --
    def test_balanced_depth_not_blocked(self):
        """Ratio 100/100 = 1.0 < 4.0 does not block."""
        w116.record_depth(100.0, 100.0)
        assert w116.is_entry_blocked() is False

    # -- T2: Extreme bid skew (e.g. 500 bid vs 100 ask) blocks --
    def test_extreme_bid_imbalance_blocked(self):
        """5:1 bid/ask volume skew >= 4:1 triggers block."""
        w116.record_depth(500.0, 100.0)
        assert w116.is_entry_blocked() is True

    # -- T3: Extreme ask skew (e.g. 50 bid vs 300 ask) blocks --
    def test_extreme_ask_imbalance_blocked(self):
        """6:1 ask/bid volume skew >= 4:1 triggers block."""
        w116.record_depth(50.0, 300.0)
        assert w116.is_entry_blocked() is True

    # -- T4: update() works as alias for record_depth --
    def test_update_alias(self):
        """update() functions identically to record_depth()."""
        w116.update(450.0, 100.0)
        assert w116.is_entry_blocked() is True

    # -- T5: Invalid inputs rejected; reset() clears block --
    def test_invalid_inputs_and_reset(self):
        """Booleans, negative or NaN volumes are ignored; reset() clears block."""
        w116.record_depth(True, 100.0)
        w116.record_depth(100.0, float("nan"))
        w116.record_depth(-10.0, 50.0)
        assert w116.is_entry_blocked() is False

        w116.record_depth(500.0, 50.0)
        assert w116.is_entry_blocked() is True
        w116.reset()
        assert w116.is_entry_blocked() is False


# ===========================================================================
# wave117 — Volatility of Volatility Guard (5 tests)
# ===========================================================================

class TestWave117VolatilityOfVolatilityGuard:

    def setup_method(self):
        w117.reset()

    # -- T1: Warmup requires MIN_SAMPLES before evaluation --
    def test_warmup_prevents_premature_block(self):
        """Fewer than MIN_SAMPLES volatility estimates do not block."""
        for _ in range(w117.MIN_SAMPLES - 1):
            w117.record_volatility(0.01)
        assert w117.is_entry_blocked() is False

    # -- T2: Stable volatility estimates have low vol-of-vol; no block --
    def test_stable_volatility_not_blocked(self):
        """Consistent volatility estimates yield near-zero std-dev; not blocked."""
        for _ in range(w117.MIN_SAMPLES):
            w117.record_volatility(0.0050)
        assert w117.is_entry_blocked() is False

    # -- T3: Large swings in volatility estimates trigger block --
    def test_vol_of_vol_spike_blocked(self):
        """Vol estimates swinging between 0.001 and 0.006 (std > 0.0015) trigger block."""
        vol_readings = [0.001, 0.006, 0.001, 0.007, 0.001, 0.006]
        for v in vol_readings:
            w117.record_volatility(v)
        assert w117.is_entry_blocked() is True

    # -- T4: update() works as alias for record_volatility --
    def test_update_alias(self):
        """update() functions identically to record_volatility()."""
        w117.update(0.005)
        with w117._lock:
            assert len(w117._vol_estimates) == 1

    # -- T5: Invalid inputs rejected; reset() clears estimates --
    def test_invalid_inputs_and_reset(self):
        """Boolean, NaN, Inf, negative inputs rejected; reset() clears all."""
        w117.record_volatility(True)
        w117.record_volatility(float("nan"))
        w117.record_volatility(float("inf"))
        w117.record_volatility(-0.01)
        assert len(w117._vol_estimates) == 0

        # Trigger block then reset
        with w117._lock:
            w117._blocked_until = time.monotonic() + 100.0
            w117._vol_estimates.append(0.01)
        assert w117.is_entry_blocked() is True
        w117.reset()
        assert w117.is_entry_blocked() is False
        assert len(w117._vol_estimates) == 0
