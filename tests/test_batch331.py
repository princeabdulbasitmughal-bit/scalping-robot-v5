"""
Batch 331 -- Tests for Wave 416 & Wave 417
==========================================
Wave 416: Queue Cancellation Ratio & Ghost Liquidity Guard
Wave 417: Trade Flow Clustered Dispersion & Burst Entropy Guard

Target: 10+ tests, 100% pass rate
"""

import time
import pytest

from wave416_queue_cancellation_ratio_guard import (
    Wave416QueueCancellationRatioGuard,
)
from wave417_trade_flow_clustered_dispersion_guard import (
    Wave417TradeFlowClusteredDispersionGuard,
)


class TestWave416CancellationRatioGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave416QueueCancellationRatioGuard(window_size=3)
        with pytest.raises(ValueError):
            Wave416QueueCancellationRatioGuard(max_cancellation_ratio=1.5)
        with pytest.raises(ValueError):
            Wave416QueueCancellationRatioGuard(min_lifetime_ms=-10.0)

    def test_balanced_fills_no_block(self):
        guard = Wave416QueueCancellationRatioGuard(
            window_size=10, max_cancellation_ratio=0.80, min_lifetime_ms=50.0
        )
        t0 = time.monotonic()
        # Normal healthy flow: alternating fills and cancels with 500ms lifetime
        for i in range(12):
            ev = "FILL" if i % 2 == 0 else "CANCEL"
            guard.update(ev, lifetime_ms=500.0, timestamp=t0 + i * 0.1)

        assert not guard.is_blocked()
        assert abs(guard.cancellation_ratio - 0.50) < 0.10

    def test_excessive_cancellation_triggers_block(self):
        guard = Wave416QueueCancellationRatioGuard(
            window_size=10, max_cancellation_ratio=0.80, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # 9 cancels out of 10 events (ratio = 90% > 80%)
        guard.update("FILL", lifetime_ms=200.0, timestamp=t0)
        for i in range(1, 10):
            guard.update("CANCEL", lifetime_ms=200.0, timestamp=t0 + i * 0.1)

        assert guard.is_blocked(t0 + 1.0)
        assert guard.last_reason == "EXCESS_QUEUE_CANCELLATION"

    def test_ghost_liquidity_submillisecond_collapse(self):
        guard = Wave416QueueCancellationRatioGuard(
            window_size=10, max_cancellation_ratio=0.90, min_lifetime_ms=100.0, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # 6 cancels out of 10 (ratio = 60% >= 50%), but lifetime is 10ms (<= 100ms)
        for i in range(10):
            ev = "CANCEL" if i % 2 == 0 else "FILL"
            guard.update(ev, lifetime_ms=10.0, timestamp=t0 + i * 0.05)

        assert guard.is_blocked(t0 + 0.5)
        assert guard.last_reason == "GHOST_LIQUIDITY_COLLAPSE"

    def test_validation_and_reset(self):
        guard = Wave416QueueCancellationRatioGuard(window_size=5)
        t0 = time.monotonic()
        guard.update("INVALID_EVENT", 100.0, t0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""


class TestWave417ClusteredDispersionGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave417TradeFlowClusteredDispersionGuard(window_size=3)
        with pytest.raises(ValueError):
            Wave417TradeFlowClusteredDispersionGuard(max_burst_dispersion=0.5)
        with pytest.raises(ValueError):
            Wave417TradeFlowClusteredDispersionGuard(min_interarrival_sec=-0.1)

    def test_homogeneous_regular_arrivals_no_block(self):
        guard = Wave417TradeFlowClusteredDispersionGuard(
            window_size=10, max_burst_dispersion=2.0
        )
        t0 = time.monotonic()
        # Constant arrivals every 0.1s -> std = 0, C_v = 0.0
        for i in range(15):
            guard.update(timestamp=t0 + i * 0.1)

        assert not guard.is_blocked()
        assert guard.dispersion_coefficient < 0.10

    def test_bursty_clustering_triggers_block(self):
        guard = Wave417TradeFlowClusteredDispersionGuard(
            window_size=10, max_burst_dispersion=2.0, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Initial timestamp
        curr = t0
        guard.update(timestamp=curr)
        # 9 ultra-fast trades (0.001s) followed by 1 long delay (5.0s) -> Cv ~ 3.15 > 2.0
        for _ in range(9):
            curr += 0.001
            guard.update(timestamp=curr)
        curr += 5.0
        guard.update(timestamp=curr)

        assert guard.is_blocked(curr)
        assert guard.last_reason == "TRADE_FLOW_BURST_CLUSTERING"
        assert guard.dispersion_coefficient >= 2.0

    def test_super_poisson_intensity_spike(self):
        guard = Wave417TradeFlowClusteredDispersionGuard(
            window_size=10, max_burst_dispersion=3.0, min_interarrival_sec=0.05, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        curr = t0
        guard.update(timestamp=curr)
        # 8 fast trades (0.001s) and 2 moderate trades (0.10s) -> mean ~ 0.021s <= 0.05s, Cv ~ 2.01 >= 1.50
        for _ in range(8):
            curr += 0.001
            guard.update(timestamp=curr)
        for _ in range(2):
            curr += 0.10
            guard.update(timestamp=curr)

        assert guard.is_blocked(curr)
        assert guard.last_reason in [
            "SUPER_POISSON_INTENSITY_SPIKE",
            "TRADE_FLOW_BURST_CLUSTERING",
        ]

    def test_validation_and_reset(self):
        guard = Wave417TradeFlowClusteredDispersionGuard(window_size=5)
        guard.update(timestamp=-5.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""
