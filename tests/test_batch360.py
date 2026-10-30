"""
Test Batch 360: Wave 469 Liquidity Event Horizon Guard & Wave 470 Depth Curvature Acceleration Canopy Guard
============================================================================================================
Institutional unit test suite verifying black hole event horizon contraction,
microstructure curvature acceleration dynamics, and multi-tier canopy synthesis.
"""

import pytest
import math
import numpy as np
from wave469_liquidity_event_horizon_contraction_guard import Wave469LiquidityEventHorizonContractionGuard
from wave470_depth_curvature_acceleration_canopy_guard import Wave470DepthCurvatureAccelerationCanopyGuard


class TestWave469LiquidityEventHorizonContractionGuard:
    """Test suite for Wave 469: Liquidity Black Hole Event Horizon Contraction Guard."""

    def test_init_validation(self):
        with pytest.raises(ValueError, match="window_size must be >= 10"):
            Wave469LiquidityEventHorizonContractionGuard(window_size=8)
        with pytest.raises(ValueError, match="min_samples must be >= 5"):
            Wave469LiquidityEventHorizonContractionGuard(min_samples=3)
        with pytest.raises(ValueError, match="min_samples .* cannot exceed window_size"):
            Wave469LiquidityEventHorizonContractionGuard(window_size=12, min_samples=15)
        with pytest.raises(ValueError, match="critical_contraction_ratio must be in"):
            Wave469LiquidityEventHorizonContractionGuard(critical_contraction_ratio=0.05)
        with pytest.raises(ValueError, match="critical_contraction_ratio must be in"):
            Wave469LiquidityEventHorizonContractionGuard(critical_contraction_ratio=0.85)
        with pytest.raises(ValueError, match="max_contraction_velocity must be > 0.20"):
            Wave469LiquidityEventHorizonContractionGuard(max_contraction_velocity=0.10)
        with pytest.raises(ValueError, match="asymmetry_ratio_threshold must be > 1.50"):
            Wave469LiquidityEventHorizonContractionGuard(asymmetry_ratio_threshold=1.20)
        with pytest.raises(ValueError, match="cooldown_sec must be >= 0.1"):
            Wave469LiquidityEventHorizonContractionGuard(cooldown_sec=0.05)

    def test_insufficient_samples(self):
        guard = Wave469LiquidityEventHorizonContractionGuard(min_samples=8)
        for i in range(5):
            blocked = guard.update(50.0, 50.0, timestamp=10.0 + i)
            assert not blocked
            assert not guard.is_blocked()
            assert guard.block_reason == "INSUFFICIENT_SAMPLES"

    def test_calm_liquid_market_no_block(self):
        guard = Wave469LiquidityEventHorizonContractionGuard(min_samples=8, critical_contraction_ratio=0.35)
        # Establish stable liquidity baseline ~100 lots
        for i in range(12):
            guard.update(50.0, 50.0, timestamp=100.0 + i)

        assert not guard.is_blocked()
        assert not guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert guard.contraction_ratio >= 0.90
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave469LiquidityEventHorizonContractionGuard"
        assert telem["is_blocked"] is False

    def test_event_horizon_collapse_blocks_all(self):
        guard = Wave469LiquidityEventHorizonContractionGuard(
            min_samples=8,
            critical_contraction_ratio=0.35,
            asymmetry_ratio_threshold=3.50
        )
        # Stable baseline around 100 lots
        for i in range(10):
            guard.update(50.0, 50.0, timestamp=100.0 + i)

        # Severe bilateral liquidity evaporation to 20 lots total (R_H = 0.20 < 0.35)
        blocked = guard.update(10.0, 10.0, timestamp=110.0)
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "ALL"
        assert guard.is_entry_blocked("BUY")
        assert guard.is_entry_blocked("SELL")
        assert "EVENT_HORIZON_COLLAPSE" in guard.block_reason

    def test_asymmetric_bid_vacuum_blocks_sell(self):
        guard = Wave469LiquidityEventHorizonContractionGuard(
            min_samples=8,
            critical_contraction_ratio=0.35,
            asymmetry_ratio_threshold=3.50
        )
        for i in range(10):
            guard.update(50.0, 50.0, timestamp=100.0 + i)

        # Bid side collapses to 3.0 lots while ask remains 20.0 lots (total 23 < 35, asym = 3/20 = 0.15 < 1/3.5)
        blocked = guard.update(3.0, 20.0, timestamp=110.0)
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "SELL"
        assert guard.is_entry_blocked("SELL")
        assert not guard.is_entry_blocked("BUY")
        assert "BID_DEPTH_VACUUM" in guard.block_reason

    def test_asymmetric_ask_vacuum_blocks_buy(self):
        guard = Wave469LiquidityEventHorizonContractionGuard(
            min_samples=8,
            critical_contraction_ratio=0.35,
            asymmetry_ratio_threshold=3.50
        )
        for i in range(10):
            guard.update(50.0, 50.0, timestamp=100.0 + i)

        # Ask side collapses to 3.0 lots while bid remains 20.0 lots (total 23 < 35, asym = 20/3 = 6.67 > 3.5)
        blocked = guard.update(20.0, 3.0, timestamp=110.0)
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "BUY"
        assert guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert "ASK_DEPTH_VACUUM" in guard.block_reason

    def test_contraction_velocity_breach(self):
        guard = Wave469LiquidityEventHorizonContractionGuard(
            min_samples=8,
            critical_contraction_ratio=0.20,
            max_contraction_velocity=1.80
        )
        # Establish baseline across timestamps 100.0 to 109.0
        for i in range(10):
            guard.update(50.0, 50.0, timestamp=100.0 + i)

        # Sudden rapid drop from 100 to 40 in dt = 0.2s (109.0 to 109.2) -> Delta R_H = 0.60 / 0.2 = 3.0 s^-1 > 1.80
        blocked = guard.update(20.0, 20.0, timestamp=109.2)
        assert blocked
        assert guard.is_blocked()
        assert "HORIZON_CONTRACTION_VELOCITY_BREACH" in guard.block_reason

    def test_cooldown_and_reset(self):
        guard = Wave469LiquidityEventHorizonContractionGuard(min_samples=8, cooldown_sec=2.0)
        for i in range(10):
            guard.update(50.0, 50.0, timestamp=100.0 + i)

        # Trigger breach
        guard.update(5.0, 5.0, timestamp=110.0)
        assert guard.is_blocked()

        # Cooldown prevents immediate unblock even if liquidity briefly recovers
        assert guard.update(50.0, 50.0, timestamp=111.0) is True

        # After cooldown passes and liquidity is recovered
        assert guard.update(50.0, 50.0, timestamp=113.0) is False

        # Reset clears state
        guard.reset()
        assert guard.current_depth == 0.0
        assert guard.is_blocked() is False


