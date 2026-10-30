"""
Unit Test Suite for Wave 462: High-Frequency Latency Jitter Toxic Spillover Guard
"""

import pytest
from wave462_latency_jitter_toxic_spillover_guard import Wave462LatencyJitterToxicSpilloverGuard


def test_initialization_defaults_and_validation():
    guard = Wave462LatencyJitterToxicSpilloverGuard()
    assert guard.window_size == 25
    assert guard.max_jitter_cv == 0.80
    assert guard.min_jitter_ms == 4.0
    assert guard.max_tail_z == 5.00
    assert guard.max_mean_latency_ms == 25.0
    assert guard.min_samples == 10
    assert guard.cooldown_sec == 2.0
    assert not guard.is_blocked()

    with pytest.raises(ValueError, match="window_size"):
        Wave462LatencyJitterToxicSpilloverGuard(window_size=8)
    with pytest.raises(ValueError, match="max_jitter_cv"):
        Wave462LatencyJitterToxicSpilloverGuard(max_jitter_cv=0.10)
    with pytest.raises(ValueError, match="min_jitter_ms"):
        Wave462LatencyJitterToxicSpilloverGuard(min_jitter_ms=0.2)
    with pytest.raises(ValueError, match="max_tail_z"):
        Wave462LatencyJitterToxicSpilloverGuard(max_tail_z=1.5)
    with pytest.raises(ValueError, match="max_mean_latency_ms"):
        Wave462LatencyJitterToxicSpilloverGuard(max_mean_latency_ms=1.0)
    with pytest.raises(ValueError, match="min_samples"):
        Wave462LatencyJitterToxicSpilloverGuard(min_samples=4)
    with pytest.raises(ValueError, match="cooldown_sec"):
        Wave462LatencyJitterToxicSpilloverGuard(cooldown_sec=0.05)


def test_input_validation_and_monotonicity():
    guard = Wave462LatencyJitterToxicSpilloverGuard()

    # Negative latency
    with pytest.raises(ValueError, match="non-negative"):
        guard.update(latency_ms=-1.0, timestamp=1.0)

    # Monotonic timestamps
    guard.update(latency_ms=2.0, timestamp=10.0)
    with pytest.raises(ValueError, match="strictly monotonic"):
        guard.update(latency_ms=2.5, timestamp=10.0)
    with pytest.raises(ValueError, match="strictly monotonic"):
        guard.update(latency_ms=2.5, timestamp=9.0)


def test_insufficient_samples_state():
    guard = Wave462LatencyJitterToxicSpilloverGuard(min_samples=10)
    for i in range(9):
        blocked = guard.update(latency_ms=2.0, timestamp=10.0 + i * 0.1)
        assert not blocked
        assert not guard.is_blocked()
        assert guard.block_reason == "INSUFFICIENT_SAMPLES"


def test_deterministic_low_latency_no_block():
    guard = Wave462LatencyJitterToxicSpilloverGuard(min_samples=10)
    t = 10.0
    for i in range(20):
        t += 0.05
        # Tight, stable 1.8 - 2.2 ms latency
        lat = 2.0 + 0.1 * ((i % 3) - 1)
        blocked = guard.update(latency_ms=lat, timestamp=t)

    assert not blocked
    assert not guard.is_blocked()
    assert guard.mean_latency_ms < 5.0
    assert guard.jitter_cv < 0.20
    assert guard.block_reason == ""


def test_hard_latency_ceiling_breach_block():
    guard = Wave462LatencyJitterToxicSpilloverGuard(
        min_samples=10,
        max_mean_latency_ms=25.0
    )
    t = 100.0
    for i in range(15):
        t += 0.05
        # Server congestion: high steady latency around 32 ms > 25 ms
        blocked = guard.update(latency_ms=32.0, timestamp=t)

    assert blocked
    assert guard.is_blocked()
    assert guard.is_entry_blocked("BUY")
    assert guard.is_entry_blocked("SELL")
    assert "LATENCY_CEILING_BREACH" in guard.block_reason
    assert guard.mean_latency_ms > 25.0


def test_packet_dispersion_tail_spike_block():
    guard = Wave462LatencyJitterToxicSpilloverGuard(
        min_samples=10,
        max_tail_z=5.0,
        max_mean_latency_ms=50.0  # High so ceiling breach doesn't mask tail spike
    )
    t = 200.0
    # 15 ultra-stable packets at 1.0ms
    for i in range(15):
        t += 0.02
        guard.update(latency_ms=1.0, timestamp=t)

    # 1 massive outlier packet (e.g. 45.0 ms queue hang)
    t += 0.02
    blocked = guard.update(latency_ms=45.0, timestamp=t)

    assert blocked
    assert guard.is_blocked()
    assert "PACKET_DISPERSION_SPIKE" in guard.block_reason
    assert guard.tail_z_score > 5.0


def test_latency_jitter_explosion_block():
    guard = Wave462LatencyJitterToxicSpilloverGuard(
        min_samples=10,
        max_jitter_cv=0.80,
        min_jitter_ms=4.0,
        max_mean_latency_ms=50.0,
        max_tail_z=10.0  # High so tail spike doesn't mask jitter burst
    )
    t = 300.0
    # Alternating packet jitter between 1.0 ms and 18.0 ms
    # Mean ~ 9.5 ms, std ~ 8.5 ms, CV ~ 8.5 / 9.5 = 0.89 > 0.80 and std > 4.0 ms
    for i in range(20):
        t += 0.02
        lat = 1.0 if i % 2 == 0 else 18.0
        guard.update(latency_ms=lat, timestamp=t)

    assert guard.is_blocked()
    assert "LATENCY_JITTER_EXPLOSION" in guard.block_reason
    assert guard.jitter_cv > 0.80
    assert guard.latency_std_ms > 4.0


def test_cooldown_period_enforcement():
    guard = Wave462LatencyJitterToxicSpilloverGuard(
        min_samples=10,
        cooldown_sec=2.0
    )
    t = 400.0
    for i in range(15):
        t += 0.05
        guard.update(latency_ms=35.0, timestamp=t)

    assert guard.is_blocked()

    # Next update within cooldown (0.5s < 2.0s cooldown) with calm 1.0ms latency
    t += 0.5
    blocked_in_cooldown = guard.update(latency_ms=1.0, timestamp=t)
    assert blocked_in_cooldown
    assert guard.is_blocked()


def test_telemetry_dictionary_structure():
    guard = Wave462LatencyJitterToxicSpilloverGuard()
    t = 500.0
    for i in range(15):
        t += 0.05
        guard.update(latency_ms=3.0, timestamp=t)

    telem = guard.get_telemetry()
    assert telem["guard"] == "Wave462LatencyJitterToxicSpilloverGuard"
    assert "mean_latency_ms" in telem
    assert "latency_std_ms" in telem
    assert "jitter_cv" in telem
    assert "tail_z_score" in telem
    assert telem["max_mean_latency_ms"] == 25.0
    assert isinstance(telem["is_blocked"], bool)
    assert telem["sample_size"] == 15


def test_reset_functionality():
    guard = Wave462LatencyJitterToxicSpilloverGuard()
    t = 600.0
    for i in range(15):
        t += 0.05
        guard.update(latency_ms=40.0, timestamp=t)

    assert guard.is_blocked()

    guard.reset()
    assert not guard.is_blocked()
    assert guard.mean_latency_ms == 0.0
    assert guard.latency_std_ms == 0.0
    assert guard.jitter_cv == 0.0
    assert guard.tail_z_score == 0.0
    assert guard.block_reason == ""
    assert guard._last_breach_time == -1.0
