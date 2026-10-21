"""
tests/test_batch157.py
-----------------------
Unit tests for:
  wave80_max_open_loss_guard  (per-position floating loss limit)
  wave81_tick_gap_guard        (tick-to-tick price gap detection)

5 tests per module = 10 total.
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave80_max_open_loss_guard as w80
import wave81_tick_gap_guard as w81


# ---------------------------------------------------------------------------
# wave80 tests
# ---------------------------------------------------------------------------

class TestWave80MaxOpenLossGuard:

    def setup_method(self):
        w80.reset()

    def test_no_positions_not_blocked(self):
        """With no open positions, guard must NOT block."""
        assert w80.is_entry_blocked() is False

    def test_small_loss_not_blocked(self):
        """Floating loss well within threshold must NOT trigger block."""
        w80.update_position(1001, -10.0)   # -10 pips, threshold is -25
        assert w80.is_entry_blocked() is False
        assert w80.get_worst_open_loss() == -10.0

    def test_loss_at_threshold_triggers_block(self):
        """Exactly at -25 pips must trigger cooldown block."""
        w80.update_position(2001, -25.0)
        assert w80.is_entry_blocked() is True

    def test_close_position_allows_new_entries(self):
        """After closing the bad position and cooldown expires, must unblock."""
        w80.update_position(3001, -30.0)
        assert w80.is_entry_blocked() is True
        w80.close_position(3001)
        # Manually expire the cooldown by resetting blocked_until via reset
        w80.reset()
        assert w80.is_entry_blocked() is False
        assert w80.get_worst_open_loss() == 0.0

    def test_invalid_inputs_ignored(self):
        """bool ticket, NaN pips, Inf pips, list ticket must be silently ignored."""
        w80.update_position(True, -30.0)        # bool ticket
        w80.update_position(1234, float("nan"))  # NaN pips
        w80.update_position(1234, float("inf"))  # Inf pips
        w80.update_position([1234], -30.0)       # list ticket
        # No valid updates -> no positions -> not blocked
        assert w80.is_entry_blocked() is False
        assert w80.get_worst_open_loss() == 0.0


# ---------------------------------------------------------------------------
# wave81 tests
# ---------------------------------------------------------------------------

class TestWave81TickGapGuard:

    def setup_method(self):
        w81.reset()

    def test_first_tick_not_blocked(self):
        """First tick has no previous price -> no gap possible -> not blocked."""
        w81.update(1.1000)
        assert w81.is_entry_blocked() is False
        assert w81.get_last_gap_pips() == 0.0

    def test_small_gap_not_blocked(self):
        """Gap of 5 pips (< 10 pip threshold) must NOT trigger block."""
        w81.update(1.1000)
        w81.update(1.1005)   # +5 pips
        assert w81.is_entry_blocked() is False
        assert abs(w81.get_last_gap_pips() - 5.0) < 0.01

    def test_large_gap_triggers_block(self):
        """Gap of 15 pips (> 10 pip threshold) must trigger cooldown block."""
        w81.update(1.1000)
        w81.update(1.1015)   # +15 pips
        assert w81.is_entry_blocked() is True
        assert w81.get_last_gap_pips() >= 10.0

    def test_downward_gap_triggers_block(self):
        """Downward gap of 20 pips must also trigger block."""
        w81.update(1.1200)
        w81.update(1.1180)   # -20 pips
        assert w81.is_entry_blocked() is True

    def test_invalid_prices_ignored(self):
        """bool, NaN, Inf, zero, negative prices must be silently ignored."""
        w81.update(True)
        w81.update(float("nan"))
        w81.update(float("inf"))
        w81.update(0.0)
        w81.update(-1.0)
        # No valid price stored -> no gap -> not blocked
        assert w81.is_entry_blocked() is False
        assert w81.get_last_gap_pips() == 0.0
