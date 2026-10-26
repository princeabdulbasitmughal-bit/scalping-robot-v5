"""
tests/test_batch303.py
Combined pytest suite for Batch 303 wave guards:
  - Wave 364: LOB Quote Update Entropy Guard
  - Wave 365: Trade Flow Price Impact Decay Guard

At least 12 tests total; all self-contained (no external dependencies).
Uses time.monotonic() for timestamps where needed.
"""

import math
import time
import threading

import pytest

import sys
import os

# Ensure project root is on path regardless of how pytest is invoked
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wave364_lob_quote_update_entropy_guard import (
    Wave364LOBQuoteUpdateEntropyGuard,
    REASON_LOW_ENTROPY,
    REASON_VALIDATION as W364_VALIDATION,
)
from wave365_trade_flow_price_impact_decay_guard import (
    Wave365TradeFlowPriceImpactDecayGuard,
    REASON_HIGH_IMPACT,
    REASON_VALIDATION as W365_VALIDATION,
)

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def make_w364(window_size=10, low_entropy_threshold=1.0, cooldown_seconds=1.0):
    return Wave364LOBQuoteUpdateEntropyGuard(
        window_size=window_size,
        low_entropy_threshold=low_entropy_threshold,
        cooldown_seconds=cooldown_seconds,
    )


def make_w365(window_size=5, impact_threshold=0.0001, cooldown_seconds=1.0):
    return Wave365TradeFlowPriceImpactDecayGuard(
        window_size=window_size,
        impact_threshold=impact_threshold,
        cooldown_seconds=cooldown_seconds,
    )


def _ts():
    """Return a fresh monotonic timestamp."""
    return time.monotonic()


# ===========================================================================
# Wave 364 -- LOB Quote Update Entropy Guard
# ===========================================================================

class TestWave364NoBlockBeforeWindowFills:
    """Guard must NOT block while the deque is still warming up."""

    def test_no_block_on_zero_events(self):
        g = make_w364(window_size=5)
        assert g.is_blocked() is False

    def test_no_block_before_window_full(self):
        """Feed window_size - 1 identical events; still not blocked."""
        g = make_w364(window_size=8, low_entropy_threshold=1.0)
        for _ in range(7):  # one shy of window
            g.update("INSERT_BID", _ts())
        assert g.is_blocked() is False


class TestWave364HappyPathHighEntropy:
    """Balanced distribution -> H near 2.0 bits -> no block."""

    def test_balanced_window_no_block(self):
        g = make_w364(window_size=8, low_entropy_threshold=1.0)
        events = ["INSERT_BID", "CANCEL_BID", "INSERT_ASK", "CANCEL_ASK"] * 2
        for ev in events:
            g.update(ev, _ts())
        assert g.is_blocked() is False
        assert g.last_reason == ""

    def test_entropy_max_four_equal_buckets(self):
        """Verify internal entropy of perfectly balanced window == 2.0 bits."""
        g = make_w364(window_size=4, low_entropy_threshold=1.0)
        for ev in ["INSERT_BID", "CANCEL_BID", "INSERT_ASK", "CANCEL_ASK"]:
            g.update(ev, _ts())
        # H = 2.0 bits for 4 equally probable events; 2.0 > 1.0 -> no block
        assert g.is_blocked() is False


class TestWave364TriggerBlock:
    """All-same event type -> H = 0 bits -> block."""

    def test_all_same_event_triggers_block(self):
        g = make_w364(window_size=5, low_entropy_threshold=1.0, cooldown_seconds=30.0)
        for _ in range(5):
            g.update("INSERT_BID", _ts())
        assert g.is_blocked() is True
        assert g.last_reason == REASON_LOW_ENTROPY

    def test_two_bucket_low_entropy_triggers_block(self):
        """9 INSERT_BID + 1 CANCEL_BID in window of 10 -> H ~ 0.47 bits -> block."""
        g = make_w364(window_size=10, low_entropy_threshold=1.0, cooldown_seconds=30.0)
        for _ in range(9):
            g.update("INSERT_BID", _ts())
        g.update("CANCEL_BID", _ts())
        assert g.is_blocked() is True
        assert g.last_reason == REASON_LOW_ENTROPY

    def test_is_entry_blocked_delegates_to_is_blocked(self):
        g = make_w364(window_size=5, low_entropy_threshold=1.0, cooldown_seconds=30.0)
        for _ in range(5):
            g.update("INSERT_BID", _ts())
        assert g.is_entry_blocked(1.0, 1.01, _ts()) is True


