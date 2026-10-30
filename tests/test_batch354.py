"""
Test Batch 354: Wave 457 Cross-Venue Kyle's Lambda Guard & Wave 458 Queue Depletion Survival Guard
===================================================================================================
Institutional unit test suite verifying cross-venue Kyle's Lambda order flow toxicity divergence,
multi-tier limit order book queue depletion hazard rates, and survival analysis circuit breakers.
"""

import pytest
import math
import numpy as np
from wave457_cross_venue_kyle_lambda_guard import Wave457CrossVenueKyleLambdaGuard
from wave458_queue_depletion_survival_guard import Wave458QueueDepletionSurvivalGuard


class TestWave457CrossVenueKyleLambdaGuard:
    """Test suite for Wave 457: Cross-Venue Order Flow Toxicity Kyle's Lambda Divergence Guard."""

    def test_init_validation(self):
        with pytest.raises(ValueError, match="window_size must be >= 10"):
            Wave457CrossVenueKyleLambdaGuard(window_size=8)

        with pytest.raises(ValueError, match="max_divergence_ratio must be in"):
            Wave457CrossVenueKyleLambdaGuard(max_divergence_ratio=0.15)
        with pytest.raises(ValueError, match="max_divergence_ratio must be in"):
            Wave457CrossVenueKyleLambdaGuard(max_divergence_ratio=0.99)

        with pytest.raises(ValueError, match="toxic_lambda_threshold must be > 0.0"):
            Wave457CrossVenueKyleLambdaGuard(toxic_lambda_threshold=-0.01)

        with pytest.raises(ValueError, match="max_impact_ratio must be > 1.0"):
            Wave457CrossVenueKyleLambdaGuard(max_impact_ratio=0.9)

        with pytest.raises(ValueError, match="min_samples must be >= 5"):
            Wave457CrossVenueKyleLambdaGuard(min_samples=3)

        with pytest.raises(ValueError, match="cooldown_sec must be >= 0.1"):
            Wave457CrossVenueKyleLambdaGuard(cooldown_sec=0.05)

    def test_insufficient_samples(self):
        guard = Wave457CrossVenueKyleLambdaGuard(min_samples=8)
        for i in range(5):
            blocked = guard.update(0.1, 1.0, 0.1, 1.0, timestamp=10.0 + i)
            assert not blocked
            assert not guard.is_blocked()
            assert guard.block_reason == "INSUFFICIENT_SAMPLES"

    def test_calm_symmetric_flow_no_block(self):
        guard = Wave457CrossVenueKyleLambdaGuard(min_samples=10, max_divergence_ratio=0.70)

        # Feed 15 balanced, calm observations with mild price impact
        for i in range(15):
            flow = 5.0 + (i % 3)
            dp = 0.01 * flow # lambda ~ 0.01 < toxic_lambda_threshold (0.02)
            guard.update(
                d_price_a=dp,
                flow_a=flow,
                d_price_b=dp * 1.02,
                flow_b=flow,
                timestamp=100.0 + i
            )

        assert not guard.is_blocked()
        assert not guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert guard.divergence_ratio < 0.20

    def test_toxic_kyle_lambda_divergence_blocks_buy(self):
        guard = Wave457CrossVenueKyleLambdaGuard(
            min_samples=10,
            toxic_lambda_threshold=0.02,
            max_divergence_ratio=0.60
        )

        # Baseline warm up
        for i in range(10):
            guard.update(0.005, 1.0, 0.005, 1.0, timestamp=100.0 + i)

        # Venue A undergoes massive price impact spike on buy orders (lambda_A = 0.05 / 1.0 = 0.05)
        # While Venue B remains stale with low impact (lambda_B = 0.005 / 1.0 = 0.005)
        for i in range(10, 20):
            flow = 10.0 + (i % 2) * 2.0
            dp_a = 0.06 * flow  # lambda_A ~ 0.06
            dp_b = 0.005 * flow # lambda_B ~ 0.005
            guard.update(dp_a, flow, dp_b, flow, timestamp=100.0 + i)

        assert guard.is_blocked()
        assert guard.blocked_side == "BUY"
        assert guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert "TOXIC_KYLE_LAMBDA_DIVERGENCE" in guard.block_reason

    def test_toxic_kyle_lambda_divergence_blocks_sell(self):
        guard = Wave457CrossVenueKyleLambdaGuard(
            min_samples=10,
            toxic_lambda_threshold=0.02,
            max_divergence_ratio=0.60
        )

        # Aggressive sell sweep on Venue A: flow < 0, dp < 0
        for i in range(15):
            flow_a = -10.0 - (i % 3)
            dp_a = 0.05 * flow_a # large negative price drop
            flow_b = -1.0
            dp_b = -0.001
            guard.update(dp_a, flow_a, dp_b, flow_b, timestamp=200.0 + i)

        assert guard.is_blocked()
        assert guard.blocked_side == "SELL"
        assert guard.is_entry_blocked("SELL")
        assert not guard.is_entry_blocked("BUY")

    def test_cooldown_and_reset(self):
        guard = Wave457CrossVenueKyleLambdaGuard(
            min_samples=10,
            toxic_lambda_threshold=0.02,
            max_divergence_ratio=0.50,
            cooldown_sec=3.0
        )
        for i in range(12):
            guard.update(0.1 * (i + 1), float(i + 1), 0.001, 1.0, timestamp=100.0 + i)

        assert guard.is_blocked()
        breach_t = 100.0 + 11

        # Within cooldown
        blocked = guard.update(0.001, 1.0, 0.001, 1.0, timestamp=breach_t + 1.0)
        assert blocked
        assert guard.is_blocked()

        # Reset
        guard.reset()
        assert not guard.is_blocked()
        assert guard.lambda_a == 0.0
        assert guard.blocked_side is None

    def test_input_validation(self):
        guard = Wave457CrossVenueKyleLambdaGuard()
        with pytest.raises(ValueError, match="d_price_a must be finite"):
            guard.update(float("nan"), 1.0, 0.1, 1.0, timestamp=10.0)

        with pytest.raises(ValueError, match="timestamp must be strictly monotonic"):
            guard.update(0.1, 1.0, 0.1, 1.0, timestamp=10.0)
            guard.update(0.1, 1.0, 0.1, 1.0, timestamp=10.0)


