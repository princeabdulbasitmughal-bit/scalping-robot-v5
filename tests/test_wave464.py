"""
Unit Test Suite for Wave 464: Multi-Level Volumetric Liquidity Drain Velocity Vector Guard
"""

import pytest
from wave464_orderbook_liquidity_drain_velocity_guard import Wave464OrderbookLiquidityDrainVelocityGuard


def test_initialization_defaults_and_validation():
    guard = Wave464OrderbookLiquidityDrainVelocityGuard()
    assert guard.max_drain_velocity == 2.20
    assert guard.max_drain_acceleration == 3.50
    assert guard.cooldown_sec == 2.0
    assert not guard.is_blocked()

    with pytest.raises(ValueError, match="max_drain_velocity"):
        Wave464OrderbookLiquidityDrainVelocityGuard(max_drain_velocity=0.30)
    with pytest.raises(ValueError, match="max_drain_acceleration"):
        Wave464OrderbookLiquidityDrainVelocityGuard(max_drain_acceleration=0.20)
    with pytest.raises(ValueError, match="cooldown_sec"):
        Wave464OrderbookLiquidityDrainVelocityGuard(cooldown_sec=0.05)


def test_input_validation_and_monotonicity():
    guard = Wave464OrderbookLiquidityDrainVelocityGuard()

    # Fewer than 5 levels
    with pytest.raises(ValueError, match="at least 5 levels"):
        guard.update([100.0, 100.0, 100.0, 100.0], timestamp=10.0)

    # Negative depth
    with pytest.raises(ValueError, match="non-negative"):
        guard.update([100.0, -5.0, 100.0, 100.0, 100.0], timestamp=10.0)

    # Monotonic timestamps
    guard.update([100.0, 100.0, 100.0, 100.0, 100.0], timestamp=10.0)
    with pytest.raises(ValueError, match="strictly monotonic"):
        guard.update([100.0, 100.0, 100.0, 100.0, 100.0], timestamp=10.0)
    with pytest.raises(ValueError, match="strictly monotonic"):
        guard.update([100.0, 100.0, 100.0, 100.0, 100.0], timestamp=9.0)


def test_initialization_first_tick_no_block():
    guard = Wave464OrderbookLiquidityDrainVelocityGuard()
    blocked = guard.update([100.0, 200.0, 300.0, 400.0, 500.0], timestamp=10.0)
    assert not blocked
    assert not guard.is_blocked()
    assert guard.block_reason == "INITIALIZING"


def test_calm_stable_depth_no_block():
    guard = Wave464OrderbookLiquidityDrainVelocityGuard()
    guard.update([100.0, 200.0, 300.0, 400.0, 500.0], timestamp=10.0)

    # Stable or increasing depth (no evacuation)
    blocked = guard.update([105.0, 210.0, 305.0, 410.0, 515.0], timestamp=10.5)
    assert not blocked
    assert not guard.is_blocked()
    assert guard.drain_velocity == 0.0
    assert guard.block_reason == ""


def test_flash_liquidity_evacuation_block():
    guard = Wave464OrderbookLiquidityDrainVelocityGuard(max_drain_velocity=2.20)
    # Seed baseline depth
    guard.update([100.0, 100.0, 100.0, 100.0, 100.0], timestamp=10.0)

    # Massive flash drainage across all tiers in dt = 0.1s
    # Depths collapse to [10, 10, 10, 10, 10]
    # Evacuation = 90 across all levels
    # raw_drain = 90 / 0.1 = 900 /s
    # norm_drain = 900 / 100 = 9.0 /s >> 2.20 /s
    blocked = guard.update([10.0, 10.0, 10.0, 10.0, 10.0], timestamp=10.1)

    assert blocked
    assert guard.is_blocked()
    assert guard.is_entry_blocked("BUY")
    assert guard.is_entry_blocked("SELL")
    assert "FLASH_LIQUIDITY_EVACUATION" in guard.block_reason
    assert guard.drain_velocity > 2.20


def test_exponential_drain_acceleration_block():
    guard = Wave464OrderbookLiquidityDrainVelocityGuard(
        max_drain_velocity=10.0, # High so velocity ceiling doesn't mask acceleration check
        max_drain_acceleration=3.50
    )
    # Step 1: Baseline
    guard.update([100.0, 100.0, 100.0, 100.0, 100.0], timestamp=10.0)

    # Step 2: Calm update (velocity ~ 0.0)
    guard.update([100.0, 100.0, 100.0, 100.0, 100.0], timestamp=10.5)

    # Step 3: Sudden jump in drainage in dt = 0.2s
    # Drop by 30 units: norm drain ~ (30 / 0.2) / 100 = 1.5/s > 1.20/s
    # Accel = (1.5 - 0.0) / 0.2 = 7.5 /s^2 > 3.50 /s^2
    blocked = guard.update([70.0, 70.0, 70.0, 70.0, 70.0], timestamp=10.7)

    assert blocked
    assert guard.is_blocked()
    assert "EXPONENTIAL_DRAIN_ACCELERATION" in guard.block_reason
    assert guard.drain_acceleration > 3.50
    assert guard.drain_velocity > 1.20


def test_cooldown_period_enforcement():
    guard = Wave464OrderbookLiquidityDrainVelocityGuard(cooldown_sec=2.0)
    guard.update([100.0, 100.0, 100.0, 100.0, 100.0], timestamp=10.0)
    guard.update([10.0, 10.0, 10.0, 10.0, 10.0], timestamp=10.1)
    assert guard.is_blocked()

    # Next update within cooldown (0.5s < 2.0s cooldown) with calm replenishing book
    blocked_in_cooldown = guard.update([500.0, 500.0, 500.0, 500.0, 500.0], timestamp=10.6)
    assert blocked_in_cooldown
    assert guard.is_blocked()


def test_telemetry_dictionary_structure():
    guard = Wave464OrderbookLiquidityDrainVelocityGuard()
    guard.update([100.0, 200.0, 300.0, 400.0, 500.0], timestamp=10.0)
    guard.update([95.0, 190.0, 285.0, 380.0, 475.0], timestamp=10.2)

    telem = guard.get_telemetry()
    assert telem["guard"] == "Wave464OrderbookLiquidityDrainVelocityGuard"
    assert "drain_velocity" in telem
    assert "drain_acceleration" in telem
    assert "tier_drain_rates" in telem
    assert len(telem["tier_drain_rates"]) == 5
    assert telem["max_drain_velocity"] == 2.20
    assert telem["max_drain_acceleration"] == 3.50
    assert isinstance(telem["is_blocked"], bool)


def test_reset_functionality():
    guard = Wave464OrderbookLiquidityDrainVelocityGuard()
    guard.update([100.0, 100.0, 100.0, 100.0, 100.0], timestamp=10.0)
    guard.update([10.0, 10.0, 10.0, 10.0, 10.0], timestamp=10.1)
    assert guard.is_blocked()

    guard.reset()
    assert not guard.is_blocked()
    assert guard._prev_depths is None
    assert guard.drain_velocity == 0.0
    assert guard.drain_acceleration == 0.0
    assert guard.tier_drain_rates == [0.0] * 5
    assert guard.block_reason == ""
    assert guard._last_breach_time == -1.0
