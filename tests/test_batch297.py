"""
tests/test_batch297.py
Pytest suite for Batch 297:
  - Wave 352: LOB Bid-Ask Spread Skewness Guard
  - Wave 353: Trade Flow Signed Order Flow Imbalance Reversal Guard

At least 12 tests. No external dependencies beyond the two wave modules.
"""

import sys
import os
import time
import threading

# Ensure project root is importable when running from tests/ directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wave352_lob_bid_ask_spread_skewness_guard import (  # noqa: E402
    Wave352LobBidAskSpreadSkewnessGuard as W352,
)
from wave353_trade_flow_signed_order_flow_imbalance_reversal_guard import (  # noqa: E402
    Wave353TradeFlowSignedOrderFlowImbalanceReversalGuard as W353,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _feed_uniform_spreads(guard: W352, n: int, bid: float = 1.0, ask: float = 1.01) -> None:
    """Feed n identical ticks so the window fills with near-zero skewness."""
    for _ in range(n):
        guard.update(bid, ask, timestamp=time.monotonic())


def _trigger_w352_skew(guard: W352) -> None:
    """
    Feed a window of spreads that are heavily right-skewed:
    one very wide spread on top of many narrow ones produces
    Pearson skewness >= threshold when the outlier is large enough.
    """
    # 19 tight spreads (1 bp) followed by 1 massive spread (1000 bps)
    for _ in range(19):
        guard.update(100.0, 100.01, timestamp=time.monotonic())
    guard.update(100.0, 200.0, timestamp=time.monotonic())  # huge spread


def _trigger_w353_storm(guard: W353, threshold: float = 50.0) -> None:
    """
    Trigger OFI_REVERSAL_STORM.
    Pattern: alternate big buy / big sell bursts so sign flips repeatedly.
    Each burst covers short_window=5 ticks; we do enough to hit max_reversals=3.
    """
    # Burst 1: strong buy OFI
    for _ in range(5):
        guard.update(20.0, "buy", timestamp=time.monotonic())
    # Burst 2: strong sell OFI  -> reversal 1
    for _ in range(5):
        guard.update(20.0, "sell", timestamp=time.monotonic())
    # Burst 3: strong buy OFI  -> reversal 2
    for _ in range(5):
        guard.update(20.0, "buy", timestamp=time.monotonic())
    # Burst 4: strong sell OFI  -> reversal 3  => BLOCK
    for _ in range(5):
        guard.update(20.0, "sell", timestamp=time.monotonic())


# ===========================================================================
# Wave 352 Tests
# ===========================================================================

class TestWave352NoblockBeforeWindowFills:
    """Guard must NOT block while the rolling window is still accumulating."""

    def test_no_block_before_window_fills(self):
        g = W352(window_size=20, skewness_threshold=1.5, cooldown_seconds=45.0)
        for i in range(19):  # one tick short of window_size
            g.update(100.0, 100.01, timestamp=time.monotonic())
        assert not g.is_blocked(), "Should not block before window is full"

    def test_last_reason_empty_before_block(self):
        g = W352()
        _feed_uniform_spreads(g, 10)
        assert g.last_reason == ""


class TestWave352HappyPath:
    """Low-skewness uniform spreads must not trigger a block."""

    def test_uniform_spreads_no_block(self):
        g = W352(window_size=20, skewness_threshold=1.5, cooldown_seconds=45.0)
        _feed_uniform_spreads(g, 30)
        assert not g.is_blocked()
        assert g.last_reason == ""


class TestWave352TriggerBlock:
    """Highly skewed spread distribution must trigger SPREAD_DISTRIBUTION_SKEWED."""

    def test_skewed_spreads_trigger_block(self):
        g = W352(window_size=20, skewness_threshold=1.5, cooldown_seconds=45.0)
        _trigger_w352_skew(g)
        assert g.is_blocked()
        assert g.last_reason == "SPREAD_DISTRIBUTION_SKEWED"

    def test_blocked_until_monotonically_in_future(self):
        g = W352(window_size=20, skewness_threshold=1.5, cooldown_seconds=45.0)
        before = time.monotonic()
        _trigger_w352_skew(g)
        assert g._blocked_until > before + 44.0  # cooldown ~45 s


class TestWave352InvalidInputs:
    """Any invalid input must fail-closed with INPUT_VALIDATION_ERROR."""

    def test_non_numeric_bid_blocks(self):
        g = W352()
        g.update("bad", 1.01)
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_bool_ask_blocks(self):
        g = W352()
        g.update(1.0, True)
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_ask_less_than_bid_blocks(self):
        g = W352()
        g.update(1.05, 1.00)
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_zero_bid_blocks(self):
        g = W352()
        g.update(0.0, 1.0)
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"


class TestWave352Reset:
    """reset() must clear spreads, block state and last_reason."""

    def test_reset_clears_block(self):
        g = W352(window_size=20, skewness_threshold=1.5, cooldown_seconds=45.0)
        _trigger_w352_skew(g)
        assert g.is_blocked()
        g.reset()
        assert not g.is_blocked()
        assert g.last_reason == ""

    def test_reset_clears_window(self):
        g = W352(window_size=20)
        _feed_uniform_spreads(g, 19)
        g.reset()
        # After reset window is empty so next 19 ticks should not block
        _feed_uniform_spreads(g, 19)
        assert not g.is_blocked()


class TestWave352IsEntryBlocked:
    """is_entry_blocked calls update then delegates to is_blocked."""

    def test_is_entry_blocked_delegates(self):
        g = W352(window_size=20, skewness_threshold=1.5, cooldown_seconds=45.0)
        # Prefill 19 ticks with normal spreads
        _feed_uniform_spreads(g, 19, bid=100.0, ask=100.01)
        # 20th tick via is_entry_blocked with a huge spread
        result = g.is_entry_blocked(100.0, 200.0)
        assert result is True
        assert g.last_reason == "SPREAD_DISTRIBUTION_SKEWED"


# ===========================================================================
# Wave 353 Tests
# ===========================================================================

class TestWave353NoblockBeforeWindowFills:
    """Guard must NOT block during warm-up phase."""

    def test_no_block_before_short_window_fills(self):
        g = W353(short_window=5, long_window=20, ofi_threshold=50.0,
                 max_reversals=3, cooldown_seconds=45.0)
        for _ in range(4):
            g.update(10.0, "buy", timestamp=time.monotonic())
        assert not g.is_blocked()

    def test_last_reason_empty_at_start(self):
        g = W353()
        assert g.last_reason == ""


class TestWave353HappyPath:
    """Consistent one-sided flow must not trigger a block."""

    def test_consistent_buys_no_block(self):
        g = W353(short_window=5, long_window=20, ofi_threshold=50.0,
                 max_reversals=3, cooldown_seconds=45.0)
        for _ in range(20):
            g.update(10.0, "buy", timestamp=time.monotonic())
        assert not g.is_blocked()
        assert g.last_reason == ""


class TestWave353TriggerBlock:
    """Alternating large bursts must trigger OFI_REVERSAL_STORM."""

    def test_reversal_storm_blocks(self):
        g = W353(short_window=5, long_window=20, ofi_threshold=50.0,
                 max_reversals=3, cooldown_seconds=45.0)
        _trigger_w353_storm(g)
        assert g.is_blocked()
        assert g.last_reason == "OFI_REVERSAL_STORM"

    def test_blocked_until_in_future(self):
        g = W353(short_window=5, long_window=20, ofi_threshold=50.0,
                 max_reversals=3, cooldown_seconds=45.0)
        before = time.monotonic()
        _trigger_w353_storm(g)
        assert g._blocked_until > before + 44.0


class TestWave353InvalidInputs:
    """Bad inputs must fail-closed with INPUT_VALIDATION_ERROR."""

    def test_non_numeric_volume_blocks(self):
        g = W353()
        g.update("abc", "buy")
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_bool_volume_blocks(self):
        g = W353()
        g.update(True, "buy")
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_invalid_side_blocks(self):
        g = W353()
        g.update(10.0, "long")
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_zero_volume_blocks(self):
        g = W353()
        g.update(0.0, "sell")
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"

    def test_negative_volume_blocks(self):
        g = W353()
        g.update(-5.0, "buy")
        assert g.is_blocked()
        assert g.last_reason == "INPUT_VALIDATION_ERROR"


class TestWave353Reset:
    """reset() must clear all state including block and reversal history."""

    def test_reset_clears_block(self):
        g = W353(short_window=5, long_window=20, ofi_threshold=50.0,
                 max_reversals=3, cooldown_seconds=45.0)
        _trigger_w353_storm(g)
        assert g.is_blocked()
        g.reset()
        assert not g.is_blocked()
        assert g.last_reason == ""

    def test_reset_clears_reversal_history(self):
        g = W353(short_window=5, long_window=20, ofi_threshold=50.0,
                 max_reversals=3, cooldown_seconds=45.0)
        _trigger_w353_storm(g)
        g.reset()
        # After reset, consistent buys should not block
        for _ in range(20):
            g.update(10.0, "buy", timestamp=time.monotonic())
        assert not g.is_blocked()


class TestWave353IsEntryBlocked:
    """is_entry_blocked must delegate to is_blocked."""

    def test_is_entry_blocked_when_blocked(self):
        g = W353(short_window=5, long_window=20, ofi_threshold=50.0,
                 max_reversals=3, cooldown_seconds=45.0)
        _trigger_w353_storm(g)
        assert g.is_entry_blocked(1.0, 1.01) is True

    def test_is_entry_blocked_when_clear(self):
        g = W353()
        assert g.is_entry_blocked(1.0, 1.01) is False


class TestWave353ThreadSafety:
    """Concurrent updates must not corrupt internal state."""

    def test_concurrent_updates_do_not_raise(self):
        g = W353(short_window=5, long_window=20, ofi_threshold=50.0,
                 max_reversals=3, cooldown_seconds=45.0)
        errors = []

        def worker(side: str):
            try:
                for _ in range(50):
                    g.update(10.0, side, timestamp=time.monotonic())
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=("buy",)),
            threading.Thread(target=worker, args=("sell",)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread safety errors: {errors}"
        # last_reason must be a string after concurrent run
        assert isinstance(g.last_reason, str)
