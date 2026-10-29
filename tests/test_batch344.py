"""
Batch 344 -- Tests for Wave 438 & Wave 439
==========================================
Wave 438: Dynamic Liquidity Resiliency & Depth Recovery Velocity Guard
Wave 439: Cross-Exchange Spread Arbitrage Divergence Sentinel

Target: 10+ tests, 100% pass rate
"""

import time
import pytest

from wave438_depth_recovery_velocity_guard import (
    Wave438DepthRecoveryVelocityGuard,
)
from wave439_cross_venue_arbitrage_divergence_guard import (
    Wave439CrossVenueArbitrageDivergenceGuard,
)


class TestWave438DepthRecoveryGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave438DepthRecoveryVelocityGuard(baseline_depth=5.0, critical_floor=10.0)
        with pytest.raises(ValueError):
            Wave438DepthRecoveryVelocityGuard(shock_depth_fraction=1.5)
        with pytest.raises(ValueError):
            Wave438DepthRecoveryVelocityGuard(min_recovery_velocity=-1.0)

    def test_healthy_depth_no_block(self):
        guard = Wave438DepthRecoveryVelocityGuard(baseline_depth=100.0)
        t0 = time.monotonic()
        # Normal steady depth around 100
        for i in range(10):
            guard.update(bid_depth=50.0, ask_depth=50.0, timestamp=t0 + i * 0.1)

        assert not guard.is_blocked()
        assert not guard.is_shock_active

    def test_fast_depth_recovery_post_sweep_no_block(self):
        guard = Wave438DepthRecoveryVelocityGuard(
            baseline_depth=100.0, shock_depth_fraction=0.40, max_recovery_timeout_sec=0.50
        )
        t0 = time.monotonic()
        # Step 1: Baseline 100
        guard.update(bid_depth=50.0, ask_depth=50.0, timestamp=t0)
        # Step 2: Sweep shock cuts depth to 50 (50 <= 60 shock threshold)
        guard.update(bid_depth=25.0, ask_depth=25.0, timestamp=t0 + 0.05)
        assert guard.is_shock_active

        # Step 3: Fast replenishment within 0.1s back to 95
        guard.update(bid_depth=47.5, ask_depth=47.5, timestamp=t0 + 0.15)

        assert not guard.is_blocked()
        assert not guard.is_shock_active

    def test_chronic_depth_recovery_failure_triggers_block(self):
        guard = Wave438DepthRecoveryVelocityGuard(
            baseline_depth=100.0, shock_depth_fraction=0.40, max_recovery_timeout_sec=0.30, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        guard.update(bid_depth=50.0, ask_depth=50.0, timestamp=t0)
        # Sweep shock cuts depth to 40
        guard.update(bid_depth=20.0, ask_depth=20.0, timestamp=t0 + 0.05)
        # Depth stays frozen at 40 past the 0.30s timeout (elapsed = 0.35s)
        guard.update(bid_depth=20.0, ask_depth=20.0, timestamp=t0 + 0.40)

        assert guard.is_blocked(t0 + 0.40)
        assert guard.last_reason == "CHRONIC_DEPTH_RECOVERY_FAILURE"

    def test_critical_floor_triggers_block(self):
        guard = Wave438DepthRecoveryVelocityGuard(critical_floor=15.0, cooldown_seconds=45.0)
        t0 = time.monotonic()
        # Depth 10 < 15.0 floor
        guard.update(bid_depth=5.0, ask_depth=5.0, timestamp=t0)

        assert guard.is_blocked(t0)
        assert guard.last_reason == "CRITICAL_BOOK_DEPLETION_LOCK"

    def test_validation_and_reset(self):
        guard = Wave438DepthRecoveryVelocityGuard()
        t0 = time.monotonic()
        guard.update(-5.0, 50.0, t0)  # negative depth
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert not guard.is_shock_active


class TestWave439CrossVenueArbitrageGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave439CrossVenueArbitrageDivergenceGuard(max_divergence_bps=0.1)
        with pytest.raises(ValueError):
            Wave439CrossVenueArbitrageDivergenceGuard(stale_feed_timeout_sec=-1.0)

    def test_tight_venue_parity_no_block(self):
        guard = Wave439CrossVenueArbitrageDivergenceGuard(max_divergence_bps=5.0)
        t0 = time.monotonic()
        # Local price 2400.0, Ref price 2400.1 -> basis = 0.1/2400 * 10000 = 0.41 bps < 5.0
        guard.update(bid=2399.9, ask=2400.1, ref_price=2400.1, timestamp=t0)

        assert not guard.is_blocked()
        assert guard.basis_divergence_bps < 1.0

    def test_cross_venue_price_divergence_spike_triggers_block(self):
        guard = Wave439CrossVenueArbitrageDivergenceGuard(
            max_divergence_bps=4.0, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Local price 2400.0, Ref price 2402.0 -> basis = 2.0/2402 * 10000 = 8.32 bps > 4.0 bps
        guard.update(bid=2399.9, ask=2400.1, ref_price=2402.0, timestamp=t0)

        assert guard.is_blocked(t0)
        assert guard.last_reason == "CROSS_VENUE_PRICE_DIVERGENCE_SPIKE"
        assert guard.basis_divergence_bps > 8.0

    def test_stale_benchmark_feed_triggers_block(self):
        guard = Wave439CrossVenueArbitrageDivergenceGuard(
            stale_feed_timeout_sec=2.0, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        guard.update(bid=2399.9, ask=2400.1, ref_price=2400.0, timestamp=t0)
        # Next update arrives after 3.5s > 2.0s timeout
        guard.update(bid=2399.9, ask=2400.1, ref_price=2400.0, timestamp=t0 + 3.5)

        assert guard.is_blocked(t0 + 3.5)
        assert guard.last_reason == "STALE_BENCHMARK_FEED_DISCONNECTION"

    def test_validation_and_reset(self):
        guard = Wave439CrossVenueArbitrageDivergenceGuard()
        t0 = time.monotonic()
        guard.update(2400.0, 2399.0, 2400.0, t0)  # bid > ask
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.basis_divergence_bps == 0.0
