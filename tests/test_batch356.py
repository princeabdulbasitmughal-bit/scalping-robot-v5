"""
Test Batch 356: Wave 461 Order Flow Entropy Drift & Wave 462 Latency Jitter Spillover Guard
=============================================================================================
Institutional unit test suite verifying Shannon/Rényi information entropy collapse,
execution round-trip latency jitter, and packet dispersion toxic spillover circuit breakers.
"""

import pytest
import math
import numpy as np
from wave461_order_flow_entropy_drift_guard import Wave461OrderFlowEntropyDriftGuard
from wave462_latency_jitter_toxic_spillover_guard import Wave462LatencyJitterToxicSpilloverGuard


class TestWave461OrderFlowEntropyDriftGuard:
    """Test suite for Wave 461: Shannon-Rényi Order Flow Entropy Drift Guard."""

    def test_init_validation(self):
        with pytest.raises(ValueError, match="window_size must be >= 15"):
            Wave461OrderFlowEntropyDriftGuard(window_size=10)

        with pytest.raises(ValueError, match="min_entropy_threshold must be in"):
            Wave461OrderFlowEntropyDriftGuard(min_entropy_threshold=0.10)
        with pytest.raises(ValueError, match="min_entropy_threshold must be in"):
            Wave461OrderFlowEntropyDriftGuard(min_entropy_threshold=0.90)

        with pytest.raises(ValueError, match="max_concentration_threshold must be in"):
            Wave461OrderFlowEntropyDriftGuard(max_concentration_threshold=0.30)

        with pytest.raises(ValueError, match="max_entropy_drift_rate must be > 0.05"):
            Wave461OrderFlowEntropyDriftGuard(max_entropy_drift_rate=0.01)

        with pytest.raises(ValueError, match="min_samples must be >= 10"):
            Wave461OrderFlowEntropyDriftGuard(min_samples=5)

        with pytest.raises(ValueError, match="cooldown_sec must be >= 0.1"):
            Wave461OrderFlowEntropyDriftGuard(cooldown_sec=0.05)

    def test_insufficient_samples(self):
        guard = Wave461OrderFlowEntropyDriftGuard(min_samples=12)
        for i in range(8):
            blocked = guard.update(1, timestamp=10.0 + i)
            assert not blocked
            assert not guard.is_blocked()
            assert guard.block_reason == "INSUFFICIENT_SAMPLES"

    def test_calm_uniform_order_flow_no_block(self):
        guard = Wave461OrderFlowEntropyDriftGuard(min_samples=12, min_entropy_threshold=0.45)

        # Uniform sequence across all 6 order book event types
        for i in range(30):
            ev = (i % 6) + 1
            guard.update(ev, timestamp=100.0 + i * 0.1)

        assert not guard.is_blocked()
        assert not guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert guard.shannon_entropy_norm > 0.90
        assert guard.renyi_entropy_norm > 0.90
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave461OrderFlowEntropyDriftGuard"

    def test_deterministic_buy_sweep_triggers_block(self):
        guard = Wave461OrderFlowEntropyDriftGuard(
            min_samples=10,
            min_entropy_threshold=0.45,
            max_concentration_threshold=0.60
        )

        # Pre-populate with slight diversity
        for i in range(5):
            guard.update((i % 4) + 1, timestamp=100.0 + i * 0.1)

        # Massive deterministic cluster of aggressive market buys (event_type = 1)
        for i in range(5, 25):
            guard.update(1, timestamp=100.0 + i * 0.1)

        assert guard.is_blocked()
        assert guard.blocked_side == "BUY"
        assert guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert "ENTROPY_COLLAPSE" in guard.block_reason

    def test_deterministic_sell_sweep_triggers_block(self):
        guard = Wave461OrderFlowEntropyDriftGuard(
            min_samples=10,
            min_entropy_threshold=0.45,
            max_concentration_threshold=0.60
        )

        # Aggressive market sell orders dominate (event_type = 2)
        for i in range(20):
            guard.update(2, timestamp=200.0 + i * 0.1)

        assert guard.is_blocked()
        assert guard.blocked_side == "SELL"
        assert guard.is_entry_blocked("SELL")
        assert not guard.is_entry_blocked("BUY")

    def test_cooldown_and_reset(self):
        guard = Wave461OrderFlowEntropyDriftGuard(
            min_samples=10,
            min_entropy_threshold=0.45,
            cooldown_sec=2.0
        )
        for i in range(15):
            guard.update(1, timestamp=10.0 + i * 0.1)
        assert guard.is_blocked()

        # Update within cooldown
        blocked = guard.update(3, timestamp=10.0 + 1.5 + 0.5)
        assert blocked
        assert guard.is_blocked()

        # Reset
        guard.reset()
        assert not guard.is_blocked()
        assert guard.shannon_entropy_norm == 1.0
        assert guard.blocked_side is None

    def test_input_validation(self):
        guard = Wave461OrderFlowEntropyDriftGuard()
        with pytest.raises(ValueError, match="event_type must be in range"):
            guard.update(0, timestamp=10.0)
        with pytest.raises(ValueError, match="event_type must be in range"):
            guard.update(7, timestamp=10.0)

        with pytest.raises(ValueError, match="timestamp must be strictly monotonic"):
            guard.update(1, timestamp=10.0)
            guard.update(1, timestamp=10.0)


