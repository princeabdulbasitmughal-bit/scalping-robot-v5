"""
Batch 287 -- Tests for Wave 340 and Wave 341
============================================
Wave 340: LOB Depth-Weighted Mid-Price Skew Persistence Guard  [LANDMARK WAVE 340]
Wave 341: Trade Flow Inter-Arrival Time Coefficient-of-Variation Guard

Target: 15 new tests, 0 failures
Baseline before: 3,123 passed, 1 skipped
Baseline after:  3,138 passed, 1 skipped
"""

import math
import time
import pytest

from wave340_lob_depth_weighted_mid_price_skew_persistence_guard import (
    Wave340LOBDepthWeightedMidPriceSkewPersistenceGuard,
)
from wave341_trade_flow_inter_arrival_cov_guard import (
    Wave341TradeFlowInterArrivalCovGuard,
)


# ─────────────────────────────────────────────────────────────
# Wave 340 -- Micro-Price Skew Persistence Guard Tests
# ─────────────────────────────────────────────────────────────


class TestWave340SkewPersistenceGuard:
    """Tests for depth-weighted mid-price skew persistence guard."""

    def _make_guard(self, **kw):
        defaults = dict(
            window_size=10,
            persist_threshold=2.0,
            min_skew_bps=0.5,
            cooldown_seconds=60.0,
        )
        defaults.update(kw)
        return Wave340LOBDepthWeightedMidPriceSkewPersistenceGuard(**defaults)

    def _tick(self, guard, bid, ask, bid_size, ask_size, ts):
        guard.update(bid, ask, bid_size, ask_size, ts)

    def test_wave340_no_block_before_window_fills(self):
        """Guard must not block before window_size skews accumulated."""
        guard = self._make_guard(window_size=10)
        t0 = time.monotonic()
        # 9 ticks only
        for i in range(9):
            self._tick(guard, 1.1000, 1.10011, 100.0, 100.0, t0 + i)
        assert not guard.is_blocked(t0 + 9), "Should not block before window fills"

    def test_wave340_balanced_book_no_block(self):
        """Perfectly balanced book (equal bid/ask sizes) has zero skew; no block."""
        guard = self._make_guard(persist_threshold=2.0)
        t0 = time.monotonic()
        # Equal sizes -> micro_price == mid -> skew == 0
        for i in range(20):
            self._tick(guard, 1.1000, 1.10011, 100.0, 100.0, t0 + i)
        assert not guard.is_blocked(t0 + 20), "Balanced book has zero skew; should not block"

    def test_wave340_persistent_bid_heavy_skew_blocks(self):
        """Persistent bid-heavy book (large bid_size > ask_size) should block."""
        guard = self._make_guard(persist_threshold=2.0, min_skew_bps=0.2)
        t0 = time.monotonic()
        # bid_size >> ask_size -> micro_price pulled toward ask -> positive skew
        for i in range(20):
            self._tick(guard, 1.1000, 1.10011, 1000.0, 10.0, t0 + i)
        assert guard.is_blocked(t0 + 20), "Persistent bid-heavy skew should block"
        assert guard.last_reason == "MICRO_PRICE_SKEW_PERSISTENCE"

    def test_wave340_alternating_skew_no_block(self):
        """Alternating bid-heavy / ask-heavy book cancels skew mean; no block."""
        guard = self._make_guard(persist_threshold=2.0, min_skew_bps=0.2)
        t0 = time.monotonic()
        for i in range(20):
            if i % 2 == 0:
                self._tick(guard, 1.1000, 1.10011, 1000.0, 10.0, t0 + i)
            else:
                self._tick(guard, 1.1000, 1.10011, 10.0, 1000.0, t0 + i)
        assert not guard.is_blocked(t0 + 20), "Alternating skew cancels; should not block"

    def test_wave340_invalid_negative_bid_size_blocks(self):
        """Non-positive bid_size must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(1.1000, 1.10011, -1.0, 100.0, t0)
        assert guard.is_blocked(t0 + 0.001)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave340_bool_bid_blocks(self):
        """Boolean bid must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(True, 1.10011, 100.0, 100.0, t0)
        assert guard.is_blocked(t0 + 0.001)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave340_crossed_quotes_block(self):
        """Crossed quote (ask <= bid) must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(1.1001, 1.1000, 100.0, 100.0, t0)
        assert guard.is_blocked(t0 + 0.001)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave340_reset_clears_state(self):
        """Reset must clear all accumulated skews and block state."""
        guard = self._make_guard(persist_threshold=2.0, min_skew_bps=0.2)
        t0 = time.monotonic()
        for i in range(20):
            guard.update(1.1000, 1.10011, 1000.0, 10.0, t0 + i)
        assert guard.is_blocked(t0 + 20)
        guard.reset()
        assert not guard.is_blocked(t0 + 20), "After reset, guard should be unblocked"
        assert guard.last_reason == ""


# ─────────────────────────────────────────────────────────────
# Wave 341 -- Inter-Arrival CoV Guard Tests
# ─────────────────────────────────────────────────────────────


class TestWave341InterArrivalCovGuard:
    """Tests for the trade inter-arrival time CoV guard."""

    def _make_guard(self, **kw):
        defaults = dict(
            window_size=10,
            high_cov_threshold=3.0,
            low_cov_threshold=0.05,
            cooldown_seconds=45.0,
        )
        defaults.update(kw)
        return Wave341TradeFlowInterArrivalCovGuard(**defaults)

    def test_wave341_no_block_before_window_fills(self):
        """Guard must not block before window_size deltas accumulated."""
        guard = self._make_guard(window_size=10)
        t0 = time.monotonic()
        for i in range(5):  # only 5 ticks -> 4 deltas < 10
            guard.update(t0 + i * 0.1)
        assert not guard.is_blocked(t0 + 0.5), "Should not block before window fills"

    def test_wave341_regular_intervals_triggers_block(self):
        """Perfectly regular arrivals (CoV=0) should trigger REGULAR_INTER_ARRIVAL."""
        guard = self._make_guard(high_cov_threshold=3.0, low_cov_threshold=0.05)
        t0 = time.monotonic()
        # Perfectly equal intervals -> CoV = 0 < 0.05
        for i in range(20):
            guard.update(t0 + i * 0.1)
        assert guard.is_blocked(t0 + 2.0), "CoV=0 should trigger regular block"
        assert guard.last_reason == "REGULAR_INTER_ARRIVAL"

    def test_wave341_bursty_intervals_triggers_block(self):
        """Extremely bursty arrivals (high CoV) should trigger BURSTY_INTER_ARRIVAL."""
        guard = self._make_guard(high_cov_threshold=2.0, low_cov_threshold=0.01)
        t0 = time.monotonic()
        # Burst of rapid arrivals followed by long lull -> high CoV
        ts = t0
        for i in range(25):
            if i % 10 == 0 and i > 0:
                ts += 10.0    # long pause
            else:
                ts += 0.001   # rapid burst
            guard.update(ts)
        assert guard.is_blocked(ts + 0.1), "Bursty arrivals should trigger block"
        assert guard.last_reason == "BURSTY_INTER_ARRIVAL"

    def test_wave341_moderate_cov_no_block(self):
        """Moderate CoV (between thresholds) should not block."""
        guard = self._make_guard(high_cov_threshold=3.0, low_cov_threshold=0.05)
        t0 = time.monotonic()
        # Intervals: 0.1, 0.2, 0.1, 0.2, ... -> CoV ~ 0.4 (moderate)
        ts = t0
        for i in range(20):
            ts += 0.1 if i % 2 == 0 else 0.2
            guard.update(ts)
        assert not guard.is_blocked(ts + 0.1), "Moderate CoV should not block"

    def test_wave341_bool_timestamp_blocks(self):
        """Boolean timestamp must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        guard.update(True)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave341_negative_delta_blocks(self):
        """Decreasing timestamps (negative delta) must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(t0 + 1.0)
        guard.update(t0)  # goes backward
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave341_reset_clears_state(self):
        """Reset must clear all deltas and block state."""
        guard = self._make_guard()
        t0 = time.monotonic()
        for i in range(20):
            guard.update(t0 + i * 0.1)
        assert guard.is_blocked(t0 + 2.0)
        guard.reset()
        assert not guard.is_blocked(t0 + 2.0), "After reset, guard should be unblocked"
        assert guard.last_reason == ""
