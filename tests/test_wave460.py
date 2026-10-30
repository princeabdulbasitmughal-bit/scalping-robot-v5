"""
Unit Test Suite for Wave 460: Dynamic Level-2 Order Book Slope Convexity Invariant Synthesizer Guard
"""

import pytest
from wave460_orderbook_slope_convexity_synthesizer_guard import Wave460OrderbookSlopeConvexitySynthesizerGuard


def test_initialization_defaults_and_validation():
    guard = Wave460OrderbookSlopeConvexitySynthesizerGuard()
    assert guard.critical_composite_threshold == 0.68
    assert guard.min_convexity_floor == -1.80
    assert guard.max_slope_asymmetry_ratio == 3.20
    assert guard.cooldown_sec == 2.0
    assert not guard.is_blocked()

    with pytest.raises(ValueError, match="critical_composite_threshold"):
        Wave460OrderbookSlopeConvexitySynthesizerGuard(critical_composite_threshold=0.20)
    with pytest.raises(ValueError, match="min_convexity_floor"):
        Wave460OrderbookSlopeConvexitySynthesizerGuard(min_convexity_floor=-0.30)
    with pytest.raises(ValueError, match="max_slope_asymmetry_ratio"):
        Wave460OrderbookSlopeConvexitySynthesizerGuard(max_slope_asymmetry_ratio=1.10)
    with pytest.raises(ValueError, match="cooldown_sec"):
        Wave460OrderbookSlopeConvexitySynthesizerGuard(cooldown_sec=0.05)


def test_input_validation_and_monotonicity():
    guard = Wave460OrderbookSlopeConvexitySynthesizerGuard()
    # Less than 3 levels
    with pytest.raises(ValueError, match="at least 3 levels"):
        guard.update([10.0, 20.0], [10.0, 20.0], [1.0, 2.0], timestamp=10.0)

    # Length mismatch
    with pytest.raises(ValueError, match="matching lengths"):
        guard.update([10.0, 20.0, 30.0, 40.0], [10.0, 20.0, 30.0], [1.0, 2.0, 3.0, 4.0], timestamp=10.0)

    # Negative depths
    with pytest.raises(ValueError, match="non-negative"):
        guard.update([-5.0, 20.0, 30.0], [10.0, 20.0, 30.0], [1.0, 2.0, 3.0], timestamp=10.0)

    # Non-monotonic timestamp
    guard.update([10.0, 20.0, 30.0], [10.0, 20.0, 30.0], [1.0, 2.0, 3.0], timestamp=10.0)
    with pytest.raises(ValueError, match="strictly monotonic"):
        guard.update([10.0, 20.0, 30.0], [10.0, 20.0, 30.0], [1.0, 2.0, 3.0], timestamp=10.0)
    with pytest.raises(ValueError, match="strictly monotonic"):
        guard.update([10.0, 20.0, 30.0], [10.0, 20.0, 30.0], [1.0, 2.0, 3.0], timestamp=9.0)


def test_healthy_convex_orderbook_no_block():
    guard = Wave460OrderbookSlopeConvexitySynthesizerGuard()
    # Healthy expanding book: depth increases with distance
    dist = [1.0, 2.0, 3.0, 4.0, 5.0]
    bid_depths = [20.0, 45.0, 80.0, 120.0, 180.0]
    ask_depths = [20.0, 45.0, 80.0, 120.0, 180.0]

    blocked = guard.update(
        bid_depths=bid_depths,
        ask_depths=ask_depths,
        tick_distances=dist,
        multiscale_fragility=0.05,
        jump_variance_ratio=0.02,
        kyle_divergence=0.05,
        queue_depletion_hazard=0.05,
        hawkes_spectral_radius=0.10,
        timestamp=10.0
    )

    assert not blocked
    assert not guard.is_blocked()
    assert guard.bid_convexity > 0.0
    assert guard.ask_convexity > 0.0
    assert guard.composite_invariant < 0.68
    assert guard.block_reason == ""


def test_concave_bid_liquidity_cliff_block():
    guard = Wave460OrderbookSlopeConvexitySynthesizerGuard(min_convexity_floor=-1.80)
    # Severe concave cliff on bid: depth collapses at outer ticks
    dist = [1.0, 2.0, 3.0, 4.0, 5.0]
    bid_depths = [250.0, 10.0, 1.0, 0.5, 0.1]
    ask_depths = [50.0, 80.0, 120.0, 160.0, 200.0]

    blocked = guard.update(
        bid_depths=bid_depths,
        ask_depths=ask_depths,
        tick_distances=dist,
        timestamp=20.0
    )

    assert blocked
    assert guard.is_blocked()
    assert guard.blocked_side == "BUY"
    assert guard.is_entry_blocked("BUY")
    assert not guard.is_entry_blocked("SELL")
    assert "CONCAVE_LIQUIDITY_CLIFF_BID" in guard.block_reason
    assert guard.bid_convexity < -1.80


