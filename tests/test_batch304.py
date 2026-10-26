# tests/test_batch304.py
# Combined pytest test file for batch 304
#   Wave 366 -- LOB Top-of-Book Persistence Guard
#   Wave 367 -- Trade Flow Bulk Trade Accumulation Guard
#
# Self-contained: no external dependencies beyond the two guard modules.
# ASCII-only content. No live server calls.

import sys
import os
import time

import pytest

# ---------------------------------------------------------------------------
# Make project root importable when running from the tests/ sub-directory
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wave366_lob_top_of_book_persistence_guard import (
    Wave366LobTopOfBookPersistenceGuard,
)
from wave367_trade_flow_bulk_trade_accumulation_guard import (
    Wave367TradeFlowBulkTradeAccumulationGuard,
)


# ===========================================================================
# Helpers
# ===========================================================================

def make_w366(max_persistence_ticks=5, cooldown_seconds=30.0):
    return Wave366LobTopOfBookPersistenceGuard(
        max_persistence_ticks=max_persistence_ticks,
        cooldown_seconds=cooldown_seconds,
    )


def make_w367(large_trade_threshold=50.0, max_bulk_count=3, cooldown_seconds=30.0):
    return Wave367TradeFlowBulkTradeAccumulationGuard(
        large_trade_threshold=large_trade_threshold,
        max_bulk_count=max_bulk_count,
        cooldown_seconds=cooldown_seconds,
    )


# ===========================================================================
# Wave 366 Tests
# ===========================================================================

class TestWave366NoblockBeforeWindowFills:
    """Guard must NOT block before persistence_count reaches the threshold."""

    def test_first_tick_no_block(self):
        g = make_w366(max_persistence_ticks=5)
        g.update(1.1000, 1.1005, time.monotonic())
        assert not g.is_blocked()

    def test_below_threshold_unchanged_quote(self):
        g = make_w366(max_persistence_ticks=5)
        g.update(1.1000, 1.1005, time.monotonic())
        # 4 more identical ticks -> persistence_count == 4, threshold == 5
        for _ in range(4):
            g.update(1.1000, 1.1005, time.monotonic())
        assert not g.is_blocked()
        assert g.last_reason is None

    def test_quote_change_resets_count(self):
        g = make_w366(max_persistence_ticks=3)
        g.update(1.0, 1.1, time.monotonic())
        g.update(1.0, 1.1, time.monotonic())   # count = 1
        g.update(1.0, 1.1, time.monotonic())   # count = 2  (still < 3)
        # now change quote
        g.update(1.0, 1.2, time.monotonic())   # count resets -> 0
        g.update(1.0, 1.2, time.monotonic())   # count = 1
        assert not g.is_blocked()


class TestWave366HappyPathBlock:
    """Guard must block exactly at the threshold."""

    def test_blocks_at_threshold(self):
        g = make_w366(max_persistence_ticks=3, cooldown_seconds=10.0)
        g.update(1.0, 1.1, time.monotonic())   # first tick, no count
        g.update(1.0, 1.1, time.monotonic())   # count = 1
        g.update(1.0, 1.1, time.monotonic())   # count = 2
        g.update(1.0, 1.1, time.monotonic())   # count = 3 -> BLOCK
        assert g.is_blocked()
        assert g.last_reason == "TOP_OF_BOOK_STALENESS"

    def test_cooldown_deadline_is_monotonic(self):
        g = make_w366(max_persistence_ticks=2, cooldown_seconds=60.0)
        g.update(1.0, 1.1, time.monotonic())
        g.update(1.0, 1.1, time.monotonic())
        g.update(1.0, 1.1, time.monotonic())   # count = 2 -> BLOCK
        # Simulating "now + 0 seconds" should still be blocked
        assert g.is_blocked(current_time=time.monotonic())
        # Simulating far future should be open
        assert not g.is_blocked(current_time=time.monotonic() + 120.0)


