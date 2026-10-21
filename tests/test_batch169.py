"""
tests/test_batch169.py
-----------------------
Unit tests for Batch 169 wave modules:
  - wave104_pip_target_guard        (5 tests)
  - wave105_max_daily_trades_guard  (5 tests)

Baseline before this batch: 1,933 passed, 1 skipped
Expected after: 1,943 passed, 1 skipped
"""

import math
import time
import threading
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave104_pip_target_guard as w104
import wave105_max_daily_trades_guard as w105


# ===========================================================================
# wave104 — Daily Pip Target Guard (5 tests)
# ===========================================================================

class TestWave104PipTargetGuard:

    def setup_method(self):
        w104.reset()

    # -- T1: Not blocked before pip target is reached --
    def test_not_blocked_below_target(self):
        """Cumulative pips below DAILY_PIP_TARGET must not block."""
        w104.add_pips(20.0)
        w104.add_pips(15.0)   # total = 35 < 50
        assert w104.is_entry_blocked() is False

    # -- T2: Blocked exactly at pip target --
    def test_blocked_at_target(self):
        """Cumulative pips reaching DAILY_PIP_TARGET must block."""
        w104.add_pips(30.0)
        w104.add_pips(20.0)   # total = 50.0 >= 50.0 -> blocked
        assert w104.is_entry_blocked() is True

    # -- T3: Blocked above pip target --
    def test_blocked_above_target(self):
        """Single trade exceeding the target must also block."""
        w104.add_pips(75.0)   # 75 > 50 -> blocked
        assert w104.is_entry_blocked() is True

    # -- T4: Negative pips reduce cumulative total --
    def test_negative_pips_reduce_total(self):
        """Losses must reduce the cumulative pip total."""
        w104.add_pips(60.0)   # total = 60 -> blocked
        assert w104.is_entry_blocked() is True
        w104.add_pips(-20.0)  # total = 40 < 50 -> unblocked
        assert w104.is_entry_blocked() is False

    # -- T5: Invalid inputs ignored; reset() clears state --
    def test_invalid_inputs_and_reset(self):
        """Bool/NaN/Inf inputs silently rejected; reset() zeroes everything."""
        w104.add_pips(True)
        w104.add_pips(False)
        w104.add_pips(float("nan"))
        w104.add_pips(float("inf"))
        w104.add_pips("10")    # type: ignore
        assert w104.is_entry_blocked() is False

        # Accumulate past target, then reset
        w104.add_pips(55.0)
        assert w104.is_entry_blocked() is True
        w104.reset()
        assert w104.is_entry_blocked() is False
        with w104._lock:
            assert w104._cumulative_pips == 0.0


# ===========================================================================
# wave105 — Max Daily Trades Guard (5 tests)
# ===========================================================================

class TestWave105MaxDailyTradesGuard:

    def setup_method(self):
        w105.reset()

    # -- T1: Not blocked below MAX_TRADES_PER_DAY --
    def test_not_blocked_below_max(self):
        """Fewer than MAX_TRADES_PER_DAY trades must not block."""
        for _ in range(w105.MAX_TRADES_PER_DAY - 1):
            w105.record_trade()
        assert w105.is_entry_blocked() is False

    # -- T2: Blocked exactly at MAX_TRADES_PER_DAY --
    def test_blocked_at_max_trades(self):
        """Reaching MAX_TRADES_PER_DAY must block."""
        for _ in range(w105.MAX_TRADES_PER_DAY):
            w105.record_trade()
        assert w105.is_entry_blocked() is True

    # -- T3: Blocked above MAX_TRADES_PER_DAY --
    def test_blocked_above_max_trades(self):
        """Exceeding MAX_TRADES_PER_DAY must also block."""
        for _ in range(w105.MAX_TRADES_PER_DAY + 5):
            w105.record_trade()
        assert w105.is_entry_blocked() is True

    # -- T4: update() is alias for record_trade() --
    def test_update_alias(self):
        """update() must increment the counter identically to record_trade()."""
        for _ in range(w105.MAX_TRADES_PER_DAY):
            w105.update()
        assert w105.is_entry_blocked() is True

    # -- T5: reset() clears counter and day marker --
    def test_reset_clears_state(self):
        """After reset(), guard must report not blocked."""
        for _ in range(w105.MAX_TRADES_PER_DAY):
            w105.record_trade()
        assert w105.is_entry_blocked() is True
        w105.reset()
        assert w105.is_entry_blocked() is False
        with w105._lock:
            assert w105._trade_count == 0
