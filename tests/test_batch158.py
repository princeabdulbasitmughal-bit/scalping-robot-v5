"""
tests/test_batch158.py
-----------------------
Unit tests for:
  wave82_order_rate_guard      (sliding-window order rate limiter)
  wave83_price_deviation_guard (bid/ask midpoint deviation from rolling mean)

5 tests per module = 10 total.
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import wave82_order_rate_guard as w82
import wave83_price_deviation_guard as w83


# ---------------------------------------------------------------------------
# wave82 tests
# ---------------------------------------------------------------------------

class TestWave82OrderRateGuard:

    def setup_method(self):
        w82.reset()

    def test_empty_deque_not_blocked(self):
        """No orders recorded -> not blocked."""
        assert w82.is_entry_blocked() is False
        assert w82.get_order_count() == 0

    def test_below_limit_not_blocked(self):
        """9 orders (< limit of 10) must NOT block."""
        for _ in range(9):
            w82.record_order()
        assert w82.is_entry_blocked() is False
        assert w82.get_order_count() == 9

    def test_at_limit_triggers_block(self):
        """Exactly 10 orders in the window must trigger block."""
        for _ in range(10):
            w82.record_order()
        assert w82.is_entry_blocked() is True

    def test_reset_clears_block(self):
        """After reset, guard must be clear."""
        for _ in range(10):
            w82.record_order()
        assert w82.is_entry_blocked() is True
        w82.reset()
        assert w82.is_entry_blocked() is False
        assert w82.get_order_count() == 0

    def test_update_alias_works(self):
        """update() alias must behave identically to record_order()."""
        for _ in range(10):
            w82.update()
        assert w82.is_entry_blocked() is True


# ---------------------------------------------------------------------------
# wave83 tests
# ---------------------------------------------------------------------------

class TestWave83PriceDeviationGuard:

    def setup_method(self):
        w83.reset()

    def test_warmup_fail_closed(self):
        """Before window_size (20) midpoints are fed, guard is blocked."""
        for i in range(15):
            w83.update(1.1000 + i * 0.0001, 1.1001 + i * 0.0001)
        assert w83.is_entry_blocked() is True
        assert w83.get_rolling_mean() == -1.0

    def test_stable_prices_not_blocked(self):
        """Midpoints tightly clustered (< 0.5% deviation) must not block."""
        w83.reset()
        base = 1.10000
        for i in range(25):
            bid = base + i * 0.000001   # tiny variation
            ask = bid + 0.0001
            w83.update(bid, ask)
        assert w83.is_entry_blocked() is False

    def test_large_deviation_triggers_block(self):
        """A sudden 1% mid-price spike must trigger cooldown block."""
        w83.reset()
        base = 1.10000
        # Seed 20 stable ticks
        for _ in range(20):
            w83.update(base, base + 0.0001)
        assert w83.is_entry_blocked() is False
        # Now spike +1% from mean
        spike = base * 1.01
        w83.update(spike, spike + 0.0001)
        assert w83.is_entry_blocked() is True

    def test_bid_ge_ask_rejected(self):
        """Degenerate ticks where bid >= ask must be silently ignored."""
        w83.reset()
        base = 1.10000
        for _ in range(20):
            w83.update(base, base + 0.0001)
        count_before = len(w83._midpoints)
        w83.update(1.1010, 1.1005)   # bid > ask
        w83.update(1.1010, 1.1010)   # bid == ask
        assert len(w83._midpoints) == count_before  # no new points added

    def test_invalid_prices_ignored(self):
        """bool, NaN, Inf, zero, negative prices must be silently ignored."""
        w83.reset()
        w83.update(True, 1.1001)
        w83.update(float("nan"), 1.1001)
        w83.update(1.1000, float("inf"))
        w83.update(0.0, 1.1001)
        w83.update(-1.0, 1.1001)
        # No valid ticks -> still in warmup -> blocked (fail-closed)
        assert w83.is_entry_blocked() is True
        assert w83.get_rolling_mean() == -1.0
