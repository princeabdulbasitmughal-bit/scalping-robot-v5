"""
Unit Test Suite for Wave 465: Markovian Queue Imbalance Drift & Replenishment Boundary Hazard Guard
"""

import pytest
from wave465_queue_imbalance_drift_hazard_guard import Wave465QueueImbalanceDriftHazardGuard


def test_initialization_defaults_and_validation():
    guard = Wave465QueueImbalanceDriftHazardGuard()
    assert guard.critical_imbalance == 0.85
    assert guard.max_drift_velocity == 3.00
    assert guard.min_queue_size == 5.0
    assert guard.cooldown_sec == 2.0
    assert not guard.is_blocked()

    with pytest.raises(ValueError, match="critical_imbalance"):
        Wave465QueueImbalanceDriftHazardGuard(critical_imbalance=0.30)
    with pytest.raises(ValueError, match="max_drift_velocity"):
        Wave465QueueImbalanceDriftHazardGuard(max_drift_velocity=0.20)
    with pytest.raises(ValueError, match="min_queue_size"):
        Wave465QueueImbalanceDriftHazardGuard(min_queue_size=0.5)
    with pytest.raises(ValueError, match="cooldown_sec"):
        Wave465QueueImbalanceDriftHazardGuard(cooldown_sec=0.05)


def test_input_validation_and_monotonicity():
    guard = Wave465QueueImbalanceDriftHazardGuard()

    # Negative queue sizes
    with pytest.raises(ValueError, match="non-negative"):
        guard.update(bid_queue=-5.0, ask_queue=10.0, timestamp=10.0)
    with pytest.raises(ValueError, match="non-negative"):
        guard.update(bid_queue=10.0, ask_queue=-5.0, timestamp=10.0)

    # Monotonic timestamps
    guard.update(bid_queue=50.0, ask_queue=50.0, timestamp=10.0)
    with pytest.raises(ValueError, match="strictly monotonic"):
        guard.update(bid_queue=50.0, ask_queue=50.0, timestamp=10.0)
    with pytest.raises(ValueError, match="strictly monotonic"):
        guard.update(bid_queue=50.0, ask_queue=50.0, timestamp=9.0)


def test_initialization_first_tick_no_block():
    guard = Wave465QueueImbalanceDriftHazardGuard()
    blocked = guard.update(bid_queue=50.0, ask_queue=50.0, timestamp=10.0)
    assert not blocked
    assert not guard.is_blocked()
    assert guard.block_reason == "INITIALIZING"
    assert guard.blocked_side is None


def test_balanced_symmetric_queues_no_block():
    guard = Wave465QueueImbalanceDriftHazardGuard()
    guard.update(bid_queue=100.0, ask_queue=100.0, timestamp=10.0)

    # Gentle fluctuations around parity
    blocked = guard.update(bid_queue=105.0, ask_queue=98.0, timestamp=10.5)
    assert not blocked
    assert not guard.is_blocked()
    assert abs(guard.current_imbalance) < 0.10
    assert abs(guard.drift_velocity) < 1.0
    assert guard.block_reason == ""
    assert guard.blocked_side is None


def test_rapid_queue_drift_block_sell():
    guard = Wave465QueueImbalanceDriftHazardGuard(max_drift_velocity=3.00)
    # Start balanced
    guard.update(bid_queue=100.0, ask_queue=100.0, timestamp=10.0)

    # Massive flash bid skew in dt = 0.1s
    # I_prev = 0.0 -> I_curr = (190 - 10) / 200 = 0.90
    # v_I = (0.90 - 0.0) / 0.1 = 9.0/s >> 3.0/s
    blocked = guard.update(bid_queue=190.0, ask_queue=10.0, timestamp=10.1)

    assert blocked
    assert guard.is_blocked()
    assert guard.blocked_side == "SELL"
    assert guard.is_entry_blocked("SELL")
    assert not guard.is_entry_blocked("BUY")
    assert "QUEUE_IMBALANCE_RAPID_DRIFT" in guard.block_reason
    assert guard.drift_velocity > 3.00


