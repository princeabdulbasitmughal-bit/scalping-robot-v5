"""Unit tests for Batch 281: Wave 328 and Wave 329 Risk & Microstructure Guards."""

import math
import time
import pytest

from wave328_lob_effective_depth_decay_curvature_guard import Wave328LOBEffectiveDepthDecayCurvatureGuard
from wave329_trade_flow_volume_clock_entropy_guard import Wave329TradeFlowVolumeClockEntropyGuard


# ==========================================
# Wave 328 Tests: Depth Decay Curvature
# ==========================================

def test_wave328_convex_depth_profile_no_block():
    """Verify healthy convex book depth profile does not trigger curvature blocks."""
    guard = Wave328LOBEffectiveDepthDecayCurvatureGuard(
        window_size=8,
        curvature_collapse_threshold=-1.50,
        cooldown_seconds=30.0,
    )
    t0 = 1000.0
    for i in range(12):
        # Convex book: Q1=2.0, Q2=3.5, Q3=5.0 (kappa = 5.0 - 2.0 = +3.0)
        blocked = guard.update(
            bid_price=1.1000,
            ask_price=1.1001,
            bid_depths=[2.0, 3.5, 5.0],
            ask_depths=[2.1, 3.6, 5.1],
            current_time=t0 + i,
        )
        assert not blocked
        assert not guard.is_entry_blocked(t0 + i)

    status = guard.get_status(t0 + 12)
    assert not status["is_blocked"]
    assert status["total_violations"] == 0
    assert status["buffer_fill"] == 8


def test_wave328_rolling_curvature_collapse_blocks():
    """Verify inverted fragile shell book with hollow outer tiers triggers curvature collapse block."""
    guard = Wave328LOBEffectiveDepthDecayCurvatureGuard(
        window_size=8,
        curvature_collapse_threshold=-1.50,
        acute_evaporation_ratio=1.10,  # avoid acute ratio
        cooldown_seconds=45.0,
    )
    t0 = 2000.0
    # Fragile shell: Q1=10.0, Q2=3.0, Q3=2.0 (kappa = 2.0 - 10.0 = -8.0 <= -1.50)
    for i in range(10):
        blocked = guard.update(
            bid_price=1.1000,
            ask_price=1.1001,
            bid_depths=[10.0, 3.0, 2.0],
            ask_depths=[10.0, 3.0, 2.0],
            current_time=t0 + i,
        )
        if i < 7:
            assert not blocked
        else:
            assert blocked

    assert guard.is_blocked(t0 + 10)
    status = guard.get_status(t0 + 10)
    assert "ROLLING_CURVATURE_COLLAPSE" in status["last_block_reason"]
    assert status["rolling_mean_curvature"] <= -1.50


def test_wave328_acute_depth_evaporation_blocks():
    """Verify outer book evaporation (D3 <= 1.25 * Q1) with wide spread triggers immediate block."""
    guard = Wave328LOBEffectiveDepthDecayCurvatureGuard(
        acute_evaporation_ratio=1.25,
        acute_spread_bps=2.0,
        cooldown_seconds=45.0,
    )
    t0 = 3000.0
    # Wide spread = 0.0003 on 1.1000 ~= 2.72 bps >= 2.0 bps
    # Outer tiers have virtually zero depth: Q1 = 8.0, Q2 = 0.5, Q3 = 0.5 -> D3 = 9.0 <= 1.25 * 8.0 (10.0)
    blocked = guard.update(
        bid_price=1.1000,
        ask_price=1.1003,
        bid_depths=[8.0, 0.5, 0.5],
        ask_depths=[8.0, 0.5, 0.5],
        current_time=t0,
    )
    assert blocked

    status = guard.get_status(t0)
    assert status["is_blocked"]
    assert "ACUTE_DEPTH_EVAPORATION" in status["last_block_reason"]


