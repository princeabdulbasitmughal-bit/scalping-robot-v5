"""
Test Batch 352: Wave 453 Orderbook Curvature Acceleration & Wave 454 Volume-Synchronized Divergence
===================================================================================================
Institutional unit test suite verifying order book depth curvature acceleration, liquidity cliffs,
and volume-synchronized cross-venue statistical arbitrage basis divergence.
"""

import pytest
import math
import numpy as np
from wave453_orderbook_curvature_acceleration_guard import Wave453OrderbookCurvatureAccelerationGuard
from wave454_volume_synchronized_divergence_guard import Wave454VolumeSynchronizedDivergenceGuard


class TestWave453OrderbookCurvatureAccelerationGuard:
    """Test suite for Wave 453: Orderbook Micro-Structural Curvature Acceleration Guard."""

    def test_init_invalid_params(self):
        with pytest.raises(ValueError, match="window_size must be >= 10"):
            Wave453OrderbookCurvatureAccelerationGuard(window_size=5)

        with pytest.raises(ValueError, match="min_kappa_floor must be negative"):
            Wave453OrderbookCurvatureAccelerationGuard(min_kappa_floor=0.5)

        with pytest.raises(ValueError, match="max_negative_acceleration must be > 0.10"):
            Wave453OrderbookCurvatureAccelerationGuard(max_negative_acceleration=0.05)

    def test_calm_convex_depth_no_block(self):
        guard = Wave453OrderbookCurvatureAccelerationGuard(
            window_size=20,
            min_kappa_floor=-1.50,
            max_negative_acceleration=2.50
        )

        # Distances: [1.0, 2.0, 3.0, 4.0] ticks
        # Convex depth: Q(x) = 10 * x + 2 * x^2 => kappa = 4.0 > 0 (solid convex cushion)
        x_tiers = [1.0, 2.0, 3.0, 4.0]
        t = 10.0

        for i in range(10):
            t += 1.0
            q_tiers = [10.0 * x + 2.0 * (x ** 2) for x in x_tiers]
            guard.update(q_tiers, x_tiers, t)

        assert not guard.is_blocked()
        assert not guard.is_entry_blocked("BUY")
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave453OrderbookCurvatureAccelerationGuard"
        assert telem["current_kappa"] > 0.0

    def test_orderbook_hollow_cliff_triggers_block(self):
        guard = Wave453OrderbookCurvatureAccelerationGuard(
            window_size=20,
            min_kappa_floor=-1.00,
            max_negative_acceleration=5.0
        )

        # Severe concave depth: Q(x) = 50 * x - 2 * x^2 => kappa = -4.0 < -1.00 (hollow cliff)
        x_tiers = [1.0, 2.0, 3.0, 4.0]
        t = 10.0
        for i in range(5):
            t += 1.0
            q_tiers = [50.0 * x - 2.0 * (x ** 2) for x in x_tiers]
            guard.update(q_tiers, x_tiers, t)

        assert guard.is_blocked()
        assert "ORDERBOOK_HOLLOW_CLIFF" in guard.block_reason
        assert guard.current_kappa < -1.00

    def test_rapid_curvature_acceleration_collapse_triggers_block(self):
        guard = Wave453OrderbookCurvatureAccelerationGuard(
            window_size=20,
            min_kappa_floor=-10.0,  # Deep floor to isolate acceleration trigger
            max_negative_acceleration=2.0  # 2.0 s^-1 acceleration threshold
        )

        x_tiers = [1.0, 2.0, 3.0, 4.0]
        t = 10.0
        # Start with convex kappa = 4.0
        for i in range(4):
            t += 1.0
            q_tiers = [10.0 * x + 2.0 * (x ** 2) for x in x_tiers]
            guard.update(q_tiers, x_tiers, t)

        # In 0.1s, kappa drops from +4.0 to -1.0 -> d_kappa = -5.0, a_kappa = -50.0 s^-1 << -2.0!
        t += 0.1
        cliff_q = [10.0 * x - 0.5 * (x ** 2) for x in x_tiers]
        guard.update(cliff_q, x_tiers, t)

        assert guard.is_blocked()
        assert "RAPID_DEPTH_CURVATURE_COLLAPSE" in guard.block_reason
        assert guard.curvature_acceleration < -2.0

    def test_validation_and_reset(self):
        guard = Wave453OrderbookCurvatureAccelerationGuard()
        with pytest.raises(ValueError, match="at least 3 levels"):
            guard.update([10.0, 20.0], [1.0, 2.0], 1.0)

        with pytest.raises(ValueError, match="must have identical length"):
            guard.update([10.0, 20.0, 30.0], [1.0, 2.0], 1.0)

        guard.update([10.0, 20.0, 30.0], [1.0, 2.0, 3.0], 1.0)
        with pytest.raises(ValueError, match="timestamp must be strictly monotonic"):
            guard.update([10.0, 20.0, 30.0], [1.0, 2.0, 3.0], 1.0)

        guard.reset()
        assert not guard.is_blocked()
        assert len(guard._kappas) == 0


