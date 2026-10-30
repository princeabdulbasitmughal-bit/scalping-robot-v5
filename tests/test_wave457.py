"""
Unit Test Suite for Wave 457: Cross-Venue Order Flow Toxicity Kyle's Lambda Guard
"""

import pytest
import numpy as np
from wave457_cross_venue_kyle_lambda_guard import Wave457CrossVenueKyleLambdaGuard


def test_initialization_defaults_and_validation():
    guard = Wave457CrossVenueKyleLambdaGuard()
    assert guard.window_size == 20
    assert guard.max_divergence_ratio == 0.70
    assert guard.toxic_lambda_threshold == 0.02
    assert guard.max_impact_ratio == 3.0
    assert not guard.is_blocked()

    with pytest.raises(ValueError, match="window_size"):
        Wave457CrossVenueKyleLambdaGuard(window_size=5)
    with pytest.raises(ValueError, match="max_divergence_ratio"):
        Wave457CrossVenueKyleLambdaGuard(max_divergence_ratio=0.10)
    with pytest.raises(ValueError, match="toxic_lambda_threshold"):
        Wave457CrossVenueKyleLambdaGuard(toxic_lambda_threshold=-0.01)
    with pytest.raises(ValueError, match="max_impact_ratio"):
        Wave457CrossVenueKyleLambdaGuard(max_impact_ratio=0.5)


def test_insufficient_samples_does_not_block():
    guard = Wave457CrossVenueKyleLambdaGuard(min_samples=10)
    t = 100.0
    for _ in range(6):
        t += 0.5
        blocked = guard.update(0.01, 10.0, 0.01, 10.0, timestamp=t)
        assert not blocked
        assert guard.block_reason == "INSUFFICIENT_SAMPLES"


def test_monotonic_timestamp_and_finite_validation():
    guard = Wave457CrossVenueKyleLambdaGuard()
    guard.update(0.01, 1.0, 0.01, 1.0, timestamp=10.0)
    with pytest.raises(ValueError, match="strictly monotonic"):
        guard.update(0.01, 1.0, 0.01, 1.0, timestamp=10.0)
    with pytest.raises(ValueError, match="strictly monotonic"):
        guard.update(0.01, 1.0, 0.01, 1.0, timestamp=9.0)
    with pytest.raises(ValueError, match="must be finite"):
        guard.update(float("nan"), 1.0, 0.01, 1.0, timestamp=11.0)


def test_symmetric_balanced_flows_no_block():
    guard = Wave457CrossVenueKyleLambdaGuard(min_samples=10)
    np.random.seed(42)
    # Both venues experience identical proportional price impact
    t = 10.0
    for _ in range(15):
        t += 0.2
        q = float(np.random.normal(0, 5.0))
        dp = 0.005 * q + float(np.random.normal(0, 0.001))
        guard.update(dp, q, dp, q, timestamp=t)

    assert not guard.is_blocked()
    assert guard.divergence_ratio < 0.20
    assert guard.block_reason == ""


def test_toxic_buy_divergence_blocks_buy_entry():
    guard = Wave457CrossVenueKyleLambdaGuard(
        toxic_lambda_threshold=0.015,
        max_divergence_ratio=0.60,
        max_impact_ratio=2.5,
        min_samples=10,
        cooldown_sec=1.0
    )
    # Venue A has huge price impact from aggressive buying (lambda ~ 0.030)
    # Venue B has zero/stale price impact (lambda ~ 0.001)
    t = 50.0
    for i in range(12):
        t += 0.1
        q_a = 10.0 + (i % 3)
        dp_a = 0.035 * q_a
        q_b = 10.0 + (i % 3)
        dp_b = 0.001 * q_b
        guard.update(dp_a, q_a, dp_b, q_b, timestamp=t)

    assert guard.is_blocked()
    assert guard.blocked_side == "BUY"
    assert guard.is_entry_blocked("BUY")
    assert not guard.is_entry_blocked("SELL")
    assert "TOXIC_KYLE_LAMBDA_DIVERGENCE" in guard.block_reason


def test_toxic_sell_divergence_blocks_sell_entry():
    guard = Wave457CrossVenueKyleLambdaGuard(
        toxic_lambda_threshold=0.015,
        max_divergence_ratio=0.60,
        max_impact_ratio=2.5,
        min_samples=10,
        cooldown_sec=1.0
    )
    # Venue A has huge downward price impact from aggressive selling (flow < 0)
    t = 50.0
    for i in range(12):
        t += 0.1
        q_a = -10.0 - (i % 3)
        dp_a = 0.035 * q_a
        q_b = -10.0 - (i % 3)
        dp_b = 0.001 * q_b
        guard.update(dp_a, q_a, dp_b, q_b, timestamp=t)

    assert guard.is_blocked()
    assert guard.blocked_side == "SELL"
    assert guard.is_entry_blocked("SELL")
    assert not guard.is_entry_blocked("BUY")


def test_cooldown_period_enforcement():
    guard = Wave457CrossVenueKyleLambdaGuard(
        toxic_lambda_threshold=0.015,
        max_divergence_ratio=0.60,
        min_samples=10,
        cooldown_sec=2.0
    )
    t = 10.0
    for i in range(12):
        t += 0.1
        q_a = 10.0 + (i % 3)
        dp_a = 0.035 * q_a
        q_b = 10.0 + (i % 3)
        dp_b = 0.001 * q_b
        guard.update(dp_a, q_a, dp_b, q_b, timestamp=t)
    assert guard.is_blocked()

    # Next tick during cooldown (dt = 0.5s < 2.0s cooldown)
    t += 0.5
    blocked_during_cooldown = guard.update(0.001, 1.0, 0.001, 1.0, timestamp=t)
    assert blocked_during_cooldown
    assert guard.is_blocked()


def test_telemetry_dictionary_structure():
    guard = Wave457CrossVenueKyleLambdaGuard()
    t = 10.0
    for _ in range(12):
        t += 0.1
        guard.update(0.01, 2.0, 0.01, 2.0, timestamp=t)

    telem = guard.get_telemetry()
    assert telem["guard"] == "Wave457CrossVenueKyleLambdaGuard"
    assert "lambda_a" in telem
    assert "lambda_b" in telem
    assert "divergence_ratio" in telem
    assert "impact_ratio" in telem
    assert telem["sample_size"] == 12


def test_reset_functionality():
    guard = Wave457CrossVenueKyleLambdaGuard(
        toxic_lambda_threshold=0.015,
        max_divergence_ratio=0.60,
        min_samples=10
    )
    t = 10.0
    for i in range(12):
        t += 0.1
        q_a = 10.0 + (i % 3)
        dp_a = 0.035 * q_a
        q_b = 10.0 + (i % 3)
        dp_b = 0.001 * q_b
        guard.update(dp_a, q_a, dp_b, q_b, timestamp=t)
    assert guard.is_blocked()

    guard.reset()
    assert not guard.is_blocked()
    assert len(guard._dp_a) == 0
    assert guard.lambda_a == 0.0
    assert guard.block_reason == ""
    assert guard.blocked_side is None