class TestWave462LatencyJitterToxicSpilloverGuard:
    """Test suite for Wave 462: High-Frequency Latency Jitter Toxic Spillover Guard."""

    def test_init_validation(self):
        with pytest.raises(ValueError, match="window_size must be >= 12"):
            Wave462LatencyJitterToxicSpilloverGuard(window_size=8)

        with pytest.raises(ValueError, match="max_jitter_cv must be in"):
            Wave462LatencyJitterToxicSpilloverGuard(max_jitter_cv=0.20)

        with pytest.raises(ValueError, match="min_jitter_ms must be > 0.5"):
            Wave462LatencyJitterToxicSpilloverGuard(min_jitter_ms=0.2)

        with pytest.raises(ValueError, match="max_tail_z must be > 2.0"):
            Wave462LatencyJitterToxicSpilloverGuard(max_tail_z=1.5)

        with pytest.raises(ValueError, match="max_mean_latency_ms must be > 2.0"):
            Wave462LatencyJitterToxicSpilloverGuard(max_mean_latency_ms=1.0)

        with pytest.raises(ValueError, match="min_samples must be >= 8"):
            Wave462LatencyJitterToxicSpilloverGuard(min_samples=4)

        with pytest.raises(ValueError, match="cooldown_sec must be >= 0.1"):
            Wave462LatencyJitterToxicSpilloverGuard(cooldown_sec=0.05)

    def test_calm_low_jitter_no_block(self):
        guard = Wave462LatencyJitterToxicSpilloverGuard(min_samples=10, max_jitter_cv=1.80)

        # Consistent sub-millisecond execution: ~0.8 ms
        for i in range(15):
            lat = 0.80 + (i % 3) * 0.05
            guard.update(lat, timestamp=100.0 + i)

        assert not guard.is_blocked()
        assert not guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert guard.jitter_cv < 0.30
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave462LatencyJitterToxicSpilloverGuard"

    def test_jitter_burst_triggers_block(self):
        guard = Wave462LatencyJitterToxicSpilloverGuard(
            min_samples=10,
            max_jitter_cv=0.80,
            min_jitter_ms=4.0
        )

        # High continuous bimodal jitter: alternating between 2.0ms and 22.0ms
        for i in range(16):
            lat = 2.0 if i % 2 == 0 else 22.0
            guard.update(lat, timestamp=100.0 + i)

        assert guard.is_blocked()
        assert guard.is_entry_blocked("BUY")
        assert guard.is_entry_blocked("SELL")
        assert "LATENCY_JITTER_EXPLOSION" in guard.block_reason

    def test_tail_packet_dispersion_spike(self):
        guard = Wave462LatencyJitterToxicSpilloverGuard(
            min_samples=10,
            max_tail_z=4.0
        )

        # 14 normal samples at 1.0 ms
        for i in range(14):
            guard.update(1.0 + (i % 2) * 0.1, timestamp=100.0 + i)

        # Sudden massive 45ms outlier packet hang
        blocked = guard.update(45.0, timestamp=115.0)
        assert blocked
        assert guard.is_blocked()
        assert "PACKET_DISPERSION_SPIKE" in guard.block_reason

    def test_hard_latency_ceiling_breach(self):
        guard = Wave462LatencyJitterToxicSpilloverGuard(
            min_samples=10,
            max_mean_latency_ms=20.0
        )

        # Sustained elevated network latency at 28ms
        for i in range(12):
            guard.update(28.0, timestamp=100.0 + i)

        assert guard.is_blocked()
        assert "LATENCY_CEILING_BREACH" in guard.block_reason

    def test_cooldown_and_reset(self):
        guard = Wave462LatencyJitterToxicSpilloverGuard(min_samples=8, max_mean_latency_ms=10.0, cooldown_sec=2.0)
        for i in range(10):
            guard.update(25.0, timestamp=10.0 + i)
        assert guard.is_blocked()

        # Update within cooldown
        blocked = guard.update(1.0, timestamp=20.5)
        assert blocked
        assert guard.is_blocked()

        # Reset
        guard.reset()
        assert not guard.is_blocked()
        assert guard.mean_latency_ms == 0.0
        assert guard.block_reason == ""

    def test_input_validation(self):
        guard = Wave462LatencyJitterToxicSpilloverGuard()
        with pytest.raises(ValueError, match="latency_ms must be non-negative"):
            guard.update(-1.0, timestamp=10.0)

        with pytest.raises(ValueError, match="timestamp must be strictly monotonic"):
            guard.update(1.0, timestamp=10.0)
            guard.update(1.0, timestamp=10.0)
