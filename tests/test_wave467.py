"""
Unit Test Suite for Wave 467: Cross-Impact Propagator & Transient Market Decay Guard
"""

import pytest
import math
from wave467_cross_impact_propagator_transient_decay_guard import Wave467CrossImpactPropagatorTransientDecayGuard


def test_initialization_defaults_and_validation():
    guard = Wave467CrossImpactPropagatorTransientDecayGuard()
    assert guard.coupling_coeff == 1.0
    assert guard.decay_exponent == 0.5
    assert guard.tau_0 == 0.2
    assert guard.alpha == 0.5
    assert guard.toxic_impact_threshold == 5.0
    assert guard.emergency_impact_threshold == 15.0
    assert guard.window_sec == 10.0
    assert guard.cooldown_sec == 2.0
    assert not guard.is_blocked()

    with pytest.raises(ValueError, match="coupling_coeff"):
        Wave467CrossImpactPropagatorTransientDecayGuard(coupling_coeff=0.0)
    with pytest.raises(ValueError, match="decay_exponent"):
        Wave467CrossImpactPropagatorTransientDecayGuard(decay_exponent=0.01)
    with pytest.raises(ValueError, match="tau_0"):
        Wave467CrossImpactPropagatorTransientDecayGuard(tau_0=0.0001)
    with pytest.raises(ValueError, match="alpha"):
        Wave467CrossImpactPropagatorTransientDecayGuard(alpha=0.1)
    with pytest.raises(ValueError, match="toxic_impact_threshold"):
        Wave467CrossImpactPropagatorTransientDecayGuard(toxic_impact_threshold=0.05)
    with pytest.raises(ValueError, match="emergency_impact_threshold"):
        Wave467CrossImpactPropagatorTransientDecayGuard(toxic_impact_threshold=10.0, emergency_impact_threshold=8.0)
    with pytest.raises(ValueError, match="window_sec"):
        Wave467CrossImpactPropagatorTransientDecayGuard(window_sec=0.5)
    with pytest.raises(ValueError, match="cooldown_sec"):
        Wave467CrossImpactPropagatorTransientDecayGuard(cooldown_sec=0.05)


def test_input_validation_and_monotonicity():
    guard = Wave467CrossImpactPropagatorTransientDecayGuard()

    # Invalid trade parameters
    with pytest.raises(ValueError, match="sign"):
        guard.record_lead_trade(timestamp=10.0, sign=0, volume=100.0)
    with pytest.raises(ValueError, match="volume"):
        guard.record_lead_trade(timestamp=10.0, sign=1, volume=-5.0)

    # Monotonic timestamps on trades
    guard.record_lead_trade(timestamp=10.0, sign=1, volume=50.0)
    with pytest.raises(ValueError, match="monotonic"):
        guard.record_lead_trade(timestamp=9.0, sign=1, volume=50.0)

    # Monotonic timestamps on updates
    with pytest.raises(ValueError, match="monotonic"):
        guard.update(current_time=8.0)


def test_no_lead_trades_clean_state():
    guard = Wave467CrossImpactPropagatorTransientDecayGuard()
    blocked = guard.update(current_time=1.0)
    assert not blocked
    assert not guard.is_blocked()
    assert guard.current_cross_impact == 0.0
    assert not guard.is_entry_blocked("BUY")
    assert not guard.is_entry_blocked("SELL")
    assert guard.block_reason == ""


def test_toxic_upward_cross_impact_blocks_sell():
    guard = Wave467CrossImpactPropagatorTransientDecayGuard(
        toxic_impact_threshold=5.0,
        emergency_impact_threshold=20.0
    )
    # Heavy buyer volume on lead asset at t = 10.0:
    # 3 consecutive trades of volume 100 -> concave impact = sqrt(100) = 10 each
    guard.record_lead_trade(timestamp=10.0, sign=1, volume=100.0)
    guard.record_lead_trade(timestamp=10.1, sign=1, volume=100.0)

    # Evaluate at t = 10.15
    blocked = guard.update(current_time=10.15)
    assert blocked
    assert guard.is_blocked()
    assert guard.is_entry_blocked("SELL")
    assert not guard.is_entry_blocked("BUY")
    assert "TOXIC_UPWARD_CROSS_IMPACT" in guard.block_reason
    assert guard.current_cross_impact > 5.0


