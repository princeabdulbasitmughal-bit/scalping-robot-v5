"""
Unit Test Suite for Wave 458: Multi-Tier LOB Queue Depletion Survival Analysis Guard
"""

import pytest
from wave458_queue_depletion_survival_guard import Wave458QueueDepletionSurvivalGuard


def test_initialization_defaults_and_validation():
    guard = Wave458QueueDepletionSurvivalGuard()
    assert guard.horizon_sec == 0.10
    assert guard.min_survival_prob == 0.30
    assert guard.max_top_hazard == 4.0
    assert guard.cooldown_sec == 1.5
    assert not guard.is_blocked()

    with pytest.raises(ValueError, match="horizon_sec"):
        Wave458QueueDepletionSurvivalGuard(horizon_sec=0.001)
    with pytest.raises(ValueError, match="min_survival_prob"):
        Wave458QueueDepletionSurvivalGuard(min_survival_prob=0.01)
    with pytest.raises(ValueError, match="max_top_hazard"):
        Wave458QueueDepletionSurvivalGuard(max_top_hazard=0.5)
    with pytest.raises(ValueError, match="cooldown_sec"):
        Wave458QueueDepletionSurvivalGuard(cooldown_sec=0.05)


def test_insufficient_tiers_validation():
    guard = Wave458QueueDepletionSurvivalGuard()
    with pytest.raises(ValueError, match="at least 3 tiers"):
        guard.update([100.0, 200.0], [5.0, 5.0], [1.0, 1.0], dt=0.1, timestamp=10.0)


def test_monotonic_timestamp_and_dt_validation():
    guard = Wave458QueueDepletionSurvivalGuard()
    depths = [100.0, 200.0, 300.0]
    cancels = [2.0, 4.0, 6.0]
    fills = [1.0, 2.0, 3.0]
    guard.update(depths, cancels, fills, dt=0.1, timestamp=10.0)

    with pytest.raises(ValueError, match="strictly monotonic"):
        guard.update(depths, cancels, fills, dt=0.1, timestamp=10.0)
    with pytest.raises(ValueError, match="strictly monotonic"):
        guard.update(depths, cancels, fills, dt=0.1, timestamp=9.0)
    with pytest.raises(ValueError, match="strictly positive"):
        guard.update(depths, cancels, fills, dt=-0.1, timestamp=11.0)


def test_calm_resilient_queues_no_block():
    guard = Wave458QueueDepletionSurvivalGuard()
    # High resting depth, tiny drains
    depths = [500.0, 1000.0, 2000.0]
    cancels = [1.0, 2.0, 3.0]
    fills = [0.5, 1.0, 1.5]
    blocked = guard.update(depths, cancels, fills, dt=0.5, timestamp=10.0)

    assert not blocked
    assert not guard.is_blocked()
    assert guard.composite_survival > 0.95
    assert guard.block_reason == ""


def test_top_of_book_flash_drain_hazard_block():
    guard = Wave458QueueDepletionSurvivalGuard(
        max_top_hazard=4.0,
        horizon_sec=0.10
    )
    # L1 depth is 10.0, drain is 9.0 in dt = 0.1s -> h_1 = 9.0 / (10 * 0.1) = 9.0/s > 4.0
    depths = [10.0, 500.0, 1000.0]
    cancels = [6.0, 5.0, 5.0]
    fills = [3.0, 5.0, 5.0]
    blocked = guard.update(depths, cancels, fills, dt=0.1, timestamp=10.0)

    assert blocked
    assert guard.is_blocked()
    assert guard.is_entry_blocked("BUY")
    assert guard.is_entry_blocked("SELL")
    assert "TOP_QUEUE_FLASH_DRAIN" in guard.block_reason
    assert guard.hazard_rates[0] > 4.0


def test_multi_tier_queue_evaporation_block():
    guard = Wave458QueueDepletionSurvivalGuard(
        max_top_hazard=50.0,  # high to isolate multi-tier composite survival check
        min_survival_prob=0.30,
        horizon_sec=0.10
    )
    # Huge drains across all 3 tiers causing composite survival < 0.30
    # h = drain / (depth * dt) -> set h ~ 15.0 -> S = exp(-15 * 0.1) = exp(-1.5) = 0.223 < 0.30
    depths = [20.0, 20.0, 20.0]
    cancels = [15.0, 15.0, 15.0]
    fills = [15.0, 15.0, 15.0]
    # Drain = 30, depth = 20, dt = 0.1 -> h = 30 / (20 * 0.1) = 15.0/s -> S = exp(-1.5) = 22.3%
    blocked = guard.update(depths, cancels, fills, dt=0.1, timestamp=10.0)

    assert blocked
    assert guard.is_blocked()
    assert "MULTI_TIER_QUEUE_EVAPORATION" in guard.block_reason
    assert guard.composite_survival < 0.30


def test_cooldown_period_enforcement():
    guard = Wave458QueueDepletionSurvivalGuard(
        max_top_hazard=4.0,
        cooldown_sec=2.0
    )
    # Trigger breach
    guard.update([10.0, 100.0, 100.0], [5.0, 1.0, 1.0], [5.0, 1.0, 1.0], dt=0.1, timestamp=10.0)
    assert guard.is_blocked()

    # Next update within cooldown (dt = 0.5s < 2.0s cooldown) with calm inputs
    blocked_in_cooldown = guard.update([1000.0, 1000.0, 1000.0], [0.1, 0.1, 0.1], [0.1, 0.1, 0.1], dt=0.5, timestamp=10.5)
    assert blocked_in_cooldown
    assert guard.is_blocked()


def test_telemetry_dictionary_structure():
    guard = Wave458QueueDepletionSurvivalGuard()
    depths = [100.0, 200.0, 300.0]
    cancels = [2.0, 4.0, 6.0]
    fills = [1.0, 2.0, 3.0]
    guard.update(depths, cancels, fills, dt=0.1, timestamp=10.0)

    telem = guard.get_telemetry()
    assert telem["guard"] == "Wave458QueueDepletionSurvivalGuard"
    assert "top_hazard_rate" in telem
    assert "composite_survival" in telem
    assert telem["horizon_sec"] == 0.10
    assert isinstance(telem["is_blocked"], bool)


def test_reset_functionality():
    guard = Wave458QueueDepletionSurvivalGuard(max_top_hazard=4.0)
    guard.update([10.0, 100.0, 100.0], [5.0, 1.0, 1.0], [5.0, 1.0, 1.0], dt=0.1, timestamp=10.0)
    assert guard.is_blocked()

    guard.reset()
    assert not guard.is_blocked()
    assert guard.composite_survival == 1.0
    assert guard.hazard_rates == [0.0, 0.0, 0.0]
    assert guard.block_reason == ""
    assert guard._last_breach_time == -1.0