class TestWave454VolumeSynchronizedDivergenceGuard:
    """Test suite for Wave 454: Volume-Synchronized Cross-Exchange Divergence Guard."""

    def test_init_invalid_params(self):
        with pytest.raises(ValueError, match="window_size must be >= 10"):
            Wave454VolumeSynchronizedDivergenceGuard(window_size=5)

        with pytest.raises(ValueError, match="max_divergence_zscore must be > 1.0"):
            Wave454VolumeSynchronizedDivergenceGuard(max_divergence_zscore=0.5)

        with pytest.raises(ValueError, match="max_basis_bps_threshold must be > 1.0"):
            Wave454VolumeSynchronizedDivergenceGuard(max_basis_bps_threshold=0.5)

    def test_synchronized_calm_basis_no_block(self):
        guard = Wave454VolumeSynchronizedDivergenceGuard(
            window_size=20,
            max_divergence_zscore=2.80,
            max_basis_bps_threshold=15.0,
            min_samples=10
        )

        # Tightly synchronized feeds with tiny noise (< 2 bps)
        t = 10.0
        np.random.seed(42)
        base_p = 2400.0
        for i in range(15):
            t += 1.0
            noise_bps = float(np.random.randn() * 0.5)
            p1 = base_p * math.exp(noise_bps / 10000.0)
            p2 = base_p
            guard.update(p1, p2, volume=10.0, timestamp=t)

        assert not guard.is_blocked()
        assert not guard.is_entry_blocked("SELL")
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave454VolumeSynchronizedDivergenceGuard"
        assert telem["divergence_zscore"] < 2.80
        assert abs(telem["current_basis_bps"]) < 15.0

    def test_absolute_basis_dislocation_triggers_block(self):
        guard = Wave454VolumeSynchronizedDivergenceGuard(
            window_size=20,
            max_divergence_zscore=5.0,
            max_basis_bps_threshold=12.0,
            min_samples=10
        )

        t = 10.0
        for i in range(12):
            t += 1.0
            guard.update(2400.0, 2400.0, volume=10.0, timestamp=t)

        # Sudden 20 bps dislocation (P1=2404.8 vs P2=2400.0 -> 20 bps > 12 bps)
        t += 1.0
        p1_dislocated = 2400.0 * math.exp(20.0 / 10000.0)
        guard.update(p1_dislocated, 2400.0, volume=15.0, timestamp=t)

        assert guard.is_blocked()
        assert "ABSOLUTE_BASIS_DISLOCATION" in guard.block_reason
        assert abs(guard.current_basis_bps) > 12.0

    def test_divergence_zscore_triggers_block(self):
        guard = Wave454VolumeSynchronizedDivergenceGuard(
            window_size=20,
            max_divergence_zscore=2.50,
            max_basis_bps_threshold=50.0,  # High bps threshold to isolate zscore trigger
            min_samples=10
        )

        # Very stable baseline with standard deviation ~ 0.2 bps
        t = 10.0
        for i in range(12):
            t += 1.0
            # 0.1 bps alternating
            bps = 0.1 if i % 2 == 0 else -0.1
            p1 = 2400.0 * math.exp(bps / 10000.0)
            guard.update(p1, 2400.0, volume=10.0, timestamp=t)

        # Sudden jump of 2.5 bps (which is ~15 sigma above the 0.15 sigma baseline, but < 50 bps)
        t += 1.0
        jump_p1 = 2400.0 * math.exp(2.5 / 10000.0)
        guard.update(jump_p1, 2400.0, volume=10.0, timestamp=t)

        assert guard.is_blocked()
        assert "CROSS_VENUE_STATISTICAL_ARBITRAGE_SHOCK" in guard.block_reason
        assert guard.divergence_zscore > 2.50

    def test_validation_and_reset(self):
        guard = Wave454VolumeSynchronizedDivergenceGuard()
        with pytest.raises(ValueError, match="primary_price must be positive"):
            guard.update(-2400.0, 2400.0, 10.0, 1.0)

        with pytest.raises(ValueError, match="volume must be positive"):
            guard.update(2400.0, 2400.0, -5.0, 1.0)

        guard.update(2400.0, 2400.0, 10.0, 1.0)
        with pytest.raises(ValueError, match="timestamp must be strictly monotonic"):
            guard.update(2400.0, 2400.0, 10.0, 1.0)

        guard.reset()
        assert not guard.is_blocked()
        assert len(guard._basis_history) == 0