class TestWave470DepthCurvatureAccelerationCanopyGuard:
    """Test suite for Wave 470: Multi-Tier Depth Curvature Acceleration Canopy Guard."""

    def test_init_validation(self):
        with pytest.raises(ValueError, match="critical_canopy_threshold must be in"):
            Wave470DepthCurvatureAccelerationCanopyGuard(critical_canopy_threshold=0.30)
        with pytest.raises(ValueError, match="critical_canopy_threshold must be in"):
            Wave470DepthCurvatureAccelerationCanopyGuard(critical_canopy_threshold=0.95)
        with pytest.raises(ValueError, match="min_curvature_floor must be <= -0.50"):
            Wave470DepthCurvatureAccelerationCanopyGuard(min_curvature_floor=-0.20)
        with pytest.raises(ValueError, match="max_negative_acceleration must be <= -0.50"):
            Wave470DepthCurvatureAccelerationCanopyGuard(max_negative_acceleration=-0.30)
        with pytest.raises(ValueError, match="cooldown_sec must be >= 0.1"):
            Wave470DepthCurvatureAccelerationCanopyGuard(cooldown_sec=0.05)

    def test_input_vector_length_validation(self):
        guard = Wave470DepthCurvatureAccelerationCanopyGuard()
        with pytest.raises(ValueError, match="must contain at least 3 levels"):
            guard.update([10.0, 20.0], [10.0, 20.0], [1.0, 2.0], timestamp=10.0)

    def test_healthy_convex_book_no_block(self):
        guard = Wave470DepthCurvatureAccelerationCanopyGuard(min_curvature_floor=-1.50)
        # Convex depth: levels 1, 2, 3 have accelerating depth (10, 30, 70 lots at deltas 1.0, 2.0, 3.0)
        bid_depths = [10.0, 30.0, 70.0]
        ask_depths = [10.0, 30.0, 70.0]
        deltas = [1.0, 2.0, 3.0]

        for i in range(5):
            blocked = guard.update(bid_depths, ask_depths, deltas, upstream_blackhole_risk=0.05, timestamp=10.0 + i)
            assert not blocked
            assert not guard.is_blocked()
            assert guard.min_curvature > 0.0 # Positively convex

        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave470DepthCurvatureAccelerationCanopyGuard"
        assert telem["is_blocked"] is False

    def test_concave_curvature_cliff_breach(self):
        guard = Wave470DepthCurvatureAccelerationCanopyGuard(min_curvature_floor=-1.50)
        # Deeply concave depth profile (air pocket): levels 1, 2, 3 have decelerating depth (50, 10, 2 lots)
        # slopes: (50 to 60 -> 10/1 = 10), (60 to 62 -> 2/1 = 2) -> diff slope = 2 - 10 = -8.0 -> curvature = -8.0
        bid_depths = [50.0, 10.0, 2.0]
        ask_depths = [10.0, 30.0, 60.0] # Ask is convex
        deltas = [1.0, 2.0, 3.0]

        blocked = guard.update(bid_depths, ask_depths, deltas, upstream_blackhole_risk=0.10, timestamp=10.0)
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "BUY" # Bid has concave cliff -> buying into hollow bid book is toxic
        assert guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert "CURVATURE_CONCAVITY_CLIFF" in guard.block_reason
        assert "BID_CURVATURE_CLIFF" in guard.block_reason

    def test_ask_curvature_cliff_blocks_sell(self):
        guard = Wave470DepthCurvatureAccelerationCanopyGuard(min_curvature_floor=-1.50)
        bid_depths = [10.0, 30.0, 60.0] # Bid is convex
        ask_depths = [50.0, 10.0, 2.0]  # Ask has concave cliff
        deltas = [1.0, 2.0, 3.0]

        blocked = guard.update(bid_depths, ask_depths, deltas, upstream_blackhole_risk=0.10, timestamp=10.0)
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "SELL" # Ask has concave cliff -> selling into hollow ask book is toxic
        assert guard.is_entry_blocked("SELL")
        assert not guard.is_entry_blocked("BUY")
        assert "ASK_CURVATURE_CLIFF" in guard.block_reason

    def test_curvature_acceleration_burst(self):
        guard = Wave470DepthCurvatureAccelerationCanopyGuard(
            min_curvature_floor=-15.0, # Broad floor so acceleration triggers as primary breaker
            max_negative_acceleration=-2.20
        )
        deltas = [1.0, 2.0, 3.0]
        # Step 1: gentle profile (curvature = 0.0)
        guard.update([20.0, 20.0, 20.0], [20.0, 20.0, 20.0], deltas, timestamp=10.0)

        # Step 2: sudden shift to concave cliff in dt = 0.5s
        # curvature drops from 0.0 to -10.0 in 0.5s -> accel = -20.0 / s < -2.20
        blocked = guard.update([40.0, 15.0, 5.0], [40.0, 15.0, 5.0], deltas, timestamp=10.5)
        assert blocked
        assert guard.is_blocked()
        assert "CURVATURE_ACCELERATION_BURST" in guard.block_reason

    def test_canopy_composite_fragility_breach(self):
        guard = Wave470DepthCurvatureAccelerationCanopyGuard(critical_canopy_threshold=0.65)
        deltas = [1.0, 2.0, 3.0]
        # Step 1: baseline profile
        guard.update([10.0, 20.0, 30.0], [10.0, 20.0, 30.0], deltas, timestamp=10.0)

        # Step 2: Severe concavity cliff, high acceleration and severe upstream blackhole risk
        blocked = guard.update([40.0, 15.0, 5.0], [40.0, 15.0, 5.0], deltas, upstream_blackhole_risk=0.90, timestamp=10.5)
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "ALL"
        assert guard.composite_canopy_index > 0.65

    def test_reset_and_monotonicity(self):
        guard = Wave470DepthCurvatureAccelerationCanopyGuard()
        deltas = [1.0, 2.0, 3.0]
        guard.update([10.0, 20.0, 30.0], [10.0, 20.0, 30.0], deltas, timestamp=10.0)

        # Non-monotonic timestamp raises ValueError
        with pytest.raises(ValueError, match="strictly monotonic"):
            guard.update([10.0, 20.0, 30.0], [10.0, 20.0, 30.0], deltas, timestamp=9.5)

        guard.reset()
        assert guard.bid_curvature == 0.0
        assert guard.is_blocked() is False
