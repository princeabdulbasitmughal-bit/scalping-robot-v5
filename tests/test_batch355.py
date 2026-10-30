"""
Test Batch 355: Wave 459 Hawkes Contagion Guard & Wave 460 Slope Convexity Synthesizer Guard
=============================================================================================
Institutional unit test suite verifying Hawkes process cross-venue mutual excitation,
spectral radius supercritical cascades, and Level-2 order book slope-convexity sovereign canopy.
"""

import pytest
import math
import numpy as np
from wave459_hawkes_cross_venue_contagion_guard import Wave459HawkesCrossVenueContagionGuard
from wave460_orderbook_slope_convexity_synthesizer_guard import Wave460OrderbookSlopeConvexitySynthesizerGuard


class TestWave459HawkesCrossVenueContagionGuard:
    """Test suite for Wave 459: Hawkes Process Mutual-Excitation Cross-Venue Contagion Guard."""

    def test_init_validation(self):
        with pytest.raises(ValueError, match="window_events must be >= 20"):
            Wave459HawkesCrossVenueContagionGuard(window_events=10)

        with pytest.raises(ValueError, match="beta_decay must be > 1.0"):
            Wave459HawkesCrossVenueContagionGuard(beta_decay=0.5)

        with pytest.raises(ValueError, match="max_spectral_radius must be in"):
            Wave459HawkesCrossVenueContagionGuard(max_spectral_radius=0.30)
        with pytest.raises(ValueError, match="max_spectral_radius must be in"):
            Wave459HawkesCrossVenueContagionGuard(max_spectral_radius=0.99)

        with pytest.raises(ValueError, match="max_cross_ratio must be > 1.0"):
            Wave459HawkesCrossVenueContagionGuard(max_cross_ratio=0.8)

        with pytest.raises(ValueError, match="min_events must be >= 10"):
            Wave459HawkesCrossVenueContagionGuard(min_events=5)

        with pytest.raises(ValueError, match="cooldown_sec must be >= 0.1"):
            Wave459HawkesCrossVenueContagionGuard(cooldown_sec=0.05)

    def test_insufficient_events(self):
        guard = Wave459HawkesCrossVenueContagionGuard(min_events=12)
        for i in range(8):
            blocked = guard.update("A", timestamp=10.0 + i)
            assert not blocked
            assert not guard.is_blocked()
            assert guard.block_reason == "INSUFFICIENT_EVENTS"

    def test_calm_independent_arrivals_no_block(self):
        guard = Wave459HawkesCrossVenueContagionGuard(min_events=10, max_spectral_radius=0.85)

        # Feed 20 slow, spaced-out events (dt = 0.5s, decay beta=25 ensures exp(-25*0.5) ~ 0)
        t = 100.0
        for i in range(20):
            t += 0.5
            v = "A" if i % 2 == 0 else "B"
            guard.update(v, timestamp=t)

        assert not guard.is_blocked()
        assert not guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert guard.spectral_radius < 0.20
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave459HawkesCrossVenueContagionGuard"

    def test_supercritical_cascade_triggers_block(self):
        guard = Wave459HawkesCrossVenueContagionGuard(
            min_events=10,
            beta_decay=10.0,
            max_spectral_radius=0.60
        )

        # Microsecond rapid bursts back and forth triggering high cross excitation
        t = 100.0
        for i in range(25):
            t += 0.005 # 5 ms apart
            v = "A" if i % 2 == 0 else "B"
            guard.update(v, timestamp=t)

        assert guard.is_blocked()
        assert guard.is_entry_blocked("BUY")
        assert guard.is_entry_blocked("SELL")
        assert "HAWKES_SUPERCRITICAL_CASCADE" in guard.block_reason

    def test_cooldown_and_reset(self):
        guard = Wave459HawkesCrossVenueContagionGuard(
            min_events=10,
            beta_decay=10.0,
            max_spectral_radius=0.60,
            cooldown_sec=3.0
        )
        t = 100.0
        for i in range(20):
            t += 0.005
            guard.update("A" if i % 2 == 0 else "B", timestamp=t)

        assert guard.is_blocked()
        breach_t = t

        # Update within cooldown
        blocked = guard.update("A", timestamp=breach_t + 1.0)
        assert blocked
        assert guard.is_blocked()

        # Reset
        guard.reset()
        assert not guard.is_blocked()
        assert guard.spectral_radius == 0.0
        assert guard.block_reason == ""

    def test_input_validation(self):
        guard = Wave459HawkesCrossVenueContagionGuard()
        with pytest.raises(ValueError, match="venue must be 'A' or 'B'"):
            guard.update("C", timestamp=10.0)

        with pytest.raises(ValueError, match="timestamp must be finite"):
            guard.update("A", timestamp=float("nan"))

        with pytest.raises(ValueError, match="timestamp must be strictly monotonic"):
            guard.update("A", timestamp=10.0)
            guard.update("A", timestamp=10.0)