def test_concave_ask_liquidity_cliff_block():
    guard = Wave460OrderbookSlopeConvexitySynthesizerGuard(min_convexity_floor=-1.80)
    # Severe concave cliff on ask: depth collapses at outer ticks
    dist = [1.0, 2.0, 3.0, 4.0, 5.0]
    bid_depths = [50.0, 80.0, 120.0, 160.0, 200.0]
    ask_depths = [250.0, 10.0, 1.0, 0.5, 0.1]

    blocked = guard.update(
        bid_depths=bid_depths,
        ask_depths=ask_depths,
        tick_distances=dist,
        timestamp=30.0
    )

    assert blocked
    assert guard.is_blocked()
    assert guard.blocked_side == "SELL"
    assert guard.is_entry_blocked("SELL")
    assert not guard.is_entry_blocked("BUY")
    assert "CONCAVE_LIQUIDITY_CLIFF_ASK" in guard.block_reason
    assert guard.ask_convexity < -1.80


def test_grand_sovereign_canopy_breach_block():
    guard = Wave460OrderbookSlopeConvexitySynthesizerGuard(critical_composite_threshold=0.68)
    dist = [1.0, 2.0, 3.0, 4.0]
    bid_depths = [100.0, 100.0, 100.0, 100.0]
    ask_depths = [100.0, 100.0, 100.0, 100.0]

    # Extreme risk values across all upstream models
    blocked = guard.update(
        bid_depths=bid_depths,
        ask_depths=ask_depths,
        tick_distances=dist,
        multiscale_fragility=0.95,
        jump_variance_ratio=0.85,
        kyle_divergence=0.90,
        queue_depletion_hazard=0.90,
        hawkes_spectral_radius=0.95,
        timestamp=40.0
    )

    assert blocked
    assert guard.is_blocked()
    assert guard.blocked_side == "ALL"
    assert guard.is_entry_blocked("BUY")
    assert guard.is_entry_blocked("SELL")
    assert "GRAND_SOVEREIGN_CANOPY_BREACH" in guard.block_reason
    assert guard.composite_invariant > 0.68


def test_cooldown_period_enforcement():
    guard = Wave460OrderbookSlopeConvexitySynthesizerGuard(cooldown_sec=2.0)
    dist = [1.0, 2.0, 3.0, 4.0, 5.0]
    # Trigger cliff breach (bid_convexity < -1.80)
    guard.update([250.0, 10.0, 1.0, 0.5, 0.1], [50.0, 80.0, 120.0, 160.0, 200.0], dist, timestamp=50.0)
    assert guard.is_blocked()

    # Next update within cooldown (0.5s < 2.0s cooldown) with calm inputs
    blocked_in_cooldown = guard.update([50.0, 100.0, 200.0, 300.0, 400.0], [50.0, 100.0, 200.0, 300.0, 400.0], dist, timestamp=50.5)
    assert blocked_in_cooldown
    assert guard.is_blocked()


def test_telemetry_dictionary_structure():
    guard = Wave460OrderbookSlopeConvexitySynthesizerGuard()
    dist = [1.0, 2.0, 3.0]
    guard.update([50.0, 100.0, 150.0], [50.0, 100.0, 150.0], dist, timestamp=60.0)

    telem = guard.get_telemetry()
    assert telem["guard"] == "Wave460OrderbookSlopeConvexitySynthesizerGuard"
    assert "bid_slope" in telem
    assert "ask_slope" in telem
    assert "bid_convexity" in telem
    assert "ask_convexity" in telem
    assert "slope_asymmetry" in telem
    assert "composite_invariant" in telem
    assert telem["critical_composite_threshold"] == 0.68
    assert isinstance(telem["is_blocked"], bool)


def test_reset_functionality():
    guard = Wave460OrderbookSlopeConvexitySynthesizerGuard()
    dist = [1.0, 2.0, 3.0, 4.0, 5.0]
    guard.update([250.0, 10.0, 1.0, 0.5, 0.1], [50.0, 80.0, 120.0, 160.0, 200.0], dist, timestamp=70.0)
    assert guard.is_blocked()

    guard.reset()
    assert not guard.is_blocked()
    assert guard.bid_slope == 0.0
    assert guard.ask_slope == 0.0
    assert guard.bid_convexity == 0.0
    assert guard.ask_convexity == 0.0
    assert guard.slope_asymmetry == 1.0
    assert guard.composite_invariant == 0.0
    assert guard.blocked_side is None
    assert guard.block_reason == ""
    assert guard._last_breach_time == -1.0