class TestWave364InvalidInput:
    """Any invalid input must immediately block (fail-closed)."""

    def test_invalid_event_type_string_blocks(self):
        g = make_w364()
        g.update("UNKNOWN_EVENT", _ts())
        assert g.is_blocked() is True
        assert g.last_reason == W364_VALIDATION

    def test_non_string_event_type_blocks(self):
        g = make_w364()
        g.update(42, _ts())
        assert g.is_blocked() is True
        assert g.last_reason == W364_VALIDATION

    def test_bool_event_type_blocks(self):
        """bool is subclass of int, but NOT a str -- must block."""
        g = make_w364()
        g.update(True, _ts())
        assert g.is_blocked() is True
        assert g.last_reason == W364_VALIDATION

    def test_none_timestamp_blocks(self):
        g = make_w364()
        g.update("INSERT_BID", None)
        assert g.is_blocked() is True
        assert g.last_reason == W364_VALIDATION

    def test_bool_timestamp_blocks(self):
        g = make_w364()
        g.update("INSERT_BID", True)
        assert g.is_blocked() is True
        assert g.last_reason == W364_VALIDATION


class TestWave364Reset:
    """reset() must clear all state and unblock."""

    def test_reset_clears_block(self):
        g = make_w364(window_size=5, low_entropy_threshold=1.0, cooldown_seconds=30.0)
        for _ in range(5):
            g.update("INSERT_BID", _ts())
        assert g.is_blocked() is True
        g.reset()
        assert g.is_blocked() is False

    def test_reset_clears_last_reason(self):
        g = make_w364(window_size=5, low_entropy_threshold=1.0, cooldown_seconds=30.0)
        for _ in range(5):
            g.update("INSERT_BID", _ts())
        assert g.last_reason == REASON_LOW_ENTROPY
        g.reset()
        assert g.last_reason == ""

    def test_reset_allows_new_window_to_accumulate(self):
        """After reset, window must warm up again before evaluating."""
        g = make_w364(window_size=5, low_entropy_threshold=1.0, cooldown_seconds=30.0)
        for _ in range(5):
            g.update("INSERT_BID", _ts())
        g.reset()
        # only 4 events after reset -- window not full, must not block
        for _ in range(4):
            g.update("INSERT_BID", _ts())
        assert g.is_blocked() is False


class TestWave364ThreadSafety:
    def test_concurrent_updates_do_not_raise(self):
        g = make_w364(window_size=20, cooldown_seconds=0.1)
        errors = []

        def worker():
            try:
                for ev in ["INSERT_BID", "CANCEL_BID", "INSERT_ASK", "CANCEL_ASK"] * 5:
                    g.update(ev, _ts())
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []


# ===========================================================================
# Wave 365 -- Trade Flow Price Impact Decay Guard
# ===========================================================================

class TestWave365NoBlockBeforeWindowFills:
    def test_no_block_on_zero_trades(self):
        g = make_w365(window_size=5)
        assert g.is_blocked() is False

    def test_no_block_before_window_full(self):
        g = make_w365(window_size=5, impact_threshold=0.0001)
        # Feed 4 high-impact trades (one shy of window=5) -- must not block
        for _ in range(4):
            g.update(1.0, "buy", 100.0, 101.0, _ts())  # impact = 1.0 >> threshold
        assert g.is_blocked() is False


class TestWave365HappyPathLowImpact:
    def test_zero_price_change_no_block(self):
        g = make_w365(window_size=5, impact_threshold=0.0001, cooldown_seconds=1.0)
        for _ in range(5):
            g.update(100.0, "buy", 1.0, 1.0, _ts())  # delta_mid = 0 -> impact = 0
        assert g.is_blocked() is False
        assert g.last_reason == ""

    def test_tiny_impact_no_block(self):
        g = make_w365(window_size=5, impact_threshold=0.0001, cooldown_seconds=1.0)
        for _ in range(5):
            # impact = 0.000001 / 1000 = 1e-9 << threshold
            g.update(1000.0, "buy", 1.0, 1.000001, _ts())
        assert g.is_blocked() is False


class TestWave365TriggerBlock:
    def test_high_positive_impact_triggers_block(self):
        """Large delta_mid with small volume -> high impact -> block."""
        g = make_w365(window_size=5, impact_threshold=0.0001, cooldown_seconds=30.0)
        for _ in range(5):
            # impact = 1.0 / 1.0 = 1.0 >> 0.0001
            g.update(1.0, "buy", 100.0, 101.0, _ts())
        assert g.is_blocked() is True
        assert g.last_reason == REASON_HIGH_IMPACT

    def test_sell_side_does_not_suppress_block_on_high_impact(self):
        """Sell gives negative signed_volume; impact = neg/neg = positive."""
        g = make_w365(window_size=5, impact_threshold=0.0001, cooldown_seconds=30.0)
        for _ in range(5):
            # signed_volume = -1.0, delta_mid = -1.0, impact = (-1)/(-1) = 1.0
            g.update(1.0, "sell", 101.0, 100.0, _ts())
        assert g.is_blocked() is True
        assert g.last_reason == REASON_HIGH_IMPACT

    def test_is_entry_blocked_delegates_when_triggered(self):
        g = make_w365(window_size=5, impact_threshold=0.0001, cooldown_seconds=30.0)
        for _ in range(5):
            g.update(1.0, "buy", 100.0, 101.0, _ts())
        assert g.is_entry_blocked(99.9, 100.1, _ts()) is True


