"""
tests/test_batch172.py
-----------------------
Unit tests for Batch 172 wave modules:
  - wave110_quote_staleness_guard  (5 tests)
  - wave111_slippage_budget_guard  (5 tests)

Baseline before this batch: 1,964 collected items
Expected after: 1,974 collected items
"""

import math
import time
import threading
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave110_quote_staleness_guard as w110
import wave111_slippage_budget_guard as w111


# ===========================================================================
# wave110 — Quote Staleness Guard (5 tests)
# ===========================================================================

class TestWave110QuoteStalenessGuard:

    def setup_method(self):
        w110.reset()

    # -- T1: Fail-closed before any quote is received --
    def test_blocked_initially_fail_closed(self):
        """Guard must be blocked before the first quote arrives."""
        assert w110.is_entry_blocked() is True

    # -- T2: Unblocked immediately upon fresh quote --
    def test_unblocked_on_fresh_quote(self):
        """Recording a fresh quote immediately clears the block."""
        w110.record_quote(bid=1.1000, ask=1.1002)
        assert w110.is_entry_blocked() is False

    # -- T3: Blocked when quote becomes older than MAX_STALENESS_SECONDS --
    def test_blocked_on_stale_quote(self):
        """When elapsed time exceeds MAX_STALENESS_SECONDS, entries must block."""
        w110.record_quote()
        assert w110.is_entry_blocked() is False

        # Backdate last quote time
        with w110._lock:
            w110._last_quote_time = time.monotonic() - (w110.MAX_STALENESS_SECONDS + 1.0)
        assert w110.is_entry_blocked() is True

    # -- T4: update() works as alias for record_quote --
    def test_update_alias(self):
        """update() must record quote and refresh timestamp."""
        w110.update()
        assert w110.is_entry_blocked() is False

    # -- T5: Invalid inputs ignored; reset() restores uninitialized state --
    def test_invalid_inputs_and_reset(self):
        """Invalid bid/ask rejected; reset() restores blocked uninitialized state."""
        w110.record_quote(bid=float("nan"), ask=1.10)
        assert w110.is_entry_blocked() is True  # still uninitialized

        w110.record_quote(bid=1.10, ask=float("inf"))
        assert w110.is_entry_blocked() is True

        w110.record_quote(bid=-1.0, ask=1.10)
        assert w110.is_entry_blocked() is True

        w110.record_quote(bid=1.10, ask=1.12)
        assert w110.is_entry_blocked() is False

        w110.reset()
        assert w110.is_entry_blocked() is True
        assert w110._last_quote_time == -1.0


# ===========================================================================
# wave111 — Cumulative Slippage Budget Guard (5 tests)
# ===========================================================================

class TestWave111SlippageBudgetGuard:

    def setup_method(self):
        w111.reset()

    # -- T1: Not blocked below budget --
    def test_not_blocked_below_budget(self):
        """Total adverse slippage of 8 pips < 15 pips limit does not block."""
        w111.record_slippage(4.0)
        w111.record_slippage(4.0)
        assert w111.is_entry_blocked() is False

    # -- T2: Blocked when slippage budget is reached --
    def test_blocked_at_budget(self):
        """15.0 pips total adverse slippage meets threshold and blocks."""
        w111.record_slippage(10.0)
        w111.record_slippage(5.0)
        assert w111.is_entry_blocked() is True

    # -- T3: Price improvements (negative slippage) do not add adverse slippage --
    def test_price_improvements_clamped(self):
        """Negative slippage does not count as adverse slippage."""
        w111.record_slippage(-5.0)
        w111.record_slippage(-10.0)
        assert w111._cumulative_adverse_pips == 0.0
        assert w111.is_entry_blocked() is False

    # -- T4: update() works as alias for record_slippage --
    def test_update_alias(self):
        """update() functions identically to record_slippage()."""
        w111.update(16.0)
        assert w111.is_entry_blocked() is True

    # -- T5: Invalid inputs rejected; reset() clears budget --
    def test_invalid_inputs_and_reset(self):
        """Boolean, NaN, and Inf inputs are ignored; reset() clears all state."""
        w111.record_slippage(True)
        w111.record_slippage(float("nan"))
        w111.record_slippage(float("inf"))
        w111.record_slippage("5.0")
        assert w111._cumulative_adverse_pips == 0.0

        w111.record_slippage(20.0)
        assert w111.is_entry_blocked() is True
        w111.reset()
        assert w111.is_entry_blocked() is False
        assert w111._cumulative_adverse_pips == 0.0
