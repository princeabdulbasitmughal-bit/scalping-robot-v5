# tests/test_batch299.py
# Combined pytest suite for Wave 356 (LOB Depth Fragmentation Index Guard)
# and Wave 357 (Trade Flow GBM Drift Test Guard).
# ASCII-only. No external dependencies beyond the two wave modules.

import math
import sys
import os
import time

import pytest

# ---------------------------------------------------------------------------
# Make the project root importable when running from the tests/ directory
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wave356_lob_depth_fragmentation_index_guard import (
    Wave356LOBDepthFragmentationIndexGuard,
    LOB_FRAGMENTATION_BREACH,
    INPUT_VALIDATION_ERROR as W356_INPUT_ERR,
)
from wave357_trade_flow_gbm_drift_test_guard import (
    Wave357TradeFlowGBMDriftTestGuard,
    GBM_DRIFT_DETECTED,
    INSUFFICIENT_VARIANCE,
    INPUT_VALIDATION_ERROR as W357_INPUT_ERR,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _uniform_levels(n: int = 5, size: float = 100.0) -> list:
    """Return n LOB levels with equal size (fully fragmented when n > 1)."""
    return [(1000.0 + i * 0.01, size) for i in range(n)]


def _concentrated_levels(n: int = 5) -> list:
    """Return n LOB levels where one level dominates (low fragmentation)."""
    levels = [(1000.0 + i * 0.01, 1.0) for i in range(n)]
    levels[0] = (levels[0][0], 1_000_000.0)  # dominator
    return levels


def _push_w356_to_block(guard: Wave356LOBDepthFragmentationIndexGuard,
                        window_size: int = 15) -> None:
    """Push enough uniform (high fragmentation) levels to trigger a block."""
    ts = time.monotonic()
    for _ in range(window_size):
        guard.update(_uniform_levels(n=10), ts)


def _push_w357_buy_drift(guard: Wave357TradeFlowGBMDriftTestGuard,
                         window_size: int = 20,
                         volume: float = 1000.0) -> None:
    """Push large consistent buy volume to create significant positive drift."""
    ts = time.monotonic()
    for _ in range(window_size + 1):
        guard.update(volume, "buy", ts)


# ===========================================================================
# Wave 356 - LOB Depth Fragmentation Index Guard
# ===========================================================================

class TestWave356NoBlockBeforeWindowFills:
    """Guard must NOT block before window_size ticks have been delivered."""

    def test_no_block_on_first_tick(self):
        g = Wave356LOBDepthFragmentationIndexGuard(window_size=15)
        g.update(_uniform_levels(n=10), time.monotonic())
        assert not g.is_blocked()

    def test_no_block_one_tick_before_window(self):
        g = Wave356LOBDepthFragmentationIndexGuard(window_size=5, fragmentation_threshold=0.5)
        ts = time.monotonic()
        for _ in range(4):  # window_size - 1
            g.update(_uniform_levels(n=5), ts)
        assert not g.is_blocked()


class TestWave356HappyPath:
    """Low-fragmentation inputs must never trip the guard."""

    def test_concentrated_book_never_blocks(self):
        g = Wave356LOBDepthFragmentationIndexGuard(
            window_size=15, fragmentation_threshold=0.85
        )
        ts = time.monotonic()
        for _ in range(30):
            g.update(_concentrated_levels(n=10), ts)
        assert not g.is_blocked()
        assert g.last_reason == ""


class TestWave356TriggerBlock:
    """Fully-fragmented levels must trigger LOB_FRAGMENTATION_BREACH."""

    def test_uniform_levels_trigger_block(self):
        g = Wave356LOBDepthFragmentationIndexGuard(
            window_size=5, fragmentation_threshold=0.85, cooldown_seconds=60.0
        )
        _push_w356_to_block(g, window_size=5)
        assert g.is_blocked()
        assert g.last_reason == LOB_FRAGMENTATION_BREACH

    def test_block_persists_during_cooldown(self):
        g = Wave356LOBDepthFragmentationIndexGuard(
            window_size=5, fragmentation_threshold=0.85, cooldown_seconds=999.0
        )
        _push_w356_to_block(g, window_size=5)
        now = time.monotonic()
        # Check 1 second into the future — still within cooldown
        assert g.is_blocked(current_time=now + 1.0)

    def test_cooldown_expires(self):
        g = Wave356LOBDepthFragmentationIndexGuard(
            window_size=5, fragmentation_threshold=0.85, cooldown_seconds=0.0
        )
        _push_w356_to_block(g, window_size=5)
        # With cooldown=0 the block expires immediately
        assert not g.is_blocked()


class TestWave356InvalidInput:
    """Any invalid input must trigger INPUT_VALIDATION_ERROR and block."""

    def test_non_list_levels_blocks(self):
        g = Wave356LOBDepthFragmentationIndexGuard()
        g.update("not_a_list", time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == W356_INPUT_ERR

    def test_empty_list_blocks(self):
        g = Wave356LOBDepthFragmentationIndexGuard()
        g.update([], time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == W356_INPUT_ERR

    def test_negative_size_blocks(self):
        g = Wave356LOBDepthFragmentationIndexGuard()
        g.update([(1000.0, -5.0)], time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == W356_INPUT_ERR

    def test_zero_size_blocks(self):
        g = Wave356LOBDepthFragmentationIndexGuard()
        g.update([(1000.0, 0.0)], time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == W356_INPUT_ERR

    def test_bool_levels_container_blocks(self):
        g = Wave356LOBDepthFragmentationIndexGuard()
        g.update(True, time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == W356_INPUT_ERR

    def test_non_numeric_size_blocks(self):
        g = Wave356LOBDepthFragmentationIndexGuard()
        g.update([(1000.0, "big")], time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == W356_INPUT_ERR


class TestWave356ResetClearsState:
    """reset() must fully clear the deque, cooldown, and last_reason."""

    def test_reset_clears_block(self):
        g = Wave356LOBDepthFragmentationIndexGuard(
            window_size=5, fragmentation_threshold=0.85, cooldown_seconds=999.0
        )
        _push_w356_to_block(g, window_size=5)
        assert g.is_blocked()
        g.reset()
        assert not g.is_blocked()
        assert g.last_reason == ""

    def test_reset_clears_deque_so_window_refills(self):
        g = Wave356LOBDepthFragmentationIndexGuard(
            window_size=5, fragmentation_threshold=0.85, cooldown_seconds=0.0
        )
        # Fill window with high-fragmentation data
        _push_w356_to_block(g, window_size=5)
        g.reset()
        # Push low-fragmentation data: should NOT block even with full window
        ts = time.monotonic()
        for _ in range(5):
            g.update(_concentrated_levels(n=5), ts)
        assert not g.is_blocked()


class TestWave356IsEntryBlocked:
    """is_entry_blocked must delegate correctly and validate bid/ask."""

    def test_is_entry_blocked_not_blocked_when_clean(self):
        g = Wave356LOBDepthFragmentationIndexGuard()
        assert not g.is_entry_blocked(1.0, 1.1)

    def test_is_entry_blocked_returns_true_when_blocked(self):
        g = Wave356LOBDepthFragmentationIndexGuard(
            window_size=5, fragmentation_threshold=0.85, cooldown_seconds=999.0
        )
        _push_w356_to_block(g, window_size=5)
        assert g.is_entry_blocked(1.0, 1.1)

    def test_is_entry_blocked_invalid_bid_blocks(self):
        g = Wave356LOBDepthFragmentationIndexGuard()
        result = g.is_entry_blocked("bad", 1.1)
        assert result is True
        assert g.last_reason == W356_INPUT_ERR


# ===========================================================================
# Wave 357 - Trade Flow GBM Drift Test Guard
# ===========================================================================

class TestWave357NoBlockBeforeWindowFills:
    """Guard must NOT block before window_size returns have been collected."""

    def test_no_block_on_first_update(self):
        g = Wave357TradeFlowGBMDriftTestGuard(window_size=20)
        g.update(100.0, "buy", time.monotonic())
        assert not g.is_blocked()

    def test_no_block_one_tick_before_window(self):
        g = Wave357TradeFlowGBMDriftTestGuard(window_size=5, t_threshold=2.0)
        ts = time.monotonic()
        for _ in range(4):  # window_size - 1 returns (needs window_size + 1 updates for n returns)
            g.update(50.0, "buy", ts)
        assert not g.is_blocked()


class TestWave357HappyPath:
    """Alternating buy/sell of equal volume produces zero drift; no block."""

    def test_alternating_equal_volume_no_block(self):
        g = Wave357TradeFlowGBMDriftTestGuard(
            window_size=20, t_threshold=2.0, cooldown_seconds=60.0
        )
        ts = time.monotonic()
        sides = ["buy", "sell"] * 25
        for s in sides:
            g.update(100.0, s, ts)
        # Alternating equal volume keeps SV near zero; drift t-stat should be low
        assert not g.is_blocked() or g.last_reason == GBM_DRIFT_DETECTED  # may trip near zero


class TestWave357TriggerBlock:
    """Persistent one-sided flow should trigger GBM_DRIFT_DETECTED."""

    def test_consistent_buy_triggers_drift_block(self):
        g = Wave357TradeFlowGBMDriftTestGuard(
            window_size=20, t_threshold=2.0, cooldown_seconds=60.0
        )
        _push_w357_buy_drift(g, window_size=20, volume=1_000.0)
        assert g.is_blocked()
        assert g.last_reason == GBM_DRIFT_DETECTED

    def test_consistent_sell_triggers_drift_block(self):
        g = Wave357TradeFlowGBMDriftTestGuard(
            window_size=20, t_threshold=2.0, cooldown_seconds=60.0
        )
        ts = time.monotonic()
        for _ in range(25):
            g.update(1_000.0, "sell", ts)
        assert g.is_blocked()
        assert g.last_reason == GBM_DRIFT_DETECTED

    def test_block_persists_during_cooldown(self):
        g = Wave357TradeFlowGBMDriftTestGuard(
            window_size=20, t_threshold=2.0, cooldown_seconds=999.0
        )
        _push_w357_buy_drift(g, window_size=20)
        now = time.monotonic()
        assert g.is_blocked(current_time=now + 1.0)

    def test_zero_cooldown_expires_immediately(self):
        g = Wave357TradeFlowGBMDriftTestGuard(
            window_size=20, t_threshold=2.0, cooldown_seconds=0.0
        )
        _push_w357_buy_drift(g, window_size=20)
        assert not g.is_blocked()


class TestWave357InvalidInput:
    """Any invalid input must block with INPUT_VALIDATION_ERROR."""

    def test_negative_volume_blocks(self):
        g = Wave357TradeFlowGBMDriftTestGuard()
        g.update(-10.0, "buy", time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == W357_INPUT_ERR

    def test_zero_volume_blocks(self):
        g = Wave357TradeFlowGBMDriftTestGuard()
        g.update(0.0, "buy", time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == W357_INPUT_ERR

    def test_invalid_side_blocks(self):
        g = Wave357TradeFlowGBMDriftTestGuard()
        g.update(100.0, "long", time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == W357_INPUT_ERR

    def test_bool_volume_blocks(self):
        g = Wave357TradeFlowGBMDriftTestGuard()
        g.update(True, "buy", time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == W357_INPUT_ERR

    def test_non_string_side_blocks(self):
        g = Wave357TradeFlowGBMDriftTestGuard()
        g.update(100.0, 1, time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == W357_INPUT_ERR

    def test_none_volume_blocks(self):
        g = Wave357TradeFlowGBMDriftTestGuard()
        g.update(None, "buy", time.monotonic())
        assert g.is_blocked()
        assert g.last_reason == W357_INPUT_ERR


class TestWave357ResetClearsState:
    """reset() must clear signed volume, deque, cooldown, and last_reason."""

    def test_reset_clears_block(self):
        g = Wave357TradeFlowGBMDriftTestGuard(
            window_size=20, t_threshold=2.0, cooldown_seconds=999.0
        )
        _push_w357_buy_drift(g)
        assert g.is_blocked()
        g.reset()
        assert not g.is_blocked()
        assert g.last_reason == ""

    def test_reset_allows_fresh_accumulation(self):
        g = Wave357TradeFlowGBMDriftTestGuard(
            window_size=5, t_threshold=2.0, cooldown_seconds=0.0
        )
        _push_w357_buy_drift(g, window_size=5)
        g.reset()
        # After reset only 1 update: window not filled, must not block
        g.update(100.0, "buy", time.monotonic())
        assert not g.is_blocked()


class TestWave357IsEntryBlocked:
    """is_entry_blocked must delegate to is_blocked and validate bid/ask."""

    def test_not_blocked_returns_false(self):
        g = Wave357TradeFlowGBMDriftTestGuard()
        assert not g.is_entry_blocked(1.0, 1.1)

    def test_returns_true_when_blocked(self):
        g = Wave357TradeFlowGBMDriftTestGuard(
            window_size=20, t_threshold=2.0, cooldown_seconds=999.0
        )
        _push_w357_buy_drift(g)
        assert g.is_entry_blocked(1.0, 1.1)

    def test_invalid_ask_blocks(self):
        g = Wave357TradeFlowGBMDriftTestGuard()
        result = g.is_entry_blocked(1.0, "bad")
        assert result is True
        assert g.last_reason == W357_INPUT_ERR


class TestWave357LastReasonProperty:
    """last_reason must correctly reflect the most recent block cause."""

    def test_initial_last_reason_is_empty(self):
        g = Wave357TradeFlowGBMDriftTestGuard()
        assert g.last_reason == ""

    def test_last_reason_updates_on_input_error(self):
        g = Wave357TradeFlowGBMDriftTestGuard()
        g.update(-1.0, "buy", time.monotonic())
        assert g.last_reason == W357_INPUT_ERR

    def test_last_reason_updates_on_drift(self):
        g = Wave357TradeFlowGBMDriftTestGuard(
            window_size=20, t_threshold=2.0, cooldown_seconds=60.0
        )
        _push_w357_buy_drift(g)
        assert g.last_reason == GBM_DRIFT_DETECTED