def test_rapid_queue_drift_block_buy():
    guard = Wave465QueueImbalanceDriftHazardGuard(max_drift_velocity=3.00)
    # Start balanced
    guard.update(bid_queue=100.0, ask_queue=100.0, timestamp=20.0)

    # Massive flash ask skew in dt = 0.1s
    # I_prev = 0.0 -> I_curr = (10 - 190) / 200 = -0.90
    # v_I = (-0.90 - 0.0) / 0.1 = -9.0/s
    blocked = guard.update(bid_queue=10.0, ask_queue=190.0, timestamp=20.1)

    assert blocked
    assert guard.is_blocked()
    assert guard.blocked_side == "BUY"
    assert guard.is_entry_blocked("BUY")
    assert not guard.is_entry_blocked("SELL")
    assert "QUEUE_IMBALANCE_RAPID_DRIFT" in guard.block_reason
    assert guard.drift_velocity < -3.00


def test_critical_boundary_exhaustion_block():
    guard = Wave465QueueImbalanceDriftHazardGuard(
        critical_imbalance=0.85,
        min_queue_size=5.0
    )
    # Step 1: Slow transition to avoid triggering rapid drift
    guard.update(bid_queue=10.0, ask_queue=90.0, timestamp=30.0)

    # Step 2: Bid queue drops to 2.0 (< 5.0 min_queue_size), ask = 98.0
    # I = (2 - 98) / 100 = -0.96 (abs > 0.85)
    blocked = guard.update(bid_queue=2.0, ask_queue=98.0, timestamp=31.0)

    assert blocked
    assert guard.is_blocked()
    assert guard.blocked_side == "BUY"
    assert guard.is_entry_blocked("BUY")
    assert not guard.is_entry_blocked("SELL")
    assert "CRITICAL_QUEUE_DEPLETION_HAZARD" in guard.block_reason
    assert guard.thin_queue_size < 5.0


def test_cooldown_period_enforcement():
    guard = Wave465QueueImbalanceDriftHazardGuard(cooldown_sec=2.0)
    guard.update(bid_queue=100.0, ask_queue=100.0, timestamp=40.0)
    guard.update(bid_queue=190.0, ask_queue=10.0, timestamp=40.1)
    assert guard.is_blocked()

    # Next update within cooldown (0.5s < 2.0s cooldown) with calm balanced book
    blocked_in_cooldown = guard.update(bid_queue=100.0, ask_queue=100.0, timestamp=40.6)
    assert blocked_in_cooldown
    assert guard.is_blocked()


def test_telemetry_dictionary_structure():
    guard = Wave465QueueImbalanceDriftHazardGuard()
    guard.update(bid_queue=100.0, ask_queue=100.0, timestamp=50.0)
    guard.update(bid_queue=110.0, ask_queue=90.0, timestamp=50.5)

    telem = guard.get_telemetry()
    assert telem["guard"] == "Wave465QueueImbalanceDriftHazardGuard"
    assert "current_imbalance" in telem
    assert "drift_velocity" in telem
    assert "thin_queue_size" in telem
    assert telem["critical_imbalance"] == 0.85
    assert telem["max_drift_velocity"] == 3.00
    assert telem["min_queue_size"] == 5.0
    assert isinstance(telem["is_blocked"], bool)


def test_reset_functionality():
    guard = Wave465QueueImbalanceDriftHazardGuard()
    guard.update(bid_queue=100.0, ask_queue=100.0, timestamp=60.0)
    guard.update(bid_queue=190.0, ask_queue=10.0, timestamp=60.1)
    assert guard.is_blocked()

    guard.reset()
    assert not guard.is_blocked()
    assert guard._prev_imbalance is None
    assert guard.current_imbalance == 0.0
    assert guard.drift_velocity == 0.0
    assert guard.thin_queue_size == 0.0
    assert guard.blocked_side is None
    assert guard.block_reason == ""
    assert guard._last_breach_time == -1.0
