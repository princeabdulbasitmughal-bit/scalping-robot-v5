"""
tests/test_batch170.py
-----------------------
Unit tests for Batch 170 wave modules:
  - wave106_overnight_position_guard  (5 tests)
  - wave107_account_balance_guard     (5 tests)

Baseline before this batch: 1,943 passed, 1 skipped
Expected after: 1,953 passed, 1 skipped
"""

import math
import time
import threading
import sys
import os
from datetime import datetime, timezone, timedelta
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave106_overnight_position_guard as w106
import wave107_account_balance_guard as w107


# ===========================================================================
# wave106 — Overnight Position Guard (5 tests)
# ===========================================================================

class TestWave106OvernightPositionGuard:

    def setup_method(self):
        w106.reset()

    # -- T1: Not blocked outside rollover window, no overnight flag --
    def test_not_blocked_during_normal_hours(self):
        """Outside the rollover window with no flag, guard must allow entry."""
        # Patch UTC time to 12:00 — safely outside any rollover window
        fake_dt = datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc)
        with mock.patch("wave106_overnight_position_guard.datetime") as mock_dt:
            mock_dt.now.return_value = fake_dt
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert w106.is_entry_blocked() is False

    # -- T2: Blocked inside rollover window (before rollover) --
    def test_blocked_inside_rollover_window_before(self):
        """Time 10 min before 21:00 UTC must be within block window."""
        rollover_minus_10 = datetime(
            2026, 10, 21,
            w106.ROLLOVER_HOUR_UTC, 0, 0, tzinfo=timezone.utc
        ) - timedelta(minutes=10)
        with mock.patch("wave106_overnight_position_guard.datetime") as mock_dt:
            mock_dt.now.return_value = rollover_minus_10
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert w106.is_entry_blocked() is True

    # -- T3: Blocked inside rollover window (after rollover) --
    def test_blocked_inside_rollover_window_after(self):
        """Time 10 min after 21:00 UTC must be within block window."""
        rollover_plus_10 = datetime(
            2026, 10, 21,
            w106.ROLLOVER_HOUR_UTC, 10, 0, tzinfo=timezone.utc
        )
        with mock.patch("wave106_overnight_position_guard.datetime") as mock_dt:
            mock_dt.now.return_value = rollover_plus_10
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert w106.is_entry_blocked() is True

    # -- T4: flag_overnight() triggers cooldown block --
    def test_flag_overnight_triggers_block(self):
        """Calling flag_overnight() must immediately block entries."""
        # Patch to safe hours so window check is False
        fake_dt = datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc)
        with mock.patch("wave106_overnight_position_guard.datetime") as mock_dt:
            mock_dt.now.return_value = fake_dt
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            w106.flag_overnight()
            assert w106.is_entry_blocked() is True

    # -- T5: reset() clears overnight cooldown; update() is alias --
    def test_reset_and_update_alias(self):
        """reset() must clear the cooldown; update() acts like flag_overnight()."""
        w106.update()   # alias for flag_overnight
        # Backdating makes cooldown appear expired
        with w106._lock:
            w106._overnight_blocked_until = time.monotonic() - 1.0
        # Now force a safe hour to avoid window block
        fake_dt = datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc)
        with mock.patch("wave106_overnight_position_guard.datetime") as mock_dt:
            mock_dt.now.return_value = fake_dt
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            assert w106.is_entry_blocked() is False
        w106.reset()
        with w106._lock:
            assert w106._overnight_blocked_until == 0.0


# ===========================================================================
# wave107 — Account Balance Guard (5 tests)
# ===========================================================================

class TestWave107AccountBalanceGuard:

    def setup_method(self):
        w107.reset()

    # -- T1: Not blocked when balance is above minimum --
    def test_not_blocked_above_min(self):
        """Balance well above MIN_BALANCE_USD must not block."""
        w107.update(10000.0)
        assert w107.is_entry_blocked() is False

    # -- T2: Blocked when balance is below minimum --
    def test_blocked_below_min(self):
        """Balance below MIN_BALANCE_USD must trigger block."""
        w107.update(499.99)
        assert w107.is_entry_blocked() is True

    # -- T3: Blocked on zero or negative balance --
    def test_blocked_on_zero_and_negative(self):
        """Zero and negative balance must both trigger block."""
        w107.update(0.0)
        assert w107.is_entry_blocked() is True
        w107.reset()
        w107.update(-100.0)
        assert w107.is_entry_blocked() is True

    # -- T4: Invalid inputs silently ignored --
    def test_invalid_inputs_ignored(self):
        """Bool/NaN/Inf inputs must be silently rejected."""
        w107.update(True)
        w107.update(False)
        w107.update(float("nan"))
        w107.update(float("inf"))
        w107.update(float("-inf"))
        w107.update("500")   # type: ignore
        w107.update(None)    # type: ignore
        assert w107.is_entry_blocked() is False

    # -- T5: reset() clears block state --
    def test_reset_clears_state(self):
        """After reset(), guard must report not blocked."""
        w107.update(100.0)   # below threshold -> blocked
        assert w107.is_entry_blocked() is True
        w107.reset()
        assert w107.is_entry_blocked() is False
        with w107._lock:
            assert w107._blocked_until == 0.0
