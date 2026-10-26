"""
Batch 309 -- Tests for Wave 376 and Wave 377
=============================================
Wave 376: LOB Asymmetric Depth Replenishment Guard
Wave 377: Trade Flow Kelly Criterion Regime Guard

Target: 12+ tests, 0 failures
"""

import time
import pytest

from wave376_lob_asymmetric_depth_replenishment_guard import (
    Wave376LOBAsymmetricDepthReplenishmentGuard,
)
from wave377_trade_flow_kelly_criterion_regime_guard import (
    Wave377TradeFlowKellyCriterionRegimeGuard,
)


class TestWave376DepthReplenishment:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave376LOBAsymmetricDepthReplenishmentGuard(window_size=1)
        with pytest.raises(ValueError):
            Wave376LOBAsymmetricDepthReplenishmentGuard(positive_threshold=-10.0)
        with pytest.raises(ValueError):
            Wave376LOBAsymmetricDepthReplenishmentGuard(negative_threshold=10.0)

    def test_symmetric_replenishment_no_block(self):
        guard = Wave376LOBAsymmetricDepthReplenishmentGuard(window_size=10, positive_threshold=50.0)
        t0 = time.monotonic()
        for i in range(20):
            # Both sides replenish equally by 10 each step
            guard.update(bid_depth=100.0 + i * 10.0, ask_depth=100.0 + i * 10.0, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_bid_side_accumulation_triggers_block(self):
        guard = Wave376LOBAsymmetricDepthReplenishmentGuard(
            window_size=10, positive_threshold=50.0, negative_threshold=-50.0
        )
        t0 = time.monotonic()
        b = 100.0
        a = 100.0
        for i in range(15):
            b += 100.0  # bids surging
            a += 10.0   # asks stagnant
            guard.update(bid_depth=b, ask_depth=a, timestamp=t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "BID_REPLENISHMENT_ASYMMETRY"

    def test_ask_side_accumulation_triggers_block(self):
        guard = Wave376LOBAsymmetricDepthReplenishmentGuard(
            window_size=10, positive_threshold=50.0, negative_threshold=-50.0
        )
        t0 = time.monotonic()
        b = 100.0
        a = 100.0
        for i in range(15):
            b += 10.0
            a += 100.0  # asks surging
            guard.update(bid_depth=b, ask_depth=a, timestamp=t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "ASK_REPLENISHMENT_ASYMMETRY"

    def test_invalid_input_validation(self):
        guard = Wave376LOBAsymmetricDepthReplenishmentGuard()
        guard.update(True, 100.0, 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(100.0, -50.0, 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_delegation(self):
        guard = Wave376LOBAsymmetricDepthReplenishmentGuard()
        guard.update(0.0, 100.0, 1.0)
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 1.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""


class TestWave377KellyCriterionRegime:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave377TradeFlowKellyCriterionRegimeGuard(window_size=3)
        with pytest.raises(ValueError):
            Wave377TradeFlowKellyCriterionRegimeGuard(kelly_threshold=1.5)

    def test_balanced_outcomes_no_block(self):
        guard = Wave377TradeFlowKellyCriterionRegimeGuard(window_size=10, kelly_threshold=0.60)
        t0 = time.monotonic()
        # Alternate winning and losing buy trades:
        # Step 0: buy at 1.1000
        # Step 1: price rises to 1.1002 (buy wins!), new trade buy at 1.1002
        # Step 2: price drops to 1.1001 (buy loses!), new trade buy at 1.1001
        p = 1.1000
        for i in range(25):
            delta = 0.0002 if i % 2 == 1 else -0.0001
            p += delta
            guard.update(volume=10.0, side="buy", price=p, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_persistent_directional_wins_trigger_block(self):
        guard = Wave377TradeFlowKellyCriterionRegimeGuard(window_size=10, kelly_threshold=0.60)
        t0 = time.monotonic()
        # All buys followed by price rises -> 100% win rate -> kelly 1.0 >= 0.60
        p = 1.1000
        for i in range(15):
            p += 0.0002
            guard.update(volume=10.0, side="buy", price=p, timestamp=t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "KELLY_REGIME_EXTREME"

    def test_persistent_directional_losses_trigger_block(self):
        guard = Wave377TradeFlowKellyCriterionRegimeGuard(window_size=10, kelly_threshold=0.60)
        t0 = time.monotonic()
        # All buys followed by price drops -> 0% win rate -> kelly -1.0 -> |kelly| >= 0.60
        p = 1.1000
        for i in range(15):
            p -= 0.0002
            guard.update(volume=10.0, side="buy", price=p, timestamp=t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "KELLY_REGIME_EXTREME"

    def test_invalid_input_validation(self):
        guard = Wave377TradeFlowKellyCriterionRegimeGuard()
        guard.update(10.0, "invalid_side", 1.1000, 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(True, "buy", 1.1000, 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_delegation(self):
        guard = Wave377TradeFlowKellyCriterionRegimeGuard()
        guard.update(0.0, "buy", 1.1000, 1.0)
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 1.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""