class TestWave365InvalidInput:
    def test_invalid_side_blocks(self):
        g = make_w365()
        g.update(10.0, "long", 1.0, 1.0, _ts())
        assert g.is_blocked() is True
        assert g.last_reason == W365_VALIDATION

    def test_bool_side_blocks(self):
        g = make_w365()
        g.update(10.0, True, 1.0, 1.0, _ts())
        assert g.is_blocked() is True
        assert g.last_reason == W365_VALIDATION

    def test_non_numeric_volume_blocks(self):
        g = make_w365()
        g.update("lots", "buy", 1.0, 1.0, _ts())
        assert g.is_blocked() is True
        assert g.last_reason == W365_VALIDATION

    def test_bool_volume_blocks(self):
        """bool is subclass of int but must be rejected."""
        g = make_w365()
        g.update(True, "buy", 1.0, 1.0, _ts())
        assert g.is_blocked() is True
        assert g.last_reason == W365_VALIDATION

    def test_nan_prev_mid_blocks(self):
        g = make_w365()
        g.update(10.0, "buy", float("nan"), 1.0, _ts())
        assert g.is_blocked() is True
        assert g.last_reason == W365_VALIDATION

    def test_nan_curr_mid_blocks(self):
        g = make_w365()
        g.update(10.0, "buy", 1.0, float("nan"), _ts())
        assert g.is_blocked() is True
        assert g.last_reason == W365_VALIDATION

    def test_none_timestamp_blocks(self):
        g = make_w365()
        g.update(10.0, "buy", 1.0, 1.0, None)
        assert g.is_blocked() is True
        assert g.last_reason == W365_VALIDATION

    def test_bool_timestamp_blocks(self):
        g = make_w365()
        g.update(10.0, "buy", 1.0, 1.0, False)
        assert g.is_blocked() is True
        assert g.last_reason == W365_VALIDATION


class TestWave365Reset:
    def test_reset_clears_block(self):
        g = make_w365(window_size=5, impact_threshold=0.0001, cooldown_seconds=30.0)
        for _ in range(5):
            g.update(1.0, "buy", 100.0, 101.0, _ts())
        assert g.is_blocked() is True
        g.reset()
        assert g.is_blocked() is False

    def test_reset_clears_last_reason(self):
        g = make_w365(window_size=5, impact_threshold=0.0001, cooldown_seconds=30.0)
        for _ in range(5):
            g.update(1.0, "buy", 100.0, 101.0, _ts())
        g.reset()
        assert g.last_reason == ""

    def test_reset_requires_window_refill_before_blocking(self):
        g = make_w365(window_size=5, impact_threshold=0.0001, cooldown_seconds=30.0)
        for _ in range(5):
            g.update(1.0, "buy", 100.0, 101.0, _ts())
        g.reset()
        # Only 4 high-impact trades after reset -- window not full, no block
        for _ in range(4):
            g.update(1.0, "buy", 100.0, 101.0, _ts())
        assert g.is_blocked() is False


class TestWave365ThreadSafety:
    def test_concurrent_updates_do_not_raise(self):
        g = make_w365(window_size=10, cooldown_seconds=0.1)
        errors = []

        def worker():
            try:
                for _ in range(10):
                    g.update(10.0, "buy", 1.0, 1.0, _ts())
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []


# ===========================================================================
# Cross-guard: cooldown expiry test
# ===========================================================================

class TestCooldownExpiry:
    def test_w364_unblocks_after_cooldown(self):
        g = make_w364(window_size=5, low_entropy_threshold=1.0, cooldown_seconds=0.05)
        for _ in range(5):
            g.update("INSERT_BID", _ts())
        assert g.is_blocked() is True
        time.sleep(0.1)
        assert g.is_blocked() is False

    def test_w365_unblocks_after_cooldown(self):
        g = make_w365(window_size=5, impact_threshold=0.0001, cooldown_seconds=0.05)
        for _ in range(5):
            g.update(1.0, "buy", 100.0, 101.0, _ts())
        assert g.is_blocked() is True
        time.sleep(0.1)
        assert g.is_blocked() is False