def test_wave328_curvature_asymmetry_blocks():
    """Verify extreme cross-side curvature discrepancy with wide spread triggers asymmetry block."""
    guard = Wave328LOBEffectiveDepthDecayCurvatureGuard(
        asymmetry_curvature_threshold=4.0,
        asymmetry_spread_bps=2.0,
        cooldown_seconds=45.0,
    )
    t0 = 4000.0
    # Bid: heavy thickening (Q1=2.0, Q2=5.0, Q3=8.0 -> kappa_bid = +6.0)
    # Ask: heavy thinning (Q1=8.0, Q2=3.0, Q3=2.0 -> kappa_ask = -6.0)
    # Discrepancy = |6 - (-6)| = 12.0 >= 4.0
    # Spread = 0.00025 on 1.1000 ~= 2.27 bps >= 2.0 bps
    blocked = guard.update(
        bid_price=1.1000,
        ask_price=1.10025,
        bid_depths=[2.0, 5.0, 8.0],
        ask_depths=[8.0, 3.0, 2.0],
        current_time=t0,
    )
    assert blocked

    status = guard.get_status(t0)
    assert "CURVATURE_ASYMMETRY_DISCREPANCY" in status["last_block_reason"]


def test_wave328_fail_closed_and_reset():
    """Verify non-numeric/bool/invalid tier inputs fail closed and reset restores pristine state."""
    guard = Wave328LOBEffectiveDepthDecayCurvatureGuard(cooldown_seconds=20.0)
    t0 = 5000.0

    # Non-numeric price
    assert guard.update(True, 1.1001, [1.0, 2.0, 3.0], [1.0, 2.0, 3.0], current_time=t0)
    assert "FAIL_CLOSED" in guard.get_status(t0)["last_block_reason"]

    guard.reset()
    # Less than 3 tiers
    assert guard.update(1.1000, 1.1001, [1.0, 2.0], [1.0, 2.0, 3.0], current_time=t0 + 1.0)
    assert "FAIL_CLOSED" in guard.get_status(t0 + 1.0)["last_block_reason"]

    guard.reset()
    # Non-positive depth in tier
    assert guard.update(1.1000, 1.1001, [1.0, -2.0, 3.0], [1.0, 2.0, 3.0], current_time=t0 + 2.0)
    assert "FAIL_CLOSED" in guard.get_status(t0 + 2.0)["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked(t0 + 3.0)
    assert guard.get_status(t0 + 3.0)["total_violations"] == 0


# ==========================================
# Wave 329 Tests: Volume-Clock Entropy
# ==========================================

def test_wave329_heterogeneous_trade_volumes_no_block():
    """Verify diverse trade sizes across all 4 tiers yield high entropy and no block."""
    guard = Wave329TradeFlowVolumeClockEntropyGuard(
        window_size=20,
        entropy_collapse_threshold=0.25,
        cooldown_seconds=30.0,
    )
    t0 = 6000.0
    # Balanced mix across Tier 0 (0.2), Tier 1 (1.0), Tier 2 (3.0), Tier 3 (5.5)
    vols = [0.2, 1.0, 3.0, 5.5] * 5
    for i, v in enumerate(vols):
        blocked = guard.update(trade_volume=v, current_time=t0 + i * 0.1)
        assert not blocked

    status = guard.get_status(t0 + 2.0)
    assert not status["is_blocked"]
    assert status["total_violations"] == 0
    assert status["normalized_entropy"] >= 0.85


def test_wave329_volume_entropy_collapse_blocks():
    """Verify rigid slicing in a single tier leads to entropy collapse and triggers block."""
    guard = Wave329TradeFlowVolumeClockEntropyGuard(
        window_size=20,
        entropy_collapse_threshold=0.25,
        robotic_streak_threshold=50,  # disable equal-volume streak
        cooldown_seconds=45.0,
    )
    t0 = 7000.0
    # 18 trades strictly in Tier 1 with slight jitter to avoid identical streak (e.g. 1.01, 1.05, 1.02...)
    for i in range(18):
        v = 1.0 + (i % 5) * 0.05
        blocked = guard.update(trade_volume=v, current_time=t0 + i * 0.1)
        if i < 15:
            assert not blocked
        else:
            assert blocked

    assert guard.is_blocked(t0 + 1.8)
    status = guard.get_status(t0 + 1.8)
    assert "VOLUME_ENTROPY_COLLAPSE" in status["last_block_reason"]
    assert status["normalized_entropy"] <= 0.25


def test_wave329_acute_whale_concentration_blocks():
    """Verify surge in whale prints (>=5.0 lots) triggers whale concentration block."""
    guard = Wave329TradeFlowVolumeClockEntropyGuard(
        window_size=15,
        whale_prob_threshold=0.50,
        whale_min_mean_volume=6.0,
        robotic_streak_threshold=50,
        cooldown_seconds=45.0,
    )
    t0 = 8000.0
    # 10 trades: 6 whale prints (7.0, 7.5, 8.0, 7.0, 8.5, 7.2) and 4 small trades (1.0, 1.2, 1.5, 1.1)
    # Whale count = 6/10 = 0.60 >= 0.50, mean vol ~= 50 / 10 = 5.0 -> need higher whale sizes
    vols = [7.5, 1.0, 8.5, 1.2, 9.0, 1.5, 8.0, 1.1, 8.5, 7.8]
    # Sum = 7.5+1+8.5+1.2+9+1.5+8+1.1+8.5+7.8 = 54.1 -> mean = 5.41
    # Let's boost whale prints to 9.5 each
    vols = [9.5, 1.0, 9.5, 1.2, 9.5, 1.5, 9.5, 1.1, 9.5, 9.5]
    # Whale count = 7/10 = 0.70 >= 0.50, sum = 6.0*9.5 + 4.8 = 61.8 -> mean = 6.18 >= 6.0
    for i, v in enumerate(vols):
        blocked = guard.update(trade_volume=v, current_time=t0 + i * 0.1)
        if i == 9:
            assert blocked

    assert guard.is_blocked(t0 + 1.0)
    status = guard.get_status(t0 + 1.0)
    assert "ACUTE_WHALE_CONCENTRATION_SHOCK" in status["last_block_reason"]


def test_wave329_robotic_equal_volume_streak_blocks():
    """Verify consecutive trades with identical volume trigger robotic sweep streak block."""
    guard = Wave329TradeFlowVolumeClockEntropyGuard(
        robotic_streak_threshold=8,
        robotic_volume_tolerance=0.001,
        cooldown_seconds=45.0,
    )
    t0 = 9000.0
    # 8 trades of exactly 0.750 lots
    for i in range(8):
        blocked = guard.update(trade_volume=0.750, current_time=t0 + i * 0.1)
        if i < 7:
            assert not blocked
        else:
            assert blocked

    assert guard.is_blocked(t0 + 0.8)
    status = guard.get_status(t0 + 0.8)
    assert "ROBOTIC_EQUAL_VOLUME_STREAK" in status["last_block_reason"]
    assert status["robotic_streak"] >= 8


def test_wave329_fail_closed_and_reset():
    """Verify non-numeric/bool/negative volume inputs fail closed and reset restores pristine state."""
    guard = Wave329TradeFlowVolumeClockEntropyGuard(cooldown_seconds=20.0)
    t0 = 10000.0

    # Non-numeric volume
    assert guard.update(True, current_time=t0)
    assert "FAIL_CLOSED" in guard.get_status(t0)["last_block_reason"]

    guard.reset()
    # NaN volume
    assert guard.update(float("nan"), current_time=t0 + 1.0)
    assert "FAIL_CLOSED" in guard.get_status(t0 + 1.0)["last_block_reason"]

    guard.reset()
    # Non-positive volume
    assert guard.update(-1.0, current_time=t0 + 2.0)
    assert "FAIL_CLOSED" in guard.get_status(t0 + 2.0)["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked(t0 + 3.0)
    assert guard.get_status(t0 + 3.0)["total_violations"] == 0
