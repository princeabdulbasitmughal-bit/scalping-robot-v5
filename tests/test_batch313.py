"""
Batch 313 -- Tests for Wave 384 and Wave 385
=============================================
Wave 384: LOB Bid-Ask Bounce Frequency Guard
Wave 385: Trade Flow Zipf Law Deviation Guard

Target: 12+ tests, 0 failures
"""

import time
import pytest

from wave384_lob_bid_ask_bounce_frequency_guard import (
    Wave384LOBBidAskBounceFrequencyGuard,
)
from wave385_trade_flow_zipf_law_deviation_guard import (
    Wave385TradeFlowZipfLawDeviationGuard,
)


class TestWave384BidAskBounceFrequency:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave384LOBBidAskBounceFrequencyGuard(window_size=2)
        with pytest.raises(ValueError):
            Wave384LOBBidAskBounceFrequencyGuard(bounce_rate_threshold=1.5)

    def test_trending_prices_no_block(self):
        guard = Wave384LOBBidAskBounceFrequencyGuard(window_size=10, bounce_rate_threshold=0.50)
        t0 = time.monotonic()
        # Strictly rising prices -> no bounce (p_t != p_{t-2})
        for i in range(20):
            guard.update(bid=1.1000 + i * 0.0001, ask=1.1005 + i * 0.0001, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_no_block_before_window_fills(self):
        guard = Wave384LOBBidAskBounceFrequencyGuard(window_size=10, bounce_rate_threshold=0.50)
        t0 = time.monotonic()
        # 5 bounces (less than window 10)
        for i in range(5):
            b = 1.1000 if i % 2 == 0 else 1.1001
            guard.update(bid=b, ask=1.1005, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_flickering_bounces_trigger_block(self):
        guard = Wave384LOBBidAskBounceFrequencyGuard(window_size=10, bounce_rate_threshold=0.50)
        t0 = time.monotonic()
        # Alternating bid prices: 1.1000, 1.1001, 1.1000, 1.1001...
        for i in range(20):
            b = 1.1000 if i % 2 == 0 else 1.1001
            guard.update(bid=b, ask=1.1005, timestamp=t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "HIGH_BOUNCE_FREQUENCY"

    def test_invalid_input_validation(self):
        guard = Wave384LOBBidAskBounceFrequencyGuard()
        guard.update(1.1005, 1.1000, 1.0)  # crossed
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(True, 1.1005, 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_delegation(self):
        guard = Wave384LOBBidAskBounceFrequencyGuard()
        guard.update(0.0, 1.1005, 1.0)
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 1.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""


class TestWave385ZipfLawDeviation:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave385TradeFlowZipfLawDeviationGuard(window_size=5)
        with pytest.raises(ValueError):
            Wave385TradeFlowZipfLawDeviationGuard(min_distinct_bins=2)

    def test_natural_power_law_distribution_no_block(self):
        guard = Wave385TradeFlowZipfLawDeviationGuard(
            window_size=30, max_zipf_correlation=-0.50, min_distinct_bins=4
        )
        t0 = time.monotonic()
        # Generate power-law frequencies: bin 1 has 16 items, bin 2 has 8, bin 3 has 4, bin 4 has 2
        # (volumes: 1 (bin 0), 2 (bin 1), 4 (bin 2), 8 (bin 3))
        vols = [1.0] * 16 + [2.0] * 8 + [4.0] * 4 + [8.0] * 2
        for i, v in enumerate(vols):
            guard.update(volume=v, timestamp=t0 + i)
        # Power-law gives almost perfect -1.0 correlation, which is <= -0.50 -> no block!
        assert not guard.is_blocked()

    def test_no_block_before_window_fills(self):
        guard = Wave385TradeFlowZipfLawDeviationGuard(window_size=20)
        t0 = time.monotonic()
        for i in range(10):
            guard.update(volume=10.0 + i, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_flat_unnatural_distribution_triggers_block(self):
        guard = Wave385TradeFlowZipfLawDeviationGuard(
            window_size=30, max_zipf_correlation=-0.80, min_distinct_bins=3
        )
        t0 = time.monotonic()
        # Equal counts across 5 distinct bins: 6 items in each bin (flat frequency, non-Zipf)
        vols = [1.0] * 6 + [2.0] * 6 + [4.0] * 6 + [8.0] * 6 + [16.0] * 6
        for i, v in enumerate(vols):
            guard.update(volume=v, timestamp=t0 + i)
        # Flat distribution has zero correlation (or non-negative), which is > -0.80 -> blocks!
        assert guard.is_blocked()
        assert guard.last_reason == "ZIPF_DEVIATION_DETECTED"

    def test_invalid_input_validation(self):
        guard = Wave385TradeFlowZipfLawDeviationGuard()
        guard.update(-10.0, 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(True, 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_delegation(self):
        guard = Wave385TradeFlowZipfLawDeviationGuard()
        guard.update(0.0, 1.0)
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 1.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""
