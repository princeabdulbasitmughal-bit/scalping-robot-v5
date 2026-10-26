"""
Batch 311 -- Tests for Wave 380 and Wave 381
=============================================
Wave 380: LOB Depth Convexity Sign-Change Guard  [LANDMARK WAVE 380]
Wave 381: Trade Flow Hurst Exponent Regime Classifier Guard

Target: 12+ tests, 0 failures
"""

import time
import pytest

from wave380_lob_depth_convexity_sign_change_guard import (
    Wave380LOBDepthConvexitySignChangeGuard,
)
from wave381_trade_flow_hurst_regime_classifier_guard import (
    Wave381TradeFlowHurstRegimeClassifierGuard,
)


class TestWave380DepthConvexity:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave380LOBDepthConvexitySignChangeGuard(window_size=2)
        with pytest.raises(ValueError):
            Wave380LOBDepthConvexitySignChangeGuard(sign_change_threshold=1.5)

    def test_smooth_linear_depth_no_block(self):
        guard = Wave380LOBDepthConvexitySignChangeGuard(window_size=10, sign_change_threshold=0.60)
        t0 = time.monotonic()
        # Linear change -> d2 is 0 -> no sign changes
        for i in range(20):
            guard.update(bid_depth=100.0 + i * 5.0, ask_depth=100.0, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_erratic_curvature_triggers_block(self):
        guard = Wave380LOBDepthConvexitySignChangeGuard(window_size=10, sign_change_threshold=0.50)
        t0 = time.monotonic()
        # Alternating curvature pattern: 100, 110, 100, 110... produces alternating d2
        depths = [100.0, 120.0, 100.0, 120.0, 100.0, 120.0, 100.0, 120.0, 100.0, 120.0, 100.0, 120.0, 100.0, 120.0]
        for i, d in enumerate(depths):
            guard.update(bid_depth=d, ask_depth=100.0, timestamp=t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "LOB_CONVEXITY_INSTABILITY"

    def test_invalid_input_validation(self):
        guard = Wave380LOBDepthConvexitySignChangeGuard()
        guard.update(True, 100.0, 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(-50.0, 100.0, 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_delegation(self):
        guard = Wave380LOBDepthConvexitySignChangeGuard()
        guard.update(0.0, 100.0, 1.0)
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 1.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""

    def test_no_block_before_window_fills(self):
        guard = Wave380LOBDepthConvexitySignChangeGuard(window_size=10, sign_change_threshold=0.50)
        t0 = time.monotonic()
        depths = [100.0, 120.0, 100.0, 120.0, 100.0]
        for i, d in enumerate(depths):
            guard.update(bid_depth=d, ask_depth=100.0, timestamp=t0 + i)
        assert not guard.is_blocked()


class TestWave381HurstRegimeClassifier:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave381TradeFlowHurstRegimeClassifierGuard(window_size=5)
        with pytest.raises(ValueError):
            Wave381TradeFlowHurstRegimeClassifierGuard(h_low=0.8, h_high=0.5)

    def test_insufficient_variance_blocks(self):
        guard = Wave381TradeFlowHurstRegimeClassifierGuard(window_size=15)
        t0 = time.monotonic()
        for i in range(20):
            guard.update(volume=10.0, side="buy", timestamp=t0 + i)  # all +10.0 -> zero variance
        assert guard.is_blocked()
        assert guard.last_reason == "INSUFFICIENT_VARIANCE"

    def test_antipersistent_regime_triggers_block(self):
        guard = Wave381TradeFlowHurstRegimeClassifierGuard(
            window_size=20, h_low=0.45, h_high=0.85
        )
        t0 = time.monotonic()
        # Strictly alternating buy/sell of equal size produces small cumulative range R -> low H
        for i in range(25):
            side = "buy" if i % 2 == 0 else "sell"
            vol = 10.0 if i % 2 == 0 else 12.0
            guard.update(volume=vol, side=side, timestamp=t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason in ("ANTIPERSISTENT_FLOW", "PERSISTENT_FLOW")

    def test_invalid_input_validation(self):
        guard = Wave381TradeFlowHurstRegimeClassifierGuard()
        guard.update(10.0, "invalid_side", 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(True, "buy", 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_delegation(self):
        guard = Wave381TradeFlowHurstRegimeClassifierGuard()
        guard.update(-10.0, "buy", 1.0)
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 1.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""

    def test_no_block_before_window_fills(self):
        guard = Wave381TradeFlowHurstRegimeClassifierGuard(window_size=20)
        t0 = time.monotonic()
        for i in range(10):
            guard.update(volume=10.0 + i, side="buy", timestamp=t0 + i)
        assert not guard.is_blocked()