def test_toxic_downward_cross_impact_blocks_buy():
    guard = Wave467CrossImpactPropagatorTransientDecayGuard(
        toxic_impact_threshold=5.0,
        emergency_impact_threshold=20.0
    )
    # Heavy seller volume on lead asset: sign = -1
    guard.record_lead_trade(timestamp=10.0, sign=-1, volume=100.0)
    guard.record_lead_trade(timestamp=10.05, sign=-1, volume=100.0)

    blocked = guard.update(current_time=10.1)
    assert blocked
    assert guard.is_blocked()
    assert guard.is_entry_blocked("BUY")
    assert not guard.is_entry_blocked("SELL")
    assert "TOXIC_DOWNWARD_CROSS_IMPACT" in guard.block_reason
    assert guard.current_cross_impact < -5.0


def test_emergency_cross_impact_blocks_all():
    guard = Wave467CrossImpactPropagatorTransientDecayGuard(
        toxic_impact_threshold=5.0,
        emergency_impact_threshold=15.0
    )
    # Massive cascade of trades breaching emergency threshold (15.0)
    for i in range(5):
        guard.record_lead_trade(timestamp=10.0 + i * 0.05, sign=1, volume=144.0)  # sqrt(144) = 12 each

    blocked = guard.update(current_time=10.25)
    assert blocked
    assert guard.is_blocked()
    assert guard.is_entry_blocked("BUY")
    assert guard.is_entry_blocked("SELL")
    assert "EMERGENCY_CROSS_IMPACT_SPIKE" in guard.block_reason
    assert guard.current_cross_impact > 15.0


def test_power_law_kernel_decay_over_time():
    guard = Wave467CrossImpactPropagatorTransientDecayGuard(
        decay_exponent=0.5,
        tau_0=0.1,
        toxic_impact_threshold=5.0,
        cooldown_sec=1.0
    )
    # Trade of volume 81 -> sqrt(81) = 9
    guard.record_lead_trade(timestamp=10.0, sign=1, volume=81.0)

    # Immediately at t = 10.0: tau = 0 -> kernel = (0.1 / 0.1)^0.5 = 1.0 -> impact = 9.0
    blocked_t0 = guard.update(current_time=10.0)
    assert blocked_t0
    assert guard.current_cross_impact == pytest.approx(9.0, rel=1e-3)

    # Later at t = 15.0 (after cooldown and significant decay):
    # tau = 5.0s -> kernel = (0.1 / (5.0 + 0.1))^0.5 = sqrt(0.1 / 5.1) = sqrt(0.0196) = 0.14
    # impact = 9 * 0.14 = 1.26 < 5.0
    blocked_t_late = guard.update(current_time=15.0)
    assert not blocked_t_late
    assert not guard.is_blocked()
    assert guard.current_cross_impact < 2.0


def test_sliding_window_pruning():
    guard = Wave467CrossImpactPropagatorTransientDecayGuard(window_sec=5.0)
    guard.record_lead_trade(timestamp=10.0, sign=1, volume=10.0)
    assert len(guard._lead_trades) == 1

    # Record trade at 20.0s (10s later, beyond 5s window)
    guard.record_lead_trade(timestamp=20.0, sign=-1, volume=15.0)
    assert len(guard._lead_trades) == 1
    assert guard._lead_trades[0][0] == 20.0


def test_cooldown_enforcement():
    guard = Wave467CrossImpactPropagatorTransientDecayGuard(
        toxic_impact_threshold=5.0,
        cooldown_sec=3.0
    )
    guard.record_lead_trade(timestamp=10.0, sign=1, volume=100.0)
    guard.update(current_time=10.0)
    assert guard.is_blocked()

    # Clear trades manually by resetting buffer to test pure cooldown
    guard._lead_trades.clear()

    # At t = 11.0 (cooldown is 3.0s, so until t = 13.0)
    blocked_in_cooldown = guard.update(current_time=11.0)
    assert blocked_in_cooldown
    assert guard.is_blocked()

    # At t = 13.5 (cooldown expired)
    blocked_after_cooldown = guard.update(current_time=13.5)
    assert not blocked_after_cooldown
    assert not guard.is_blocked()


def test_telemetry_and_reset():
    guard = Wave467CrossImpactPropagatorTransientDecayGuard()
    guard.record_lead_trade(timestamp=10.0, sign=1, volume=25.0)
    guard.update(current_time=10.0)

    tel = guard.get_telemetry()
    assert tel["guard"] == "Wave467CrossImpactPropagatorTransientDecayGuard"
    assert tel["current_cross_impact"] == pytest.approx(5.0, rel=1e-3)
    assert tel["active_lead_trades_count"] == 1

    guard.reset()
    assert len(guard._lead_trades) == 0
    assert guard.current_cross_impact == 0.0
    assert not guard.is_blocked()
    assert guard.block_reason == ""
