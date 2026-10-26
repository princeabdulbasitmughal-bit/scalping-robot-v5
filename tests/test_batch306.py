"""
tests/test_batch306.py
Combined pytest suite for Batch 306:
  - Wave 370: LOBSpreadCompressionMomentumGuard
  - Wave 371: TradeFlowEntropyRateGuard

Rules:
  - No external dependencies beyond the two guard modules.
  - Use time.monotonic() for timestamps.
  - >= 12 tests covering both guards.
"""

import math
import sys
import time
import os

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap so tests run from repo root or from tests/ directory
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wave370_lob_spread_compression_momentum_guard import (
    LOBSpreadCompressionMomentumGuard,
)
from wave371_trade_flow_entropy_rate_guard import TradeFlowEntropyRateGuard


# ===========================================================================
# Helpers
# ===========================================================================

def _ts():
    """Return current monotonic timestamp."""
    return time.monotonic()


def _make_w370(**kwargs):
    """Return a LOBSpreadCompressionMomentumGuard with test-friendly defaults."""
    defaults = dict(
        window_size=5,
        lookback=2,
        compression_threshold_bps=0.5,
        cooldown_seconds=0.05,
    )
    defaults.update(kwargs)
    return LOBSpreadCompressionMomentumGuard(**defaults)


def _make_w371(**kwargs):
    """Return a TradeFlowEntropyRateGuard with test-friendly defaults."""
    defaults = dict(
        window_size=8,
        large_vol_threshold=100.0,
        low_entropy_threshold=0.8,
        high_entropy_threshold=1.95,
        cooldown_seconds=0.05,
    )
    defaults.update(kwargs)
    return TradeFlowEntropyRateGuard(**defaults)


# ===========================================================================
# Wave 370 -- LOBSpreadCompressionMomentumGuard
# ===========================================================================


class TestW370NoBlockBeforeWindowFills:
    """Guard must NOT block before the momentum window is full."""

    def test_no_block_with_fewer_ticks_than_window(self):
        g = _make_w370(window_size=5, lookback=2)
        # Fewer than (window_size + lookback) raw spreads => no momenta computed
        for _ in range(4):
            g.update(1.0000, 1.0005, _ts())
        assert not g.is_blocked(), "Should not block before window fills"

    def test_no_block_partial_momenta(self):
        g = _make_w370(window_size=5, lookback=2)
        # Even with some momenta accumulated but < window_size, no block
        for _ in range(5):
            g.update(1.0000, 1.0005, _ts())
        # 5 raw values with lookback=2 => 3 momenta, window_size=5 => no trigger
        assert not g.is_blocked()


class TestW370HappyPath:
    """Guard must NOT block when spread is stable or expanding."""

    def test_stable_spread_no_block(self):
        g = _make_w370(window_size=5, lookback=2, compression_threshold_bps=0.5)
        # Identical ticks -> zero momentum -> no block
        for _ in range(12):
            g.update(1.0000, 1.0010, _ts())
        assert not g.is_blocked()
        assert g.last_reason is None

    def test_expanding_spread_no_block(self):
        g = _make_w370(window_size=5, lookback=2, compression_threshold_bps=0.5)
        ask = 1.0010
        for i in range(12):
            # spread grows each tick => positive momentum => no compression
            g.update(1.0000, ask + i * 0.0001, _ts())
        assert not g.is_blocked()


class TestW370TriggerBlock:
    """Guard MUST block on rapid spread compression."""

    def test_rapid_compression_triggers_block(self):
        g = _make_w370(window_size=5, lookback=2, compression_threshold_bps=0.5)
        # Start with wide spread then rapidly compress
        ask_prices = [1.0020, 1.0018, 1.0015, 1.0012, 1.0009, 1.0006, 1.0004, 1.0003, 1.0002]
        for ask in ask_prices:
            g.update(1.0000, ask, _ts())
        assert g.is_blocked(), "Rapidly shrinking spread should trigger block"
        assert g.last_reason == "SPREAD_COMPRESSION_MOMENTUM"

    def test_block_reason_is_spread_compression(self):
        g = _make_w370(window_size=5, lookback=2, compression_threshold_bps=0.5)
        ask_prices = [1.0020, 1.0018, 1.0015, 1.0012, 1.0009, 1.0006, 1.0004, 1.0003, 1.0002]
        for ask in ask_prices:
            g.update(1.0000, ask, _ts())
        assert g.last_reason == "SPREAD_COMPRESSION_MOMENTUM"


