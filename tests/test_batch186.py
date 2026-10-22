"""
tests/test_batch186.py
-----------------------
Unit tests for Batch 186 wave modules:
  - wave138_kurtosis_fat_tail_guard            (5 tests)
  - wave139_order_flow_toxicity_vpin_guard     (5 tests)

Baseline before this batch: 2,104 collected items (2,103 passed, 1 skipped)
Expected after: 2,114 collected items (2,113 passed, 1 skipped)
"""

import math
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave138_kurtosis_fat_tail_guard as w138
import wave139_order_flow_toxicity_vpin_guard as w139


# ===========================================================================
# wave138 — Microstructure Return Kurtosis Fat-Tail Guard (5 tests)
# ===========================================================================

class TestWave138KurtosisFatTailGuard:

    def setup_method(self):
        w138.reset()

    # -- T1: Normal Gaussian-like returns produce kurtosis < 6.0 and do not block --
    def test_normal_kurtosis_not_blocked(self):
        """Evenly distributed micro returns maintain low kurtosis and do not block."""
        price = 100.0
        w138.record_tick(price)
        # Moderate balanced step variations
        for i in range(20):
            delta = 0.10 if (i % 2 == 0) else -0.10
            price += delta
            w138.record_tick(price)

        kurt = w138.get_current_kurtosis()
        assert kurt < 6.0
        assert w138.is_entry_blocked() is False
        assert w138.is_blocked() is False

    # -- T2: Extreme leptokurtic jump outliers drive kurtosis >= 6.0 and block --
    def test_extreme_kurtosis_blocks(self):
        """Isolated heavy-tail jump outliers drive kurtosis >= 6.0 and trigger block."""
        price = 100.0
        w138.record_tick(price)
        # 16 tiny returns: standard deviation is very small
        for _ in range(16):
            price += 0.01
            w138.record_tick(price)

        # 2 huge jump outliers (heavy tails)
        price += 3.00
        w138.record_tick(price)
        price -= 3.00
        w138.record_tick(price)

        kurt = w138.get_current_kurtosis()
        assert kurt >= 6.0
        assert w138.is_entry_blocked() is True

    # -- T3: update() alias works and tracks kurtosis --
    def test_update_alias(self):
        """update() correctly routes tick prices and evaluates kurtosis."""
        price = 100.0
        w138.update(price)
        for _ in range(16):
            price += 0.01
            w138.update(price)
        price += 3.00
        w138.update(price)
        price -= 3.00
        w138.update(price)

        assert w138.get_current_kurtosis() >= 6.0
        assert w138.is_entry_blocked() is True

    # -- T4: Invalid inputs safely ignored --
    def test_invalid_inputs_ignored(self):
        """Booleans, NaN, Inf, non-positive numbers do not corrupt state."""
        w138.record_tick(True)
        w138.record_tick(float("nan"))
        w138.record_tick(float("inf"))
        w138.record_tick(-50.0)
        w138.record_tick(0.0)

        with w138._lock:
            assert w138._prev_price is None
            assert len(w138._returns) == 0

    # -- T5: reset() restores default kurtosis and clears active block --
    def test_reset_clears_state(self):
        """reset() restores default Gaussian kurtosis (3.0) and unblocks."""
        price = 100.0
        w138.record_tick(price)
        for _ in range(16):
            price += 0.01
            w138.record_tick(price)
        price += 3.00
        w138.record_tick(price)
        price -= 3.00
        w138.record_tick(price)
        assert w138.is_entry_blocked() is True

        w138.reset()
        assert w138.is_entry_blocked() is False
        assert w138.get_current_kurtosis() == 3.0
        with w138._lock:
            assert w138._prev_price is None
            assert len(w138._returns) == 0
            assert w138._blocked_until == 0.0


# ===========================================================================
# wave139 — Volume-Synchronized Probability of Toxicity (VPIN) Guard (5 tests)
# ===========================================================================

class TestWave139OrderFlowToxicityVPINGuard:

    def setup_method(self):
        w139.reset()

    # -- T1: Balanced two-way order flow maintains low VPIN and does not block --
    def test_balanced_flow_not_blocked(self):
        """Equal alternating buy and sell trade volumes yield VPIN < 0.40 and do not block."""
        price = 100.0
        w139.record_trade(price, 1.0)
        # Feed 10 buckets of perfectly alternating 1-lot buys and sells
        for _ in range(25):
            price += 0.10
            w139.record_trade(price, 1.0)  # buy
            price -= 0.10
            w139.record_trade(price, 1.0)  # sell

        vpin = w139.get_current_vpin()
        assert vpin < 0.40
        assert w139.is_entry_blocked() is False
        assert w139.is_blocked() is False

    # -- T2: One-way toxic aggressive buying drives VPIN >= 0.70 and blocks --
    def test_toxic_flow_blocks(self):
        """Persistent one-way aggressive buying fills 5 buckets with 100% buy imbalance -> VPIN = 1.0."""
        price = 100.0
        w139.record_trade(price, 1.0)
        # 5 buckets * 5.0 lots = 25 lots total of continuous upticks
        for _ in range(5):
            price += 0.20
            w139.record_trade(price, 5.0)

        vpin = w139.get_current_vpin()
        assert vpin >= 0.70
        assert w139.is_entry_blocked() is True

    # -- T3: update() alias works identically and provides VPIN --
    def test_update_alias_and_vpin(self):
        """update() correctly routes trades into volume buckets and triggers block on toxic sell flow."""
        price = 100.0
        w139.update(price, 1.0)
        for _ in range(5):
            price -= 0.20
            w139.update(price, 5.0)  # 100% sell imbalance

        assert w139.get_current_vpin() >= 0.70
        assert w139.is_entry_blocked() is True

    # -- T4: Invalid inputs safely ignored --
    def test_invalid_inputs_ignored(self):
        """Booleans, NaN, Inf, non-positive price or volume ignored."""
        w139.record_trade(True, 1.0)
        w139.record_trade(100.0, False)
        w139.record_trade(float("nan"), 1.0)
        w139.record_trade(100.0, float("inf"))
        w139.record_trade(-10.0, 1.0)
        w139.record_trade(100.0, -1.0)

        with w139._lock:
            assert w139._prev_price is None
            assert len(w139._completed_buckets) == 0

    # -- T5: reset() clears all state and unblocks --
    def test_reset_clears_state(self):
        """reset() empties buckets, unblocks, and restores baseline VPIN."""
        price = 100.0
        w139.record_trade(price, 1.0)
        for _ in range(5):
            price += 0.20
            w139.record_trade(price, 5.0)
        assert w139.is_entry_blocked() is True

        w139.reset()
        assert w139.is_entry_blocked() is False
        assert w139.get_current_vpin() == 0.20
        with w139._lock:
            assert w139._prev_price is None
            assert len(w139._completed_buckets) == 0
            assert w139._blocked_until == 0.0