class TestWave460OrderbookSlopeConvexitySynthesizerGuard:
    """Test suite for Wave 460: Level-2 Order Book Slope Convexity Invariant Synthesizer Guard."""

    def test_init_validation(self):
        with pytest.raises(ValueError, match="critical_composite_threshold must be in"):
            Wave460OrderbookSlopeConvexitySynthesizerGuard(critical_composite_threshold=0.20)

        with pytest.raises(ValueError, match="min_convexity_floor must be <="):
            Wave460OrderbookSlopeConvexitySynthesizerGuard(min_convexity_floor=-0.20)

        with pytest.raises(ValueError, match="max_slope_asymmetry_ratio must be >"):
            Wave460OrderbookSlopeConvexitySynthesizerGuard(max_slope_asymmetry_ratio=1.0)

        with pytest.raises(ValueError, match="cooldown_sec must be >= 0.1"):
            Wave460OrderbookSlopeConvexitySynthesizerGuard(cooldown_sec=0.05)

    def test_calm_convex_book_no_block(self):
        guard = Wave460OrderbookSlopeConvexitySynthesizerGuard(critical_composite_threshold=0.68)

        # Depth thickens convexly away from midprice: [100, 250, 450] at distances [1.0, 2.0, 3.0]
        # Cumulative depth: [100, 350, 800] -> acceleration positive (convexity > 0)
        depths = [100.0, 250.0, 450.0]
        dists = [1.0, 2.0, 3.0]

        blocked = guard.update(
            bid_depths=depths,
            ask_depths=depths,
            tick_distances=dists,
            multiscale_fragility=0.10,
            jump_variance_ratio=0.05,
            kyle_divergence=0.10,
            queue_depletion_hazard=0.10,
            hawkes_spectral_radius=0.15,
            timestamp=100.0
        )

        assert not blocked
        assert not guard.is_blocked()
        assert not guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert guard.bid_convexity > 0.0
        assert guard.ask_convexity > 0.0
        assert guard.composite_invariant < 0.30
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave460OrderbookSlopeConvexitySynthesizerGuard"

    def test_concave_liquidity_cliff_bid_blocks_buy(self):
        guard = Wave460OrderbookSlopeConvexitySynthesizerGuard(
            min_convexity_floor=-1.80
        )

        # Bid depth thins drastically: [300, 20, 5] at dists [1.0, 2.0, 3.0]
        # Cumulative bid: [300, 320, 325] -> strong negative curvature / concave cliff
        bid_depths = [300.0, 20.0, 5.0]
        ask_depths = [100.0, 200.0, 300.0]
        dists = [1.0, 2.0, 3.0]

        blocked = guard.update(bid_depths, ask_depths, dists, timestamp=150.0)
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "BUY"
        assert guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert "CONCAVE_LIQUIDITY_CLIFF_BID" in guard.block_reason

    def test_concave_liquidity_cliff_ask_blocks_sell(self):
        guard = Wave460OrderbookSlopeConvexitySynthesizerGuard(
            min_convexity_floor=-1.80
        )

        bid_depths = [100.0, 200.0, 300.0]
        ask_depths = [300.0, 20.0, 5.0] # Concave cliff on ask
        dists = [1.0, 2.0, 3.0]

        blocked = guard.update(bid_depths, ask_depths, dists, timestamp=200.0)
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "SELL"
        assert guard.is_entry_blocked("SELL")
        assert not guard.is_entry_blocked("BUY")
        assert "CONCAVE_LIQUIDITY_CLIFF_ASK" in guard.block_reason

    def test_grand_sovereign_canopy_breach_blocks_all(self):
        guard = Wave460OrderbookSlopeConvexitySynthesizerGuard(
            critical_composite_threshold=0.65
        )

        # Even with normal depths, high upstream wave risks trigger the master canopy
        depths = [100.0, 100.0, 100.0]
        dists = [1.0, 2.0, 3.0]

        blocked = guard.update(
            bid_depths=depths,
            ask_depths=depths,
            tick_distances=dists,
            multiscale_fragility=0.90,
            jump_variance_ratio=0.80,
            kyle_divergence=0.85,
            queue_depletion_hazard=0.80,
            hawkes_spectral_radius=0.90,
            timestamp=250.0
        )

        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "ALL"
        assert guard.is_entry_blocked("BUY")
        assert guard.is_entry_blocked("SELL")
        assert "GRAND_SOVEREIGN_CANOPY_BREACH" in guard.block_reason

    def test_cooldown_and_reset(self):
        guard = Wave460OrderbookSlopeConvexitySynthesizerGuard(cooldown_sec=2.0)
        guard.update([300.0, 10.0, 5.0], [100.0, 100.0, 100.0], [1.0, 2.0, 3.0], timestamp=10.0)
        assert guard.is_blocked()

        # Update within cooldown
        blocked = guard.update([100.0, 100.0, 100.0], [100.0, 100.0, 100.0], [1.0, 2.0, 3.0], timestamp=11.0)
        assert blocked
        assert guard.is_blocked()

        # Reset
        guard.reset()
        assert not guard.is_blocked()
        assert guard.composite_invariant == 0.0
        assert guard.blocked_side is None

    def test_input_validation(self):
        guard = Wave460OrderbookSlopeConvexitySynthesizerGuard()
        with pytest.raises(ValueError, match="Must provide at least 3 levels"):
            guard.update([100.0, 100.0], [100.0, 100.0], [1.0, 2.0], timestamp=1.0)

        with pytest.raises(ValueError, match="matching lengths"):
            guard.update([100.0, 100.0, 100.0], [100.0, 100.0, 100.0, 100.0], [1.0, 2.0, 3.0], timestamp=1.0)

        with pytest.raises(ValueError, match="must be non-negative"):
            guard.update([-50.0, 100.0, 100.0], [100.0, 100.0, 100.0], [1.0, 2.0, 3.0], timestamp=1.0)

        with pytest.raises(ValueError, match="timestamp must be strictly monotonic"):
            guard.update([100.0, 100.0, 100.0], [100.0, 100.0, 100.0], [1.0, 2.0, 3.0], timestamp=5.0)
            guard.update([100.0, 100.0, 100.0], [100.0, 100.0, 100.0], [1.0, 2.0, 3.0], timestamp=5.0)
