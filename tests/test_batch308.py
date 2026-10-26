"""
Batch 308 -- Tests for Wave 374 and Wave 375
=============================================
Wave 374: LOB Micro-Price Mean-Reversion Speed Guard
Wave 375: Trade Flow Order Splitting Detection Guard

Target: 12+ tests, 0 failures
"""

import time
import pytest

from wave374_lob_microprice_mean_reversion_speed_guard import (
    Wave374LOBMicropriceMeanReversionSpeedGuard,
)
from wave375_trade_flow_order_splitting_detection_guard import (
    Wave375TradeFlowOrderSplittingDetectionGuard,
)


class TestWave374MicropriceReversion:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave374LOBMicropriceMeanReversionSpeedGuard(window_size=3)
        with pytest.raises(ValueError):
            Wave374LOBMicropriceMeanReversionSpeedGuard(min_reversion_speed=-0.1)

    def test_no_block_before_window_fills(self):
        guard = Wave374LOBMicropriceMeanReversionSpeedGuard(window_size=15)
        t0 = time.monotonic()
        for i in range(10):
            guard.update(1.1000 + i * 0.0001, 1.1002 + i * 0.0001, 100.0, 100.0, t0 + i)
        assert not guard.is_blocked()

    def test_insufficient_variance_blocks(self):
        guard = Wave374LOBMicropriceMeanReversionSpeedGuard(window_size=10)
        t0 = time.monotonic()
        for i in range(15):
            guard.update(1.1000, 1.1002, 100.0, 100.0, t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "INSUFFICIENT_VARIANCE"

    def test_persistent_drift_triggers_slow_reversion(self):
        guard = Wave374LOBMicropriceMeanReversionSpeedGuard(
            window_size=15, min_reversion_speed=0.20, max_reversion_speed=1.80
        )
        t0 = time.monotonic()
        # Strongly trending series has autocorrelation phi near 1.0 -> speed = 1 - phi near 0.0
        for i in range(25):
            guard.update(1.1000 + i * 0.001, 1.1002 + i * 0.001, 100.0, 100.0, t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "SLOW_MICROPRICE_REVERSION"

    def test_invalid_input_validation(self):
        guard = Wave374LOBMicropriceMeanReversionSpeedGuard()
        guard.update(True, 1.1002, 100.0, 100.0, 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(1.1002, 1.1000, 100.0, 100.0, 1.0)  # crossed quote
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_delegation(self):
        guard = Wave374LOBMicropriceMeanReversionSpeedGuard()
        guard.update(0.0, 1.1002, 100.0, 100.0, 1.0)
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 1.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""


class TestWave375OrderSplitting:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave375TradeFlowOrderSplittingDetectionGuard(small_trade_threshold=0.0)
        with pytest.raises(ValueError):
            Wave375TradeFlowOrderSplittingDetectionGuard(max_split_sequence=1)

    def test_interspersed_trades_no_block(self):
        guard = Wave375TradeFlowOrderSplittingDetectionGuard(
            small_trade_threshold=10.0, max_split_sequence=5
        )
        t0 = time.monotonic()
        # Alternating buys and sells of small size never reach sequence of 5
        for i in range(20):
            side = "buy" if i % 2 == 0 else "sell"
            guard.update(volume=5.0, side=side, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_large_trades_break_sequence(self):
        guard = Wave375TradeFlowOrderSplittingDetectionGuard(
            small_trade_threshold=10.0, max_split_sequence=5
        )
        t0 = time.monotonic()
        # 4 small buys, then 1 big buy, then 4 small buys
        for i in range(4):
            guard.update(5.0, "buy", t0 + i)
        guard.update(50.0, "buy", t0 + 4)  # resets
        for i in range(4):
            guard.update(5.0, "buy", t0 + 5 + i)
        assert not guard.is_blocked()

    def test_consecutive_small_trades_trigger_block(self):
        guard = Wave375TradeFlowOrderSplittingDetectionGuard(
            small_trade_threshold=10.0, max_split_sequence=5
        )
        t0 = time.monotonic()
        for i in range(6):
            guard.update(volume=5.0, side="buy", timestamp=t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "ORDER_SPLITTING_DETECTED"

    def test_invalid_inputs_fail_closed(self):
        guard = Wave375TradeFlowOrderSplittingDetectionGuard()
        guard.update(5.0, "invalid_side", 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(True, "buy", 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_delegation(self):
        guard = Wave375TradeFlowOrderSplittingDetectionGuard()
        guard.update(0.0, "buy", 1.0)
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 1.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""