class TestW370InvalidInput:
    """Any invalid input must cause INPUT_VALIDATION_ERROR block (fail-closed)."""

    def test_bool_bid_blocks(self):
        g = _make_w370()
        g.update(True, 1.0010, _ts())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_none_ask_blocks(self):
        g = _make_w370()
        g.update(1.0000, None, _ts())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_string_timestamp_blocks(self):
        g = _make_w370()
        g.update(1.0000, 1.0010, "now")
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_ask_equal_bid_blocks(self):
        g = _make_w370()
        g.update(1.0000, 1.0000, _ts())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_negative_bid_blocks(self):
        g = _make_w370()
        g.update(-1.0, 1.0010, _ts())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"


class TestW370Reset:
    """reset() must clear all state and cooldown."""

    def test_reset_clears_block(self):
        g = _make_w370(window_size=5, lookback=2, compression_threshold_bps=0.5)
        ask_prices = [1.0020, 1.0018, 1.0015, 1.0012, 1.0009, 1.0006, 1.0004, 1.0003, 1.0002]
        for ask in ask_prices:
            g.update(1.0000, ask, _ts())
        assert g.is_blocked()
        g.reset()
        assert not g.is_blocked()
        assert g.last_reason is None

    def test_reset_clears_accumulated_state(self):
        g = _make_w370(window_size=5, lookback=2, compression_threshold_bps=0.5)
        for _ in range(8):
            g.update(1.0000, 1.0010, _ts())
        g.reset()
        # After reset with stable spread, should not block even if window fills again
        for _ in range(12):
            g.update(1.0000, 1.0010, _ts())
        assert not g.is_blocked()


class TestW370IsEntryBlocked:
    """is_entry_blocked() must ingest tick and reflect block state."""

    def test_is_entry_blocked_delegates(self):
        g = _make_w370()
        # Valid tick, window not full -> not blocked
        result = g.is_entry_blocked(1.0000, 1.0010, _ts())
        assert isinstance(result, bool)

    def test_is_entry_blocked_invalid_returns_true(self):
        g = _make_w370()
        result = g.is_entry_blocked(True, 1.0010, _ts())
        assert result is True


# ===========================================================================
# Wave 371 -- TradeFlowEntropyRateGuard
# ===========================================================================


class TestW371NoBlockBeforeWindowFills:
    """Guard must NOT block before the rolling window is full."""

    def test_no_block_with_partial_window(self):
        g = _make_w371(window_size=8)
        for _ in range(5):
            g.update(50.0, "buy", _ts())
        assert not g.is_blocked()
        assert g.last_reason is None


class TestW371HappyPath:
    """Guard must NOT block when entropy is in the normal range."""

    def test_balanced_flow_no_block(self):
        # Equal mix of all 4 bins => entropy = log2(4) = 2.0
        # But our high threshold is 1.95 => this WOULD block on HIGH_FLOW_ENTROPY
        # So use a 2-bin balanced mix (buy/sell large) that stays inside window
        g = _make_w371(
            window_size=8,
            low_entropy_threshold=0.5,
            high_entropy_threshold=2.0,
        )
        labels = [
            (200.0, "buy"), (50.0, "sell"), (200.0, "buy"), (50.0, "sell"),
            (200.0, "buy"), (50.0, "sell"), (200.0, "buy"), (50.0, "sell"),
        ]
        for vol, side in labels:
            g.update(vol, side, _ts())
        assert not g.is_blocked()


class TestW371LowEntropyTrigger:
    """Guard MUST block when entropy is too low (directional regime)."""

    def test_all_large_buy_triggers_low_entropy(self):
        g = _make_w371(window_size=8, low_entropy_threshold=0.8)
        for _ in range(8):
            g.update(200.0, "buy", _ts())
        # All labels are +2 => H = 0 < 0.8
        assert g.is_blocked()
        assert g.last_reason == "LOW_FLOW_ENTROPY"

    def test_all_large_sell_triggers_low_entropy(self):
        g = _make_w371(window_size=8, low_entropy_threshold=0.8)
        for _ in range(8):
            g.update(200.0, "sell", _ts())
        assert g.is_blocked()
        assert g.last_reason == "LOW_FLOW_ENTROPY"


