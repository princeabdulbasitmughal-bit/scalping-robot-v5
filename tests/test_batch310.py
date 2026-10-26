"""
Batch 310 -- Tests for Wave 378 and Wave 379
=============================================
Wave 378: LOB Quote Cancellation Storm Guard
Wave 379: Trade Flow Realized Volatility Regime Guard

Target: 12+ tests, 0 failures
"""

import time
import pytest

from wave378_lob_quote_cancellation_storm_guard import (
    Wave378LOBQuoteCancellationStormGuard,
)
from wave379_trade_flow_realized_volatility_regime_guard import (
    Wave379TradeFlowRealizedVolatilityRegimeGuard,
)


class TestWave378QuoteCancellationStorm:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave378LOBQuoteCancellationStormGuard(window_seconds=0.0)
        with pytest.raises(ValueError):
            Wave378LOBQuoteCancellationStormGuard(cancel_ratio_threshold=1.5)
        with pytest.raises(ValueError):
            Wave378LOBQuoteCancellationStormGuard(min_quote_count=1)

    def test_normal_quote_flow_no_block(self):
        guard = Wave378LOBQuoteCancellationStormGuard(
            window_seconds=2.0, cancel_ratio_threshold=0.80, min_quote_count=10
        )
        t0 = time.monotonic()
        # 5 cancels, 10 submissions -> 5/15 = 33% cancels < 80%
        for i in range(15):
            is_cancel = i % 3 == 0
            guard.add_quote(is_cancel=is_cancel, timestamp=t0 + i * 0.05)
        assert not guard.is_blocked()

    def test_cancellation_storm_triggers_block(self):
        guard = Wave378LOBQuoteCancellationStormGuard(
            window_seconds=2.0, cancel_ratio_threshold=0.80, min_quote_count=10
        )
        t0 = time.monotonic()
        # 9 cancels out of 10 quotes = 90% cancels >= 80%
        for i in range(10):
            is_cancel = i != 0
            guard.add_quote(is_cancel=is_cancel, timestamp=t0 + i * 0.05)
        assert guard.is_blocked()
        assert guard.last_reason == "CANCELLATION_STORM_DETECTED"

    def test_stale_events_evicted(self):
        guard = Wave378LOBQuoteCancellationStormGuard(
            window_seconds=1.0, cancel_ratio_threshold=0.80, min_quote_count=5
        )
        t0 = time.monotonic()
        # 5 cancels at t0
        for i in range(5):
            guard.add_quote(True, timestamp=t0 + i * 0.01)
        guard.reset()
        # 5 seconds later, add 5 submissions
        for i in range(5):
            guard.add_quote(False, timestamp=t0 + 5.0 + i * 0.01)
        assert not guard.is_blocked()

    def test_invalid_input_validation(self):
        guard = Wave378LOBQuoteCancellationStormGuard()
        guard.add_quote("not_a_bool", 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.add_quote(True, True)  # timestamp is bool
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_delegation(self):
        guard = Wave378LOBQuoteCancellationStormGuard()
        guard.add_quote("bad", 1.0)
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 1.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""


class TestWave379RealizedVolatilityRegime:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave379TradeFlowRealizedVolatilityRegimeGuard(window_size=2)
        with pytest.raises(ValueError):
            Wave379TradeFlowRealizedVolatilityRegimeGuard(high_vol_threshold=0.01, low_vol_threshold=0.05)

    def test_normal_volatility_no_block(self):
        guard = Wave379TradeFlowRealizedVolatilityRegimeGuard(
            window_size=10, high_vol_threshold=10.0, low_vol_threshold=0.000001
        )
        t0 = time.monotonic()
        p = 1.1000
        for i in range(15):
            p += 0.0001 if i % 2 == 0 else -0.0001
            guard.update(price=p, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_high_volatility_spike_triggers_block(self):
        guard = Wave379TradeFlowRealizedVolatilityRegimeGuard(
            window_size=10, high_vol_threshold=5.0, low_vol_threshold=0.000001
        )
        t0 = time.monotonic()
        p = 1.1000
        # Huge swings of 0.0100 (100 pips) per tick
        for i in range(15):
            p += 0.0100 if i % 2 == 0 else -0.0100
            guard.update(price=p, timestamp=t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "HIGH_VOLATILITY_REGIME"

    def test_zero_volatility_freeze_triggers_block(self):
        guard = Wave379TradeFlowRealizedVolatilityRegimeGuard(
            window_size=10, high_vol_threshold=10.0, low_vol_threshold=0.01
        )
        t0 = time.monotonic()
        p = 1.1000
        # Completely flat prices -> RV = 0.0 <= low_vol_threshold
        for i in range(15):
            guard.update(price=p, timestamp=t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "LOW_VOLATILITY_REGIME"

    def test_invalid_input_validation(self):
        guard = Wave379TradeFlowRealizedVolatilityRegimeGuard()
        guard.update(-1.1000, 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(True, 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_delegation(self):
        guard = Wave379TradeFlowRealizedVolatilityRegimeGuard()
        guard.update(0.0, 1.0)
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 1.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""
