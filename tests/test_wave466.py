"""
Unit Test Suite for Wave 466: Dynamic Bid-Ask Spread Widening Velocity & Acceleration Guard
"""

import pytest
from wave466_spread_widening_velocity_acceleration_guard import Wave466SpreadWideningVelocityAccelerationGuard


def test_initialization_defaults_and_validation():
    guard = Wave466SpreadWideningVelocityAccelerationGuard()
    assert guard.baseline_spread_pips == 2.0
    assert guard.max_spread_velocity == 12.0
    assert guard.max_spread_acceleration == 25.0
    assert guard.max_absolute_spread_pips == 8.0
    assert guard.cooldown_sec == 2.0
    assert not guard.is_blocked()

    with pytest.raises(ValueError, match="baseline_spread_pips"):
        Wave466SpreadWideningVelocityAccelerationGuard(baseline_spread_pips=0.05)
    with pytest.raises(ValueError, match="max_spread_velocity"):
        Wave466SpreadWideningVelocityAccelerationGuard(max_spread_velocity=0.5)
    with pytest.raises(ValueError, match="max_spread_acceleration"):
        Wave466SpreadWideningVelocityAccelerationGuard(max_spread_acceleration=1.0)
    with pytest.raises(ValueError, match="max_absolute_spread_pips"):
        Wave466SpreadWideningVelocityAccelerationGuard(baseline_spread_pips=5.0, max_absolute_spread_pips=4.0)
    with pytest.raises(ValueError, match="cooldown_sec"):
        Wave466SpreadWideningVelocityAccelerationGuard(cooldown_sec=0.05)


def test_input_validation_and_monotonicity():
    guard = Wave466SpreadWideningVelocityAccelerationGuard()

    # Negative spread
    with pytest.raises(ValueError, match="non-negative"):
        guard.update(spread_pips=-1.0, timestamp=10.0)

    # Monotonic timestamps
    guard.update(spread_pips=2.0, timestamp=10.0)
    with pytest.raises(ValueError, match="strictly monotonic"):
        guard.update(spread_pips=2.0, timestamp=10.0)
    with pytest.raises(ValueError, match="strictly monotonic"):
        guard.update(spread_pips=2.0, timestamp=9.0)


def test_initialization_first_tick_no_block():
    guard = Wave466SpreadWideningVelocityAccelerationGuard()
    blocked = guard.update(spread_pips=2.0, timestamp=10.0)
    assert not blocked
    assert not guard.is_blocked()
    assert guard.block_reason == "INITIALIZING"


def test_tight_stationary_spread_no_block():
    guard = Wave466SpreadWideningVelocityAccelerationGuard()
    guard.update(spread_pips=2.0, timestamp=10.0)

    # Minor calm fluctuations
    blocked = guard.update(spread_pips=2.1, timestamp=10.5)
    assert not blocked
    assert not guard.is_blocked()
    assert guard.spread_multiple < 1.20
    assert abs(guard.spread_velocity) < 1.0
    assert guard.block_reason == ""


def test_hard_spread_ceiling_breach_block():
    guard = Wave466SpreadWideningVelocityAccelerationGuard(max_absolute_spread_pips=8.0)
    # Slow drift to high spread
    guard.update(spread_pips=2.0, timestamp=10.0)
    blocked = guard.update(spread_pips=9.5, timestamp=20.0)

    assert blocked
    assert guard.is_blocked()
    assert guard.is_entry_blocked("BUY")
    assert guard.is_entry_blocked("SELL")
    assert "HARD_SPREAD_CEILING_BREACH" in guard.block_reason
    assert guard.current_spread > 8.0


def test_flash_spread_widening_velocity_block():
    guard = Wave466SpreadWideningVelocityAccelerationGuard(
        baseline_spread_pips=2.0,
        max_spread_velocity=12.0
    )
    guard.update(spread_pips=2.0, timestamp=10.0)

    # Flash widening from 2.0 to 5.5 pips in dt = 0.1s
    # v_S = (5.5 - 2.0) / 0.1 = 35.0 pips/s >> 12.0 pips/s
    # multiple = 5.5 / 2.0 = 2.75x > 2.0x
    blocked = guard.update(spread_pips=5.5, timestamp=10.1)

    assert blocked
    assert guard.is_blocked()
    assert "SPREAD_EXPLOSION_VELOCITY" in guard.block_reason
    assert guard.spread_velocity > 12.0


def test_exponential_spread_widening_acceleration_block():
    guard = Wave466SpreadWideningVelocityAccelerationGuard(
        baseline_spread_pips=2.0,
        max_spread_velocity=50.0, # High so velocity ceiling doesn't mask acceleration check
        max_spread_acceleration=25.0
    )
    # Step 1: Baseline
    guard.update(spread_pips=2.0, timestamp=10.0)
    # Step 2: Calm update (velocity ~ 0.0)
    guard.update(spread_pips=2.0, timestamp=10.5)

    # Step 3: Sudden widening jump in dt = 0.1s: from 2.0 to 4.2 pips
    # multiple = 4.2 / 2.0 = 2.1x > 1.8x
    # velocity = (4.2 - 2.0) / 0.1 = 22.0 pips/s
    # accel = (22.0 - 0.0) / 0.1 = 220.0 pips/s^2 > 25.0 pips/s^2
    blocked = guard.update(spread_pips=4.2, timestamp=10.6)

    assert blocked
    assert guard.is_blocked()
    assert "EXPONENTIAL_SPREAD_ACCELERATION" in guard.block_reason
    assert guard.spread_acceleration > 25.0


def test_cooldown_period_enforcement():
    guard = Wave466SpreadWideningVelocityAccelerationGuard(cooldown_sec=2.0)
    guard.update(spread_pips=2.0, timestamp=10.0)
    guard.update(spread_pips=9.0, timestamp=10.1)
    assert guard.is_blocked()

    # Next update within cooldown (0.5s < 2.0s cooldown) with calm 2.0 pips spread
    blocked_in_cooldown = guard.update(spread_pips=2.0, timestamp=10.6)
    assert blocked_in_cooldown
    assert guard.is_blocked()


def test_telemetry_dictionary_structure():
    guard = Wave466SpreadWideningVelocityAccelerationGuard()
    guard.update(spread_pips=2.0, timestamp=10.0)
    guard.update(spread_pips=2.5, timestamp=10.5)

    telem = guard.get_telemetry()
    assert telem["guard"] == "Wave466SpreadWideningVelocityAccelerationGuard"
    assert "current_spread" in telem
    assert "spread_velocity" in telem
    assert "spread_acceleration" in telem
    assert "spread_multiple" in telem
    assert telem["baseline_spread_pips"] == 2.0
    assert telem["max_spread_velocity"] == 12.0
    assert telem["max_spread_acceleration"] == 25.0
    assert telem["max_absolute_spread_pips"] == 8.0
    assert isinstance(telem["is_blocked"], bool)


def test_reset_functionality():
    guard = Wave466SpreadWideningVelocityAccelerationGuard()
    guard.update(spread_pips=2.0, timestamp=10.0)
    guard.update(spread_pips=9.0, timestamp=10.1)
    assert guard.is_blocked()

    guard.reset()
    assert not guard.is_blocked()
    assert guard._prev_spread is None
    assert guard.current_spread == 0.0
    assert guard.spread_velocity == 0.0
    assert guard.spread_acceleration == 0.0
    assert guard.spread_multiple == 1.0
    assert guard.block_reason == ""
    assert guard._last_breach_time == -1.0
