"""
tests/test_batch190.py
-----------------------
Unit tests for Batch 190 wave modules:
  - wave146_trade_intensity_burst_guard             (5 tests)
  - wave147_order_cancellation_depth_decay_guard    (5 tests)

Baseline before this batch: 2,144 collected items (2,143 passed, 1 skipped)
Expected after: 2,154 collected items (2,153 passed, 1 skipped)
"""

import math
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave146_trade_intensity_burst_guard as w146
import wave147_order_cancellation_depth_decay_guard as w147


# ===========================================================================
# wave146 — Microstructure Trade Arrival Intensity Burst Guard (5 tests)
# ===========================================================================

class TestWave146TradeIntensityBurstGuard:

    def setup_method(self):
        w146.reset()

    # -- T1: Normal trade rate does not block --
    def test_normal_intensity_not_blocked(self):
        """Moderate transaction rate (5 trades/sec) yields rate < 25 and does not block."""
        t0 = 1000.0
        for i in range(5):
            w146.record_trade(100.0, 1.0, ts=t0 + i * 0.20)

        assert w146.get_current_trade_rate() < 10.0
        assert w146.is_entry_blocked() is False
        assert w146.is_blocked() is False

    # -- T2: Extreme transaction burst blocks --
    def test_trade_intensity_burst_blocks(self):
        """Burst of 30 trades within 0.8s triggers trade intensity block."""
        t0 = 1000.0
        for i in range(30):
            w146.record_trade(100.0, 1.0, ts=t0 + i * 0.025)

        assert w146.get_current_trade_rate() >= 25.0
        assert w146.is_entry_blocked() is True

    # -- T3: update() alias works identically and provides rate --
    def test_update_alias(self):
        """update() correctly routes trade records and triggers block."""
        t0 = 1000.0
        for i in range(28):
            w146.update(100.0, 1.0, ts=t0 + i * 0.025)

        assert w146.get_current_trade_rate() >= 25.0
        assert w146.is_entry_blocked() is True

    # -- T4: Invalid inputs safely ignored --
    def test_invalid_inputs_ignored(self):
        """Booleans, NaN, Inf, non-positive numbers do not corrupt state."""
        w146.record_trade(True, 1.0)
        w146.record_trade(100.0, False)
        w146.record_trade(float("nan"), 1.0)
        w146.record_trade(100.0, float("inf"))
        w146.record_trade(-10.0, 1.0)
        w146.record_trade(100.0, 0.0)

        with w146._lock:
            assert len(w146._timestamps) == 0

    # -- T5: reset() clears all state and unblocks --
    def test_reset_clears_state(self):
        """reset() empties timestamps, unblocks, and restores rate to 1.0."""
        t0 = 1000.0
        for i in range(30):
            w146.record_trade(100.0, 1.0, ts=t0 + i * 0.025)
        assert w146.is_entry_blocked() is True

        w146.reset()
        assert w146.is_entry_blocked() is False
        assert w146.get_current_trade_rate() == 1.0
        with w146._lock:
            assert len(w146._timestamps) == 0
            assert w146._blocked_until == 0.0


# ===========================================================================
# wave147 — Order Book Ghost Liquidity Flash Cancellation Guard (5 tests)
# ===========================================================================

class TestWave147OrderCancellationDepthDecayGuard:

    def setup_method(self):
        w147.reset()

    # -- T1: Normal trade consumption of depth does not trigger cancel block --
    def test_legitimate_execution_not_blocked(self):
        """When depth drops due to real executed volume, cancellation ratio remains 0."""
        t0 = 1000.0
        # Snapshot 1: 10 lots total depth (5 bid + 5 ask)
        w147.record_depth(5.0, 5.0, ts=t0)

        # Snapshot 2: depth drops to 3 lots, but 7 lots were executed by real trades!
        # canceled_vol = max(0, 10 - 3 - 7) = 0.0 -> cancel_ratio = 0.0
        w147.record_depth(1.5, 1.5, executed_vol=7.0, ts=t0 + 0.10)

        assert w147.get_cancellation_decay_ratio() == 0.0
        assert w147.is_entry_blocked() is False
        assert w147.is_blocked() is False

    # -- T2: Ghost liquidity flash pull triggers protective block --
    def test_flash_cancellation_blocks(self):
        """Sudden pull of 80% depth without trade executions triggers ghost liquidity block."""
        t0 = 1000.0
        # Initial depth: 10 lots
        w147.record_depth(5.0, 5.0, ts=t0)

        # 0.15s later, depth collapses to 1.5 lots with ZERO trade executions!
        # canceled_vol = 10 - 1.5 = 8.5 lots -> cancel_ratio = 8.5 / 10 = 0.85 >= 0.70
        w147.record_depth(0.75, 0.75, executed_vol=0.0, ts=t0 + 0.15)

        assert w147.get_cancellation_decay_ratio() >= 0.70
        assert w147.is_entry_blocked() is True

    # -- T3: update() alias works identically and provides ratio --
    def test_update_alias(self):
        """update() correctly routes depth updates and triggers block."""
        t0 = 1000.0
        w147.update(10.0, 10.0, ts=t0)  # 20 lots
        w147.update(2.0, 2.0, executed_vol=1.0, ts=t0 + 0.20)  # pull 15 lots unexecuted -> 75% cancel

        assert w147.get_cancellation_decay_ratio() >= 0.70
        assert w147.is_entry_blocked() is True

    # -- T4: Invalid inputs safely ignored --
    def test_invalid_inputs_ignored(self):
        """Booleans, NaN, Inf, negative numbers do not corrupt state."""
        w147.record_depth(True, 5.0)
        w147.record_depth(5.0, False)
        w147.record_depth(float("nan"), 5.0)
        w147.record_depth(5.0, float("inf"))
        w147.record_depth(-5.0, 5.0)
        w147.record_depth(0.0, 0.0)

        with w147._lock:
            assert w147._prev_depth is None

    # -- T5: reset() clears all state and unblocks --
    def test_reset_clears_state(self):
        """reset() clears depth history, ratio, and unblocks."""
        t0 = 1000.0
        w147.record_depth(5.0, 5.0, ts=t0)
        w147.record_depth(0.5, 0.5, executed_vol=0.0, ts=t0 + 0.15)
        assert w147.is_entry_blocked() is True

        w147.reset()
        assert w147.is_entry_blocked() is False
        assert w147.get_cancellation_decay_ratio() == 0.0
        with w147._lock:
            assert w147._prev_depth is None
            assert w147._prev_time is None
            assert w147._blocked_until == 0.0