class TestWave458QueueDepletionSurvivalGuard:
    """Test suite for Wave 458: Multi-Tier LOB Queue Depletion Survival Analysis Guard."""

    def test_init_validation(self):
        with pytest.raises(ValueError, match="horizon_sec must be > 0.005"):
            Wave458QueueDepletionSurvivalGuard(horizon_sec=0.001)

        with pytest.raises(ValueError, match="min_survival_prob must be in"):
            Wave458QueueDepletionSurvivalGuard(min_survival_prob=0.02)
        with pytest.raises(ValueError, match="min_survival_prob must be in"):
            Wave458QueueDepletionSurvivalGuard(min_survival_prob=0.95)

        with pytest.raises(ValueError, match="max_top_hazard must be >= 1.0"):
            Wave458QueueDepletionSurvivalGuard(max_top_hazard=0.5)

        with pytest.raises(ValueError, match="cooldown_sec must be >= 0.1"):
            Wave458QueueDepletionSurvivalGuard(cooldown_sec=0.02)

    def test_calm_deep_book_no_block(self):
        guard = Wave458QueueDepletionSurvivalGuard(horizon_sec=0.10, min_survival_prob=0.30)

        # Deep order book with light cancellations and fills
        depths = [1000.0, 2000.0, 3000.0]
        cancels = [2.0, 4.0, 5.0]
        fills = [1.0, 2.0, 2.0]
        dt = 0.10

        blocked = guard.update(depths, cancels, fills, dt=dt, timestamp=100.0)
        assert not blocked
        assert not guard.is_blocked()
        assert not guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert guard.composite_survival > 0.95
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave458QueueDepletionSurvivalGuard"

    def test_top_queue_flash_drain(self):
        guard = Wave458QueueDepletionSurvivalGuard(
            horizon_sec=0.10,
            max_top_hazard=4.0
        )

        # L1 has 50 units resting, but 30 units canceled + 20 units filled in dt=0.1s
        # h_1 = (30 + 20) / (50 * 0.1) = 50 / 5 = 10.0 s^-1 > 4.0 s^-1
        depths = [50.0, 1000.0, 1000.0]
        cancels = [30.0, 2.0, 2.0]
        fills = [20.0, 1.0, 1.0]
        dt = 0.10

        blocked = guard.update(depths, cancels, fills, dt=dt, timestamp=150.0)
        assert blocked
        assert guard.is_blocked()
        assert "TOP_QUEUE_FLASH_DRAIN" in guard.block_reason
        assert guard.hazard_rates[0] == 10.0

    def test_multi_tier_queue_evaporation(self):
        guard = Wave458QueueDepletionSurvivalGuard(
            horizon_sec=0.10,
            min_survival_prob=0.35,
            max_top_hazard=15.0 # High top hazard so multi-tier triggers first
        )

        # Broad order book evacuation across L1, L2, and L3
        # Depths are depleted rapidly across all tiers
        depths = [100.0, 100.0, 100.0]
        cancels = [60.0, 60.0, 60.0]
        fills = [40.0, 40.0, 40.0]
        # h_k = 100 / (100 * 0.1) = 10.0 s^-1
        # S_k(0.1s) = exp(-10 * 0.1) = exp(-1.0) ~ 0.3678
        # S_multi = 0.3678.
        # Now if cancels+fills = 120 / (100 * 0.1) = 12.0 s^-1: S_k = exp(-1.2) = 0.3012 < 0.35
        cancels = [70.0, 70.0, 70.0]
        fills = [50.0, 50.0, 50.0]
        dt = 0.10

        blocked = guard.update(depths, cancels, fills, dt=dt, timestamp=200.0)
        assert blocked
        assert guard.is_blocked()
        assert "MULTI_TIER_QUEUE_EVAPORATION" in guard.block_reason
        assert guard.composite_survival < 0.35

    def test_cooldown_and_reset(self):
        guard = Wave458QueueDepletionSurvivalGuard(
            horizon_sec=0.10,
            max_top_hazard=3.0,
            cooldown_sec=2.0
        )
        guard.update([10.0, 100.0, 100.0], [5.0, 1.0, 1.0], [5.0, 1.0, 1.0], dt=0.1, timestamp=10.0)
        assert guard.is_blocked()

        # Update within cooldown
        blocked = guard.update([1000.0, 1000.0, 1000.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], dt=0.1, timestamp=11.0)
        assert blocked
        assert guard.is_blocked()

        # Reset
        guard.reset()
        assert not guard.is_blocked()
        assert guard.composite_survival == 1.0
        assert guard.block_reason == ""

    def test_input_validation(self):
        guard = Wave458QueueDepletionSurvivalGuard()
        with pytest.raises(ValueError, match="Must provide at least 3 tiers"):
            guard.update([100.0, 200.0], [1.0, 2.0], [1.0, 2.0], dt=0.1, timestamp=1.0)

        with pytest.raises(ValueError, match="dt must be strictly positive"):
            guard.update([100.0, 100.0, 100.0], [1.0, 1.0, 1.0], [1.0, 1.0, 1.0], dt=0.0, timestamp=1.0)

        with pytest.raises(ValueError, match="must be non-negative"):
            guard.update([-10.0, 100.0, 100.0], [1.0, 1.0, 1.0], [1.0, 1.0, 1.0], dt=0.1, timestamp=1.0)

        with pytest.raises(ValueError, match="timestamp must be strictly monotonic"):
            guard.update([100.0, 100.0, 100.0], [1.0, 1.0, 1.0], [1.0, 1.0, 1.0], dt=0.1, timestamp=5.0)
            guard.update([100.0, 100.0, 100.0], [1.0, 1.0, 1.0], [1.0, 1.0, 1.0], dt=0.1, timestamp=5.0)
