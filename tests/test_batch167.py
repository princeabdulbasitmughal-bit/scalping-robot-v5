"""
tests/test_batch167.py
-----------------------
Unit tests for Batch 167 wave modules:
  - wave100_equity_high_watermark_guard  (5 tests)
  - wave101_lot_concentration_guard      (5 tests)

Baseline before this batch: 1,913 passed, 1 skipped
Expected after: 1,923 passed, 1 skipped
"""

import math
import time
import threading
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave100_equity_high_watermark_guard as w100
import wave101_lot_concentration_guard as w101


# ===========================================================================
# wave100 — Equity High-Watermark Drawdown Guard (5 tests)
# ===========================================================================

class TestWave100EquityHighWatermarkGuard:

    def setup_method(self):
        w100.reset()

    # -- T1: First update sets HWM; no block on initialization --
    def test_no_block_on_first_update(self):
        """First equity update must set HWM without triggering a block."""
        w100.update(10000.0)
        assert w100.is_entry_blocked() is False

    # -- T2: Blocked when equity drops >= MAX_DRAWDOWN_PCT from HWM --
    def test_blocked_on_large_drawdown(self):
        """A 6% drop from HWM (above 5% threshold) must trigger block."""
        w100.update(10000.0)   # sets HWM = 10000
        w100.update(9400.0)    # 6% drawdown -> blocked
        assert w100.is_entry_blocked() is True

    # -- T3: Not blocked on small drawdown below threshold --
    def test_not_blocked_on_small_drawdown(self):
        """A 2% drop from HWM (below 5% threshold) must not block."""
        w100.update(10000.0)   # HWM = 10000
        w100.update(9800.0)    # 2% drawdown -> not blocked
        assert w100.is_entry_blocked() is False

    # -- T4: HWM updates upward on new equity peak --
    def test_hwm_updates_on_peak(self):
        """HWM must track the highest equity seen; block uses updated HWM."""
        w100.update(10000.0)   # HWM = 10000
        w100.update(11000.0)   # HWM rises to 11000
        # 4% drop from 11000 = 10560 -> not blocked
        w100.update(10560.0)
        assert w100.is_entry_blocked() is False
        # 6% drop from 11000 = 10340 -> blocked
        w100.reset()
        w100.update(10000.0)
        w100.update(11000.0)
        w100.update(10340.0)
        assert w100.is_entry_blocked() is True

    # -- T5: Invalid inputs ignored; reset() clears all state --
    def test_invalid_inputs_and_reset(self):
        """Bool/NaN/Inf/zero/negative equity values silently rejected."""
        w100.update(True)
        w100.update(False)
        w100.update(float("nan"))
        w100.update(float("inf"))
        w100.update(0.0)
        w100.update(-500.0)
        w100.update("10000")  # type: ignore
        assert w100.is_entry_blocked() is False

        # Force block then reset
        with w100._lock:
            w100._blocked_until = time.monotonic() + 999.0
        assert w100.is_entry_blocked() is True
        w100.reset()
        assert w100.is_entry_blocked() is False
        assert w100._initialized is False
        assert w100._hwm == 0.0


# ===========================================================================
# wave101 — Lot Concentration Guard (5 tests)
# ===========================================================================

class TestWave101LotConcentrationGuard:

    def setup_method(self):
        w101.reset()

    # -- T1: Not blocked below MAX_TOTAL_LOTS --
    def test_not_blocked_below_max(self):
        """Total lots strictly below MAX_TOTAL_LOTS must not block."""
        w101.open_position(1, 1.0)
        w101.open_position(2, 1.0)
        w101.open_position(3, 1.5)
        # total = 3.5 < 5.0
        assert w101.is_entry_blocked() is False

    # -- T2: Blocked when total lots >= MAX_TOTAL_LOTS --
    def test_blocked_at_max_lots(self):
        """Total lots exactly equal to MAX_TOTAL_LOTS must block."""
        w101.open_position(1, 2.0)
        w101.open_position(2, 2.0)
        w101.open_position(3, 1.0)
        # total = 5.0 >= 5.0 -> blocked
        assert w101.is_entry_blocked() is True

    # -- T3: Block lifts when total drops below threshold --
    def test_block_lifts_on_close(self):
        """Closing a position that brings total below MAX_TOTAL_LOTS must unblock."""
        w101.open_position(1, 3.0)
        w101.open_position(2, 2.5)   # total = 5.5 -> blocked
        assert w101.is_entry_blocked() is True
        w101.close_position(2)        # total = 3.0 -> unblocked
        assert w101.is_entry_blocked() is False

    # -- T4: update() is alias for open_position() --
    def test_update_alias(self):
        """update(ticket, lots) must behave identically to open_position()."""
        w101.update(10, 2.5)
        w101.update(11, 2.5)   # total = 5.0 -> blocked
        assert w101.is_entry_blocked() is True
        w101.close_position(10)
        assert w101.is_entry_blocked() is False

    # -- T5: Invalid inputs rejected; reset() clears state --
    def test_invalid_inputs_and_reset(self):
        """Bool ticket, zero lots, NaN lots, negative lots silently rejected."""
        w101.open_position(True, 1.0)     # bool ticket rejected
        w101.open_position(1, True)       # bool lots rejected
        w101.open_position(2, 0.0)        # zero lots rejected
        w101.open_position(3, -0.5)       # negative lots rejected
        w101.open_position(4, float("nan"))  # NaN rejected
        w101.open_position(5, float("inf"))  # Inf rejected
        w101.open_position("", 1.0)       # empty string ticket rejected
        assert w101.is_entry_blocked() is False

        # Fill beyond threshold then reset
        w101.open_position(100, 3.0)
        w101.open_position(101, 3.0)
        assert w101.is_entry_blocked() is True
        w101.reset()
        assert w101.is_entry_blocked() is False
        with w101._lock:
            assert len(w101._positions) == 0
