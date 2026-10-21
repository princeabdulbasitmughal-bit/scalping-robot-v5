"""
tests/test_batch162.py
-----------------------
Unit tests for:
  wave90_slippage_guard       (rolling average fill slippage)
  wave91_funding_rate_guard   (overnight swap/funding rate guard)

5 tests per module = 10 total.
"""

import sys
import os
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave90_slippage_guard as w90
import wave91_funding_rate_guard as w91


# ---------------------------------------------------------------------------
# wave90 tests
# ---------------------------------------------------------------------------

class TestWave90SlippageGuard:

    def setup_method(self):
        w90.reset()

    def test_warmup_fail_closed(self):
        """Fewer than min_samples (5) -> fail-closed, avg returns -1."""
        w90.record_fill(1.10000, 1.10001)
        w90.record_fill(1.10000, 1.10001)
        assert w90.is_entry_blocked() is True
        assert w90.get_avg_slippage_pips() == -1.0

    def test_low_slippage_not_blocked(self):
        """Average slippage of 1 pip (< 3 pip threshold) -> not blocked."""
        base = 1.10000
        for _ in range(6):
            # 1 pip slippage each fill
            w90.record_fill(base, base + 0.0001)
        assert w90.is_entry_blocked() is False
        assert abs(w90.get_avg_slippage_pips() - 1.0) < 0.01

    def test_high_slippage_triggers_block(self):
        """Average slippage >= 3 pips -> triggers cooldown block."""
        base = 1.10000
        for _ in range(6):
            # 5 pip slippage each fill
            w90.record_fill(base, base + 0.0005)
        assert w90.is_entry_blocked() is True
        assert w90.get_avg_slippage_pips() >= 3.0

    def test_reset_clears_state(self):
        """After reset, guard is back in warmup (fail-closed)."""
        base = 1.10000
        for _ in range(6):
            w90.record_fill(base, base + 0.0005)
        assert w90.is_entry_blocked() is True
        w90.reset()
        assert w90.get_avg_slippage_pips() == -1.0
        assert w90.is_entry_blocked() is True  # warmup again

    def test_invalid_prices_ignored(self):
        """bool, NaN, Inf, zero, negative expected/actual prices ignored."""
        w90.record_fill(True, 1.1001)
        w90.record_fill(float("nan"), 1.1001)
        w90.record_fill(1.1000, float("inf"))
        w90.record_fill(0.0, 1.1001)
        w90.record_fill(-1.0, 1.1001)
        # No valid fills -> warmup
        assert w90.is_entry_blocked() is True
        assert w90.get_avg_slippage_pips() == -1.0


# ---------------------------------------------------------------------------
# wave91 tests
# ---------------------------------------------------------------------------

class TestWave91FundingRateGuard:

    def setup_method(self):
        w91.reset()

    def test_no_data_fail_closed(self):
        """Before any update call, guard must be blocked (fail-closed)."""
        assert w91.is_entry_blocked() is True
        assert math.isnan(w91.get_last_swap_pips())

    def test_low_swap_not_blocked(self):
        """Swap of 2.0 pips (< 5 pip threshold) -> not blocked."""
        w91.update(2.0)
        assert w91.is_entry_blocked() is False
        assert w91.get_last_swap_pips() == 2.0

    def test_negative_low_swap_not_blocked(self):
        """Negative swap of -3.0 pips (broker pays; abs < 5) -> not blocked."""
        w91.update(-3.0)
        assert w91.is_entry_blocked() is False

    def test_high_swap_triggers_block(self):
        """Swap of 7.5 pips (> 5 pip threshold) -> triggers block."""
        w91.update(7.5)
        assert w91.is_entry_blocked() is True
        assert w91.get_last_swap_pips() == 7.5

    def test_invalid_swap_ignored(self):
        """bool, NaN, Inf, string swap values must be silently ignored."""
        w91.update(True)
        w91.update(float("nan"))
        w91.update(float("inf"))
        w91.update("bad")
        # No valid update -> still uninitialised -> fail-closed
        assert w91.is_entry_blocked() is True
        assert math.isnan(w91.get_last_swap_pips())
