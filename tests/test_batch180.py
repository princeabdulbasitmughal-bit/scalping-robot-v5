"""
tests/test_batch180.py
-----------------------
Unit tests for Batch 180 wave modules:
  - wave126_intraday_turnover_guard            (5 tests)
  - wave127_adverse_excursion_velocity_guard   (5 tests)

Baseline before this batch: 2,044 collected items
Expected after: 2,054 collected items
"""

import math
import time
import threading
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave126_intraday_turnover_guard as w126
import wave127_adverse_excursion_velocity_guard as w127


# ===========================================================================
# wave126 — Intraday Gross Notional Turnover Guard (5 tests)
# ===========================================================================

class TestWave126IntradayTurnoverGuard:

    def setup_method(self):
        w126.reset()

    # -- T1: Normal trading turnover below MAX_DAILY_LOTS does not block --
    def test_low_turnover_not_blocked(self):
        """Turnover of 20 lots < 50 lots limit must not block."""
        w126.record_trade_lots(10.0)
        w126.record_trade_lots(10.0)
        assert w126.is_entry_blocked() is False

    # -- T2: Turnover reaching or exceeding MAX_DAILY_LOTS blocks --
    def test_high_turnover_blocks(self):
        """Turnover of 50 lots meets MAX_DAILY_LOTS and blocks entries."""
        w126.record_trade_lots(25.0)
        w126.record_trade_lots(25.0)
        assert w126.is_entry_blocked() is True

    # -- T3: Large single order blocks if it breaches limit --
    def test_large_single_turnover_blocks(self):
        """A single 55-lot execution breaches 50-lot limit -> blocked."""
        w126.record_trade_lots(55.0)
        assert w126.is_entry_blocked() is True

    # -- T4: update() works as alias for record_trade_lots --
    def test_update_alias(self):
        """update() functions identically to record_trade_lots()."""
        w126.update(52.0)
        assert w126.is_entry_blocked() is True

    # -- T5: Invalid inputs ignored; reset() clears all state --
    def test_invalid_inputs_and_reset(self):
        """Booleans, NaN, Inf, non-positive values ignored; reset() zeroes lots."""
        w126.record_trade_lots(True)
        w126.record_trade_lots(float("nan"))
        w126.record_trade_lots(-10.0)
        with w126._lock:
            assert w126._cumulative_lots == 0.0

        w126.record_trade_lots(60.0)
        assert w126.is_entry_blocked() is True
        w126.reset()
        assert w126.is_entry_blocked() is False
        with w126._lock:
            assert w126._cumulative_lots == 0.0


# ===========================================================================
# wave127 — Maximum Adverse Excursion (MAE) Velocity Guard (5 tests)
# ===========================================================================

class TestWave127AdverseExcursionVelocityGuard:

    def setup_method(self):
        w127.reset()

    # -- T1: Stable or improving PnL does not block --
    def test_improving_pnl_not_blocked(self):
        """Floating PnL that rises or holds stable must not block."""
        w127.record_floating_pnl(0.0, ts=1000.0)
        w127.record_floating_pnl(5.0, ts=1001.0)
        w127.record_floating_pnl(10.0, ts=1002.0)
        assert w127.is_entry_blocked() is False

    # -- T2: Slow gentle loss drift does not breach $5/s velocity --
    def test_slow_loss_drift_not_blocked(self):
        """PnL dropping $2 over 2 seconds (1 USD/s < 5 USD/s limit) does not block."""
        w127.record_floating_pnl(0.0, ts=1000.0)
        w127.record_floating_pnl(-2.0, ts=1002.0)
        assert w127.is_entry_blocked() is False

    # -- T3: Severe plunge in floating loss (>= $5/s) triggers block --
    def test_rapid_loss_plunge_triggers_block(self):
        """PnL collapsing from $0 to -$15 in 1 second ($15/s >= $5/s) blocks entries."""
        w127.record_floating_pnl(0.0, ts=1000.0)
        w127.record_floating_pnl(-15.0, ts=1001.0)
        assert w127.is_entry_blocked() is True

    # -- T4: update() works as alias for record_floating_pnl --
    def test_update_alias(self):
        """update() functions identically to record_floating_pnl()."""
        w127.update(0.0, ts=100.0)
        w127.update(-20.0, ts=101.0)
        assert w127.is_entry_blocked() is True

    # -- T5: Invalid inputs ignored; reset() clears all state --
    def test_invalid_inputs_and_reset(self):
        """Booleans, NaN, Inf values ignored; reset() restores baseline."""
        w127.record_floating_pnl(True)
        w127.record_floating_pnl(float("nan"))
        assert w127._prev_time == -1.0

        with w127._lock:
            w127._blocked_until = time.monotonic() + 100.0
        assert w127.is_entry_blocked() is True
        w127.reset()
        assert w127.is_entry_blocked() is False
        assert w127._prev_time == -1.0
