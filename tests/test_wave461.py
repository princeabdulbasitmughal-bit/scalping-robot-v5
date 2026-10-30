"""
Unit Test Suite for Wave 461: Shannon-Rényi Order Flow Entropy Drift Guard
"""

import pytest
from wave461_order_flow_entropy_drift_guard import Wave461OrderFlowEntropyDriftGuard


def test_initialization_defaults_and_validation():
    guard = Wave461OrderFlowEntropyDriftGuard()
    assert guard.window_size == 30
    assert guard.min_entropy_threshold == 0.45
    assert guard.max_concentration_threshold == 0.60
    assert guard.max_entropy_drift_rate == 0.30
    assert guard.min_samples == 15
    assert guard.cooldown_sec == 2.0
    assert not guard.is_blocked()

    with pytest.raises(ValueError, match="window_size"):
        Wave461OrderFlowEntropyDriftGuard(window_size=10)
    with pytest.raises(ValueError, match="min_entropy_threshold"):
        Wave461OrderFlowEntropyDriftGuard(min_entropy_threshold=0.10)
    with pytest.raises(ValueError, match="max_concentration_threshold"):
        Wave461OrderFlowEntropyDriftGuard(max_concentration_threshold=0.30)
    with pytest.raises(ValueError, match="max_entropy_drift_rate"):
        Wave461OrderFlowEntropyDriftGuard(max_entropy_drift_rate=0.01)
    with pytest.raises(ValueError, match="min_samples"):
        Wave461OrderFlowEntropyDriftGuard(min_samples=5)
    with pytest.raises(ValueError, match="cooldown_sec"):
        Wave461OrderFlowEntropyDriftGuard(cooldown_sec=0.05)


def test_input_validation_and_monotonicity():
    guard = Wave461OrderFlowEntropyDriftGuard()

    # Out of range event types
    with pytest.raises(ValueError, match="range"):
        guard.update(event_type=0, timestamp=1.0)
    with pytest.raises(ValueError, match="range"):
        guard.update(event_type=7, timestamp=1.0)
    with pytest.raises(ValueError, match="integer"):
        guard.update(event_type="1", timestamp=1.0)

    # Monotonic timestamps
    guard.update(event_type=1, timestamp=10.0)
    with pytest.raises(ValueError, match="strictly monotonic"):
        guard.update(event_type=2, timestamp=10.0)
    with pytest.raises(ValueError, match="strictly monotonic"):
        guard.update(event_type=2, timestamp=9.0)


def test_insufficient_samples_state():
    guard = Wave461OrderFlowEntropyDriftGuard(min_samples=15)
    for i in range(14):
        blocked = guard.update(event_type=(i % 6) + 1, timestamp=10.0 + i * 0.1)
        assert not blocked
        assert not guard.is_blocked()
        assert guard.block_reason == "INSUFFICIENT_SAMPLES"


def test_high_entropy_stochastic_dispersion_no_block():
    guard = Wave461OrderFlowEntropyDriftGuard(min_samples=15)
    # Balanced cycling across all 6 event types (1 to 6)
    t = 10.0
    for i in range(30):
        t += 0.1
        event = (i % 6) + 1
        blocked = guard.update(event_type=event, timestamp=t)

    assert not blocked
    assert not guard.is_blocked()
    assert guard.shannon_entropy_norm > 0.85
    assert guard.max_concentration < 0.30
    assert guard.block_reason == ""
    assert guard.blocked_side is None


def test_algorithmic_buy_sweep_entropy_collapse_block():
    guard = Wave461OrderFlowEntropyDriftGuard(min_samples=15)
    # Feed mostly Event 1 (Aggressive Market Buy)
    t = 100.0
    for i in range(25):
        t += 0.05
        # 90% Market Buys (event 1)
        event = 1 if i < 22 else 2
        guard.update(event_type=event, timestamp=t)

    assert guard.is_blocked()
    assert guard.blocked_side == "BUY"
    assert guard.is_entry_blocked("BUY")
    assert not guard.is_entry_blocked("SELL")
    assert "ENTROPY_COLLAPSE" in guard.block_reason
    assert guard.dominant_event_type == 1
    assert guard.shannon_entropy_norm < 0.45


def test_algorithmic_sell_sweep_entropy_collapse_block():
    guard = Wave461OrderFlowEntropyDriftGuard(min_samples=15)
    # Feed mostly Event 2 (Aggressive Market Sell)
    t = 200.0
    for i in range(25):
        t += 0.05
        event = 2 if i < 22 else 3
        guard.update(event_type=event, timestamp=t)

    assert guard.is_blocked()
    assert guard.blocked_side == "SELL"
    assert guard.is_entry_blocked("SELL")
    assert not guard.is_entry_blocked("BUY")
    assert "ENTROPY_COLLAPSE" in guard.block_reason
    assert guard.dominant_event_type == 2


def test_cooldown_period_enforcement():
    guard = Wave461OrderFlowEntropyDriftGuard(min_samples=15, cooldown_sec=2.0)
    # Trigger collapse
    t = 300.0
    for i in range(20):
        t += 0.02
        guard.update(event_type=1, timestamp=t)

    assert guard.is_blocked()

    # Next update within cooldown (0.5s < 2.0s cooldown) with calm dispersed input
    t += 0.5
    blocked_in_cooldown = guard.update(event_type=3, timestamp=t)
    assert blocked_in_cooldown
    assert guard.is_blocked()


def test_telemetry_dictionary_structure():
    guard = Wave461OrderFlowEntropyDriftGuard()
    t = 400.0
    for i in range(20):
        t += 0.05
        guard.update(event_type=(i % 6) + 1, timestamp=t)

    telem = guard.get_telemetry()
    assert telem["guard"] == "Wave461OrderFlowEntropyDriftGuard"
    assert "shannon_entropy_norm" in telem
    assert "renyi_entropy_norm" in telem
    assert "max_concentration" in telem
    assert "dominant_event_type" in telem
    assert "entropy_drift_rate" in telem
    assert telem["min_entropy_threshold"] == 0.45
    assert isinstance(telem["is_blocked"], bool)
    assert telem["sample_size"] == 20


def test_reset_functionality():
    guard = Wave461OrderFlowEntropyDriftGuard()
    t = 500.0
    for i in range(20):
        t += 0.02
        guard.update(event_type=1, timestamp=t)

    assert guard.is_blocked()

    guard.reset()
    assert not guard.is_blocked()
    assert guard.shannon_entropy_norm == 1.0
    assert guard.renyi_entropy_norm == 1.0
    assert guard.max_concentration == 0.0
    assert guard.dominant_event_type == 0
    assert guard.entropy_drift_rate == 0.0
    assert guard.blocked_side is None
    assert guard.block_reason == ""
    assert guard._last_breach_time == -1.0
