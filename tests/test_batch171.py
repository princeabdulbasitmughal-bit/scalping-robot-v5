"""
tests/test_batch171.py
-----------------------
Unit tests for Batch 171 wave modules:
  - wave108_win_rate_decay_guard  (5 tests)
  - wave109_holding_cost_guard    (5 tests)

Baseline before this batch: 1,954 collected items
Expected after: 1,964 collected items
"""

import math
import time
import threading
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave108_win_rate_decay_guard as w108
import wave109_holding_cost_guard as w109


# ===========================================================================
# wave108 — Rolling Win Rate Decay Guard (5 tests)
# ===========================================================================

class TestWave108WinRateDecayGuard:

    def setup_method(self):
        w108.reset()

    # -- T1: Not blocked before MIN_TRADES_WARMUP --
    def test_not_blocked_during_warmup(self):
        """Even with all losses, warmup requirement prevents premature blocking."""
        for _ in range(w108.MIN_TRADES_WARMUP - 1):
            w108.record_trade(-10.0)
        assert w108.is_entry_blocked() is False

    # -- T2: Blocked when win rate decays below MIN_WIN_RATE --
    def test_blocked_when_win_rate_decays(self):
        """10 trades with only 2 wins (20% win rate) < 35% must trigger block."""
        for _ in range(2):
            w108.record_trade(15.0)   # 2 wins
        for _ in range(8):
            w108.record_trade(-10.0)  # 8 losses
        assert w108.is_entry_blocked() is True

    # -- T3: Not blocked when win rate is healthy --
    def test_not_blocked_healthy_win_rate(self):
        """10 trades with 5 wins (50% win rate) >= 35% must not block."""
        for _ in range(5):
            w108.record_trade(15.0)
        for _ in range(5):
            w108.record_trade(-10.0)
        assert w108.is_entry_blocked() is False

    # -- T4: update() handles both bool and numeric PnL --
    def test_update_polymorphism(self):
        """update() must accept boolean True/False or numeric PnL."""
        w108.update(True)
        w108.update(False)
        w108.update(10.5)
        w108.update(-5.2)
        assert len(w108._outcomes) == 4

    # -- T5: Invalid inputs ignored; reset() clears history --
    def test_invalid_inputs_and_reset(self):
        """NaN, Inf, strings rejected; reset() restores baseline."""
        w108.update(float("nan"))
        w108.update(float("inf"))
        w108.update("loss")
        assert len(w108._outcomes) == 0

        # Trigger block then reset
        with w108._lock:
            w108._blocked_until = time.monotonic() + 500.0
        assert w108.is_entry_blocked() is True
        w108.reset()
        assert w108.is_entry_blocked() is False
        assert len(w108._outcomes) == 0


# ===========================================================================
# wave109 — Holding Cost Guard (5 tests)
# ===========================================================================

class TestWave109HoldingCostGuard:

    def setup_method(self):
        w109.reset()

    # -- T1: Not blocked when aggregate swap is acceptable --
    def test_not_blocked_normal_swap(self):
        """Total swap of -$10 is above the -$25 limit, so not blocked."""
        w109.update_swap(101, -5.0)
        w109.update_swap(102, -5.0)
        assert w109.is_entry_blocked() is False

    # -- T2: Blocked when aggregate swap breaches threshold --
    def test_blocked_excessive_negative_swap(self):
        """Total swap of -$30.0 breaches -$25.0 threshold and blocks entries."""
        w109.update_swap(101, -15.0)
        w109.update_swap(102, -15.0)
        assert w109.is_entry_blocked() is True

    # -- T3: Closing ticket removes it from pool --
    def test_close_ticket_removes_from_pool(self):
        """Closing a high negative swap ticket lifts the live calculation when cooldown expires."""
        w109.update_swap(101, -20.0)
        w109.update_swap(102, -10.0)
        assert w109.is_entry_blocked() is True

        w109.close_ticket(101)
        # Manually expire the cooldown to test pool recalculation
        with w109._lock:
            w109._blocked_until = 0.0
        assert w109.is_entry_blocked() is False

    # -- T4: update() alias behaves identically to update_swap --
    def test_update_alias(self):
        """update() must work like update_swap()."""
        w109.update("TICKET_A", -12.5)
        w109.update("TICKET_B", -13.0)
        assert w109.is_entry_blocked() is True

    # -- T5: Invalid inputs rejected; reset() clears all state --
    def test_invalid_inputs_and_reset(self):
        """Invalid tickets or NaN swap values are rejected."""
        w109.update_swap(True, -5.0)        # bool ticket rejected
        w109.update_swap(201, True)         # bool swap rejected
        w109.update_swap(202, float("nan")) # NaN swap rejected
        w109.update_swap("", -10.0)         # empty ticket rejected
        assert len(w109._swaps) == 0

        # Set block then reset
        w109.update_swap(301, -30.0)
        assert w109.is_entry_blocked() is True
        w109.reset()
        assert w109.is_entry_blocked() is False
        assert len(w109._swaps) == 0
