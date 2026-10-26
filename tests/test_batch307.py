"""
Batch 307 -- Tests for Wave 372 and Wave 373
=============================================
Wave 372: LOB Bid-Side Queue Exhaustion Guard
Wave 373: Trade Flow Price Reversal Frequency Guard

Target: 14+ tests, 0 failures
"""

import time
import pytest

from wave372_lob_bid_side_queue_exhaustion_guard import (
    Wave372LOBBidSideQueueExhaustionGuard,
)
from wave373_trade_flow_price_reversal_frequency_guard import (
    Wave373TradeFlowPriceReversalFrequencyGuard,
)


class TestWave372BidQueueExhaustion:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave372LOBBidSideQueueExhaustionGuard(window_size=1)
        with pytest.raises(ValueError):
            Wave372LOBBidSideQueueExhaustionGuard(exhaustion_threshold=0.0)

    def test_no_block_before_window_fills(self):
        guard = Wave372LOBBidSideQueueExhaustionGuard(window_size=10, exhaustion_threshold=0.25)
        t0 = time.monotonic()
        depth = 1000.0
        for i in range(8):
            guard.update(bid_depth=depth, ask_depth=1000.0, timestamp=t0 + i)
            depth *= 0.7  # heavy drop, but window not full
        assert not guard.is_blocked()

    def test_steady_depth_no_block(self):
        guard = Wave372LOBBidSideQueueExhaustionGuard(window_size=10, exhaustion_threshold=0.20)
        t0 = time.monotonic()
        for i in range(20):
            guard.update(bid_depth=1000.0, ask_depth=1000.0, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_rapid_exhaustion_triggers_block(self):
        guard = Wave372LOBBidSideQueueExhaustionGuard(window_size=10, exhaustion_threshold=0.20)
        t0 = time.monotonic()
        depth = 1000.0
        for i in range(15):
            guard.update(bid_depth=depth, ask_depth=1000.0, timestamp=t0 + i)
            depth *= 0.70  # ~30% exhaustion per step
        assert guard.is_blocked()
        assert guard.last_reason == "BID_QUEUE_EXHAUSTION"

    def test_invalid_input_fails_closed(self):
        guard = Wave372LOBBidSideQueueExhaustionGuard()
        guard.update(True, 100.0, 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(-10.0, 100.0, 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_delegation(self):
        guard = Wave372LOBBidSideQueueExhaustionGuard()
        guard.update(0.0, 100.0, 1.0)
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 1.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""


class TestWave373PriceReversalFrequency:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave373TradeFlowPriceReversalFrequencyGuard(window_size=2)
        with pytest.raises(ValueError):
            Wave373TradeFlowPriceReversalFrequencyGuard(reversal_rate_threshold=1.5)

    def test_no_block_before_window_fills(self):
        guard = Wave373TradeFlowPriceReversalFrequencyGuard(window_size=10, reversal_rate_threshold=0.60)
        t0 = time.monotonic()
        # 5 alternations (less than window 10)
        prices = [1.1000, 1.1005, 1.1000, 1.1005, 1.1000, 1.1005]
        for i, p in enumerate(prices):
            guard.update(price=p, volume=10.0, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_trending_prices_no_block(self):
        guard = Wave373TradeFlowPriceReversalFrequencyGuard(window_size=10, reversal_rate_threshold=0.60)
        t0 = time.monotonic()
        for i in range(25):
            guard.update(price=1.1000 + i * 0.0001, volume=10.0, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_whipsaw_reversals_trigger_block(self):
        guard = Wave373TradeFlowPriceReversalFrequencyGuard(window_size=10, reversal_rate_threshold=0.60)
        t0 = time.monotonic()
        # Strictly alternating ticks: +1, -1, +1, -1...
        p = 1.1000
        for i in range(20):
            p = 1.1005 if i % 2 == 0 else 1.1000
            guard.update(price=p, volume=10.0, timestamp=t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "HIGH_REVERSAL_FREQUENCY"

    def test_invalid_inputs_fail_closed(self):
        guard = Wave373TradeFlowPriceReversalFrequencyGuard()
        guard.update(1.1000, True, 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(-1.0, 10.0, 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_delegation(self):
        guard = Wave373TradeFlowPriceReversalFrequencyGuard()
        guard.update(1.1000, 0.0, 1.0)
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 1.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""