class TestW371HighEntropyTrigger:
    """Guard MUST block when entropy is too high (noise / spoof)."""

    def test_perfectly_uniform_all_bins_triggers_high_entropy(self):
        # 4 bins equally => H = log2(4) = 2.0 > 1.95
        g = _make_w371(
            window_size=8,
            low_entropy_threshold=0.5,
            high_entropy_threshold=1.95,
        )
        labels = [
            (200.0, "buy"),   # +2
            (50.0,  "buy"),   # +1
            (50.0,  "sell"),  # -1
            (200.0, "sell"),  # -2
            (200.0, "buy"),   # +2
            (50.0,  "buy"),   # +1
            (50.0,  "sell"),  # -1
            (200.0, "sell"),  # -2
        ]
        for vol, side in labels:
            g.update(vol, side, _ts())
        assert g.is_blocked()
        assert g.last_reason == "HIGH_FLOW_ENTROPY"


class TestW371InvalidInput:
    """Any invalid input must cause INPUT_VALIDATION_ERROR block (fail-closed)."""

    def test_bool_volume_blocks(self):
        g = _make_w371()
        g.update(True, "buy", _ts())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_invalid_side_blocks(self):
        g = _make_w371()
        g.update(50.0, "long", _ts())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_none_timestamp_blocks(self):
        g = _make_w371()
        g.update(50.0, "buy", None)
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_negative_volume_blocks(self):
        g = _make_w371()
        g.update(-50.0, "buy", _ts())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_nan_volume_blocks(self):
        g = _make_w371()
        g.update(float("nan"), "sell", _ts())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_bool_timestamp_blocks(self):
        g = _make_w371()
        g.update(50.0, "sell", True)
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_int_side_blocks(self):
        g = _make_w371()
        g.update(50.0, 1, _ts())
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"


class TestW371Reset:
    """reset() must clear all state and cooldown."""

    def test_reset_clears_low_entropy_block(self):
        g = _make_w371(window_size=8)
        for _ in range(8):
            g.update(200.0, "buy", _ts())
        assert g.is_blocked()
        g.reset()
        assert not g.is_blocked()
        assert g.last_reason is None

    def test_reset_allows_reaccumulation(self):
        g = _make_w371(window_size=8)
        for _ in range(8):
            g.update(200.0, "buy", _ts())
        g.reset()
        # 3 ticks after reset -- should not block
        for _ in range(3):
            g.update(50.0, "buy", _ts())
        assert not g.is_blocked()


class TestW371IsEntryBlocked:
    """is_entry_blocked() must ingest event and reflect block state."""

    def test_is_entry_blocked_returns_bool(self):
        g = _make_w371()
        result = g.is_entry_blocked(50.0, "buy", _ts())
        assert isinstance(result, bool)

    def test_is_entry_blocked_invalid_returns_true(self):
        g = _make_w371()
        result = g.is_entry_blocked(True, "buy", _ts())
        assert result is True


class TestW371CooldownExpiry:
    """After cooldown_seconds, guard must unblock automatically."""

    def test_cooldown_expires(self):
        g = _make_w371(window_size=8, cooldown_seconds=0.05)
        for _ in range(8):
            g.update(200.0, "buy", _ts())
        assert g.is_blocked()
        time.sleep(0.12)
        assert not g.is_blocked(), "Cooldown should have expired"


class TestW370CooldownExpiry:
    """After cooldown_seconds, Wave 370 guard must unblock automatically."""

    def test_cooldown_expires(self):
        g = _make_w370(window_size=5, lookback=2, compression_threshold_bps=0.5, cooldown_seconds=0.05)
        ask_prices = [1.0020, 1.0018, 1.0015, 1.0012, 1.0009, 1.0006, 1.0004, 1.0003, 1.0002]
        for ask in ask_prices:
            g.update(1.0000, ask, _ts())
        assert g.is_blocked()
        time.sleep(0.12)
        assert not g.is_blocked(), "Cooldown should have expired"
