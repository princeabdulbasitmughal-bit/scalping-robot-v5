"""
Batch 316 -- Tests for Wave 390 and Wave 391
=============================================
Wave 390: LOB Synthetic Momentum Index Guard
Wave 391: Trade Flow Gamma Scalping Detection Guard

Target: 12+ tests, 0 failures
"""

import time
import pytest

from wave390_lob_synthetic_momentum_index_guard import (
    Wave390LOBSyntheticMomentumIndexGuard,
)
from wave391_trade_flow_gamma_scalping_detection_guard import (
    Wave391TradeFlowGammaScalpingDetectionGuard,
)


class TestWave390SyntheticMomentumIndex:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave390LOBSyntheticMomentumIndexGuard(window_size=1)
        with pytest.raises(ValueError):
            Wave390LOBSyntheticMomentumIndexGuard(upper_smi_threshold=10.0, lower_smi_threshold=50.0)

    def test_balanced_smi_no_block(self):
        guard = Wave390LOBSyntheticMomentumIndexGuard(
            window_size=10, upper_smi_threshold=500.0, lower_smi_threshold=5.0
        )
        t0 = time.monotonic()
        # bid_depth=100, ask_depth=100 -> ratio=1.0, spread=1 pip (0.909 bps) -> SMI = (1.0 / 0.909) * 100 = 110.0 (in [5, 500])
        for i in range(15):
            guard.update(bid=1.1000, ask=1.1001, bid_depth=100.0, ask_depth=100.0, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_no_block_before_window_fills(self):
        guard = Wave390LOBSyntheticMomentumIndexGuard(window_size=10, upper_smi_threshold=200.0)
        t0 = time.monotonic()
        for i in range(5):
            guard.update(bid=1.1000, ask=1.1001, bid_depth=1000.0, ask_depth=10.0, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_extreme_bullish_smi_triggers_block(self):
        guard = Wave390LOBSyntheticMomentumIndexGuard(
            window_size=10, upper_smi_threshold=500.0, lower_smi_threshold=5.0
        )
        t0 = time.monotonic()
        # bid_depth=10000, ask_depth=10 -> ratio=1000, spread=0.9 bps -> SMI = 110,000 >> 500
        for i in range(15):
            guard.update(bid=1.1000, ask=1.1001, bid_depth=10000.0, ask_depth=10.0, timestamp=t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "SMI_UPPER_BREACH"

    def test_extreme_bearish_smi_triggers_block(self):
        guard = Wave390LOBSyntheticMomentumIndexGuard(
            window_size=10, upper_smi_threshold=500.0, lower_smi_threshold=10.0
        )
        t0 = time.monotonic()
        # bid_depth=10, ask_depth=1000 -> ratio=0.01, spread=5 bps -> SMI = (0.01 / 5) * 100 = 0.2 <= 10.0
        for i in range(15):
            guard.update(bid=1.1000, ask=1.10055, bid_depth=10.0, ask_depth=1000.0, timestamp=t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "SMI_LOWER_BREACH"

    def test_invalid_input_validation(self):
        guard = Wave390LOBSyntheticMomentumIndexGuard()
        guard.update(1.1005, 1.1000, 100.0, 100.0, 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(1.1000, 1.1005, -10.0, 100.0, 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_delegation(self):
        guard = Wave390LOBSyntheticMomentumIndexGuard()
        guard.update(0.0, 1.1005, 100.0, 100.0, 1.0)
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 1.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""


class TestWave391GammaScalping:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave391TradeFlowGammaScalpingDetectionGuard(window_size=3)
        with pytest.raises(ValueError):
            Wave391TradeFlowGammaScalpingDetectionGuard(min_alternations=10, window_size=10)

    def test_directional_trending_flow_no_block(self):
        guard = Wave391TradeFlowGammaScalpingDetectionGuard(
            window_size=10, min_alternations=6, max_price_range=0.0005
        )
        t0 = time.monotonic()
        # Trending: all buys, wide price range
        for i in range(15):
            guard.update(price=1.1000 + i * 0.0002, volume=10.0, side="buy", timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_no_block_before_window_fills(self):
        guard = Wave391TradeFlowGammaScalpingDetectionGuard(window_size=10)
        t0 = time.monotonic()
        for i in range(5):
            side = "buy" if i % 2 == 0 else "sell"
            guard.update(price=1.1000, volume=10.0, side=side, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_gamma_scalping_tight_range_triggers_block(self):
        guard = Wave391TradeFlowGammaScalpingDetectionGuard(
            window_size=10, min_alternations=6, max_price_range=0.0002
        )
        t0 = time.monotonic()
        # Rapidly alternating sides at the exact same price (range = 0.0 <= 0.0002)
        for i in range(12):
            side = "buy" if i % 2 == 0 else "sell"
            guard.update(price=1.1000, volume=10.0, side=side, timestamp=t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "GAMMA_SCALPING_PATTERN"

    def test_invalid_input_validation(self):
        guard = Wave391TradeFlowGammaScalpingDetectionGuard()
        guard.update(1.1000, 10.0, "invalid_side", 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(True, 10.0, "buy", 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_delegation(self):
        guard = Wave391TradeFlowGammaScalpingDetectionGuard()
        guard.update(-1.1000, 10.0, "buy", 1.0)
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 1.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""