class TestWave366InvalidInputBlocks:
    """Any invalid input must trigger INPUT_VALIDATION_ERROR immediately."""

    def test_non_numeric_bid_blocks(self):
        g = make_w366()
        g.update("one", 1.1, time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_bool_bid_blocks(self):
        # bool is subclass of int; guard must reject it explicitly
        g = make_w366()
        g.update(True, 1.1, time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_ask_le_bid_blocks(self):
        g = make_w366()
        g.update(1.1, 1.0, time.monotonic())   # ask < bid
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_negative_bid_blocks(self):
        g = make_w366()
        g.update(-1.0, 1.1, time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_nan_ask_blocks(self):
        import math
        g = make_w366()
        g.update(1.0, float("nan"), time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"


class TestWave366ResetClearsState:
    """reset() must fully clear the block and state."""

    def test_reset_after_block(self):
        g = make_w366(max_persistence_ticks=2, cooldown_seconds=60.0)
        g.update(1.0, 1.1, time.monotonic())
        g.update(1.0, 1.1, time.monotonic())
        g.update(1.0, 1.1, time.monotonic())   # block
        assert g.is_blocked()
        g.reset()
        assert not g.is_blocked()
        assert g.last_reason is None

    def test_reset_allows_fresh_accumulation(self):
        g = make_w366(max_persistence_ticks=2, cooldown_seconds=60.0)
        g.update(1.0, 1.1, time.monotonic())
        g.update(1.0, 1.1, time.monotonic())
        g.update(1.0, 1.1, time.monotonic())
        g.reset()
        # After reset a single unchanged tick should NOT block
        g.update(2.0, 2.1, time.monotonic())
        assert not g.is_blocked()


class TestWave366IsEntryBlocked:
    """is_entry_blocked must reject bad inputs and delegate to is_blocked."""

    def test_invalid_bid_returns_true(self):
        g = make_w366()
        assert g.is_entry_blocked("bad", 1.1) is True

    def test_valid_inputs_when_not_blocked(self):
        g = make_w366()
        assert g.is_entry_blocked(1.0, 1.1) is False

    def test_delegates_when_blocked(self):
        g = make_w366(max_persistence_ticks=2, cooldown_seconds=60.0)
        g.update(1.0, 1.1, time.monotonic())
        g.update(1.0, 1.1, time.monotonic())
        g.update(1.0, 1.1, time.monotonic())
        assert g.is_entry_blocked(1.0, 1.1) is True


# ===========================================================================
# Wave 367 Tests
# ===========================================================================

class TestWave367NoblockBeforeWindowFills:
    """Guard must NOT block until bulk_count reaches max_bulk_count."""

    def test_single_large_trade_no_block(self):
        g = make_w367(large_trade_threshold=50.0, max_bulk_count=3)
        g.update(100.0, "buy", time.monotonic())
        assert not g.is_blocked()

    def test_below_threshold_count_no_block(self):
        g = make_w367(large_trade_threshold=50.0, max_bulk_count=4)
        # 3 consecutive large buys -> count = 3, threshold = 4
        for _ in range(3):
            g.update(100.0, "buy", time.monotonic())
        assert not g.is_blocked()
        assert g.last_reason is None

    def test_small_trade_breaks_streak(self):
        g = make_w367(large_trade_threshold=50.0, max_bulk_count=3)
        g.update(100.0, "buy", time.monotonic())   # count = 1
        g.update(100.0, "buy", time.monotonic())   # count = 2
        g.update(10.0, "buy", time.monotonic())    # small -> reset
        g.update(100.0, "buy", time.monotonic())   # count = 1 (fresh)
        assert not g.is_blocked()

    def test_direction_change_resets_count(self):
        g = make_w367(large_trade_threshold=50.0, max_bulk_count=3)
        g.update(100.0, "buy", time.monotonic())   # count buy = 1
        g.update(100.0, "buy", time.monotonic())   # count buy = 2
        g.update(100.0, "sell", time.monotonic())  # direction change -> count sell = 1
        g.update(100.0, "sell", time.monotonic())  # count sell = 2
        assert not g.is_blocked()


class TestWave367HappyPathBlock:
    """Guard must block at max_bulk_count consecutive same-direction large trades."""

    def test_blocks_at_max_bulk_count(self):
        g = make_w367(large_trade_threshold=50.0, max_bulk_count=3, cooldown_seconds=30.0)
        g.update(100.0, "buy", time.monotonic())
        g.update(100.0, "buy", time.monotonic())
        g.update(100.0, "buy", time.monotonic())   # count = 3 -> BLOCK
        assert g.is_blocked()
        assert g.last_reason == "BULK_ACCUMULATION_DETECTED"

    def test_sell_side_also_blocks(self):
        g = make_w367(large_trade_threshold=50.0, max_bulk_count=3, cooldown_seconds=30.0)
        for _ in range(3):
            g.update(200.0, "sell", time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == "BULK_ACCUMULATION_DETECTED"

    def test_exact_threshold_volume_counts_as_large(self):
        g = make_w367(large_trade_threshold=50.0, max_bulk_count=2, cooldown_seconds=30.0)
        g.update(50.0, "buy", time.monotonic())    # exactly at threshold
        g.update(50.0, "buy", time.monotonic())    # count = 2 -> BLOCK
        assert g.is_blocked()


class TestWave367InvalidInputBlocks:
    """Any invalid input must trigger INPUT_VALIDATION_ERROR immediately."""

    def test_non_numeric_volume_blocks(self):
        g = make_w367()
        g.update("lots", "buy", time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_bool_volume_blocks(self):
        g = make_w367()
        g.update(True, "buy", time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_invalid_side_blocks(self):
        g = make_w367()
        g.update(100.0, "long", time.monotonic())   # "long" is not valid
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_negative_volume_blocks(self):
        g = make_w367()
        g.update(-100.0, "sell", time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_zero_volume_blocks(self):
        g = make_w367()
        g.update(0.0, "buy", time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_side_none_blocks(self):
        g = make_w367()
        g.update(100.0, None, time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"


class TestWave367ResetClearsState:
    """reset() must clear all state including block and streak."""

    def test_reset_after_block(self):
        g = make_w367(max_bulk_count=2, cooldown_seconds=60.0)
        g.update(100.0, "buy", time.monotonic())
        g.update(100.0, "buy", time.monotonic())
        assert g.is_blocked()
        g.reset()
        assert not g.is_blocked()
        assert g.last_reason is None

    def test_reset_allows_fresh_streak(self):
        g = make_w367(max_bulk_count=2, cooldown_seconds=60.0)
        g.update(100.0, "buy", time.monotonic())
        g.update(100.0, "buy", time.monotonic())
        g.reset()
        # Single trade after reset must NOT block
        g.update(100.0, "sell", time.monotonic())
        assert not g.is_blocked()


class TestWave367IsEntryBlocked:
    """is_entry_blocked must reject bad bid/ask and delegate to is_blocked."""

    def test_invalid_bid_returns_true(self):
        g = make_w367()
        assert g.is_entry_blocked("bad", 1.1) is True

    def test_bool_ask_returns_true(self):
        g = make_w367()
        assert g.is_entry_blocked(1.0, True) is True

    def test_valid_inputs_when_not_blocked(self):
        g = make_w367()
        assert g.is_entry_blocked(1.0, 1.1) is False

    def test_delegates_when_blocked(self):
        g = make_w367(max_bulk_count=2, cooldown_seconds=60.0)
        g.update(100.0, "buy", time.monotonic())
        g.update(100.0, "buy", time.monotonic())
        assert g.is_entry_blocked(1.0, 1.1) is True
