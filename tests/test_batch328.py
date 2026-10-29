"""
Batch 328 -- Tests for Wave 411 & Wave 412
==========================================
Wave 411: High-Frequency Return Autocorrelation Decay Guard
Wave 412: Orderbook Multi-Level Depth Slope Elasticity Guard

Target: 10+ tests, 100% pass rate
"""

import time
import pytest

from wave411_high_frequency_return_autocorrelation_guard import (
    Wave411HighFrequencyReturnAutocorrelationGuard,
)
from wave412_orderbook_depth_slope_elasticity_guard import (
    Wave412OrderbookDepthSlopeElasticityGuard,
)


class TestWave411AutocorrelationGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave411HighFrequencyReturnAutocorrelationGuard(window_size=3)
        with pytest.raises(ValueError):
            Wave411HighFrequencyReturnAutocorrelationGuard(max_positive_autocorr=1.5)
        with pytest.raises(ValueError):
            Wave411HighFrequencyReturnAutocorrelationGuard(max_negative_autocorr=0.1)

    def test_normal_bid_ask_bounce_no_block(self):
        guard = Wave411HighFrequencyReturnAutocorrelationGuard(
            window_size=10, max_positive_autocorr=0.40, max_negative_autocorr=0.80, max_cumulative_autocorr=1.50
        )
        t0 = time.monotonic()
        # Realistic stationary microstructure path (rho_1 ~ -0.10, cum ~ 0.84)
        deltas = [0.002, 0.003, -0.001, -0.002, 0.004, 0.001, -0.003, -0.001, 0.002, 0.003, -0.002, 0.001]
        p = 100.0
        for i, d in enumerate(deltas):
            p += d
            guard.update(bid=p, ask=p + 0.05, timestamp=t0 + i * 0.1)

        assert not guard.is_blocked()
        assert -0.80 < guard.rho_1 < 0.40

    def test_positive_trending_sweep_triggers_block(self):
        guard = Wave411HighFrequencyReturnAutocorrelationGuard(
            window_size=8, max_positive_autocorr=0.35, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Persistent one-directional trend (positive autocorrelation rho_1 ~ 1.0)
        p = 100.0
        for i in range(12):
            p += 0.05
            guard.update(bid=p, ask=p + 0.02, timestamp=t0 + i * 0.1)

        assert guard.is_blocked(t0 + 1.2)
        assert guard.last_reason == "PERSISTENT_AUTOCORRELATION_SWEEP"

    def test_excess_negative_bounce_triggers_block(self):
        guard = Wave411HighFrequencyReturnAutocorrelationGuard(
            window_size=8, max_negative_autocorr=0.60, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Strictly alternating returns of exact magnitude -> rho_1 = -1.0
        p = 100.0
        for i in range(12):
            delta = 0.05 if i % 2 == 0 else -0.05
            p += delta
            guard.update(bid=p, ask=p + 0.02, timestamp=t0 + i * 0.1)

        assert guard.is_blocked(t0 + 1.2)
        assert guard.last_reason == "EXCESS_MICROSTRUCTURE_BOUNCE"

    def test_validation_and_reset(self):
        guard = Wave411HighFrequencyReturnAutocorrelationGuard(window_size=6)
        t0 = time.monotonic()
        guard.update(bid=-10.0, ask=10.0, timestamp=t0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""


class TestWave412DepthSlopeGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave412OrderbookDepthSlopeElasticityGuard(min_depth_slope=-1.0)
        with pytest.raises(ValueError):
            Wave412OrderbookDepthSlopeElasticityGuard(cooldown_seconds=-5.0)

    def test_healthy_depth_expansion_no_block(self):
        guard = Wave412OrderbookDepthSlopeElasticityGuard(min_depth_slope=5.0)
        t0 = time.monotonic()
        # Healthy book: level depth expands smoothly [10, 20, 30, 40, 50] -> slope = (100 - 20)/4 = 20 > 5
        bids = [10.0, 20.0, 30.0, 40.0, 50.0]
        asks = [10.0, 20.0, 30.0, 40.0, 50.0]
        guard.update(bids, asks, t0)

        assert not guard.is_blocked()
        assert guard.current_slope >= 15.0

    def test_flat_or_declining_depth_slope_triggers_block(self):
        guard = Wave412OrderbookDepthSlopeElasticityGuard(min_depth_slope=5.0, cooldown_seconds=30.0)
        t0 = time.monotonic()
        # Flat book: [10, 10, 10, 10, 10] -> slope = 0 < 5
        bids = [10.0, 10.0, 10.0, 10.0, 10.0]
        asks = [10.0, 10.0, 10.0, 10.0, 10.0]
        guard.update(bids, asks, t0)

        assert guard.is_blocked(t0)
        assert guard.last_reason == "ORDERBOOK_DEPTH_SLOPE_COLLAPSE"

    def test_tier_liquidity_inversion_triggers_block(self):
        guard = Wave412OrderbookDepthSlopeElasticityGuard(min_depth_slope=1.0, cooldown_seconds=30.0)
        t0 = time.monotonic()
        # Top-heavy inverted: level 1 has 100, level 2 has only 5 (5 <= 0.25 * 100)
        bids = [50.0, 2.0, 10.0, 20.0, 30.0]
        asks = [50.0, 3.0, 10.0, 20.0, 30.0]
        guard.update(bids, asks, t0)

        assert guard.is_blocked(t0)
        assert guard.last_reason == "TIER_LIQUIDITY_INVERSION"

    def test_validation_and_reset(self):
        guard = Wave412OrderbookDepthSlopeElasticityGuard()
        t0 = time.monotonic()
        guard.update([-5.0, 10.0], [5.0, 10.0], t0)  # negative depth
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""
