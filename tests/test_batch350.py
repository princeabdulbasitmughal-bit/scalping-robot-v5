"""
Test Batch 350: Wave 448 Cross-Impact, Wave 449 Liquidity Black Hole & Wave 450 Apex Master Synthesizer
========================================================================================================
Institutional unit test suite verifying cross-asset order flow contagion, liquidity black hole
event horizons, and the landmark Wave 450 Apex Sovereign Canopy Master Synthesizer Guard.
"""

import pytest
import math
import numpy as np
from wave448_cross_impact_propagator_guard import Wave448CrossImpactPropagatorGuard
from wave449_liquidity_black_hole_horizon_guard import Wave449LiquidityBlackHoleHorizonGuard
from wave450_apex_sovereign_canopy_master_synthesizer_guard import Wave450ApexSovereignCanopyMasterSynthesizerGuard


class TestWave448CrossImpactPropagatorGuard:
    """Test suite for Wave 448: Multi-Asset Cross-Impact Propagator Guard."""

    def test_init_invalid_params(self):
        with pytest.raises(ValueError, match="window_size must be >= 15"):
            Wave448CrossImpactPropagatorGuard(window_size=10)

        with pytest.raises(ValueError, match="max_spillover_ratio must be > 0.50"):
            Wave448CrossImpactPropagatorGuard(max_spillover_ratio=0.30)

    def test_calm_independent_flow_no_block(self):
        guard = Wave448CrossImpactPropagatorGuard(window_size=25, max_spillover_ratio=2.20, min_samples_for_ols=12)
        
        # Uncorrelated noise: Cov(r, w) ~ 0 => Lambda ~ 0
        np.random.seed(42)
        t = 100.0
        for i in range(25):
            t += 1.0
            r = float(0.0005 * np.random.randn())
            w = float(10.0 * np.random.randn())
            guard.update(r, w, t)

        assert not guard.is_blocked()
        assert not guard.is_entry_blocked("BUY")
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave448CrossImpactPropagatorGuard"
        assert telem["spillover_ratio"] < 2.20

    def test_exogenous_spillover_triggers_block(self):
        guard = Wave448CrossImpactPropagatorGuard(window_size=20, max_spillover_ratio=2.0, min_samples_for_ols=12)

        # Strongly correlated flow: r = 0.001 * w + tiny noise
        t = 100.0
        for i in range(15):
            t += 1.0
            w = float(5.0 * (i + 1))
            r = float(0.002 * w)
            guard.update(r, w, t)

        # Massive foreign shock in sister asset
        t += 1.0
        huge_w = 250.0
        huge_r = 0.002 * huge_w
        guard.update(huge_r, huge_w, t)

        assert guard.is_blocked()
        assert "EXOGENOUS_CROSS_IMPACT_SPILLOVER" in guard.block_reason
        assert guard.spillover_ratio > 2.0

    def test_validation_and_reset(self):
        guard = Wave448CrossImpactPropagatorGuard()
        with pytest.raises(ValueError, match="primary_return and correlated_order_flow must be finite"):
            guard.update(float("nan"), 10.0, 1.0)

        guard.update(0.001, 10.0, 1.0)
        with pytest.raises(ValueError, match="timestamp must be strictly monotonic"):
            guard.update(0.001, 10.0, 1.0)

        guard.reset()
        assert not guard.is_blocked()
        assert len(guard._returns) == 0


class TestWave449LiquidityBlackHoleHorizonGuard:
    """Test suite for Wave 449: Liquidity Black Hole Horizon Guard."""

    def test_init_invalid_params(self):
        with pytest.raises(ValueError, match="window_size must be >= 10"):
            Wave449LiquidityBlackHoleHorizonGuard(window_size=5)

        with pytest.raises(ValueError, match="max_depth_contraction_ratio must be in"):
            Wave449LiquidityBlackHoleHorizonGuard(max_depth_contraction_ratio=0.10)

        with pytest.raises(ValueError, match="max_evaporation_velocity must be > 0.10"):
            Wave449LiquidityBlackHoleHorizonGuard(max_evaporation_velocity=0.05)

    def test_stable_depth_no_block(self):
        guard = Wave449LiquidityBlackHoleHorizonGuard(
            window_size=20,
            max_depth_contraction_ratio=0.65,
            max_evaporation_velocity=1.50
        )

        t = 10.0
        for i in range(15):
            t += 0.5
            depth = 100.0 + (i % 3) * 5.0
            guard.update(depth, t)

        assert not guard.is_blocked()
        assert not guard.is_entry_blocked("SELL")
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave449LiquidityBlackHoleHorizonGuard"

    def test_rapid_depth_contraction_triggers_block(self):
        guard = Wave449LiquidityBlackHoleHorizonGuard(
            window_size=15,
            max_depth_contraction_ratio=0.60,
            max_evaporation_velocity=5.0
        )

        t = 10.0
        # Start at 200 depth
        guard.update(200.0, t)
        for i in range(1, 10):
            t += 1.0
            # Gradual severe contraction down to 50 (75% contraction > 60%)
            d = 200.0 - (i * 15.0)
            guard.update(d, t)

        assert guard.is_blocked()
        assert "LIQUIDITY_BLACK_HOLE_EVENT_HORIZON" in guard.block_reason
        assert abs(guard.cumulative_contraction) > 0.60

    def test_evaporation_velocity_triggers_block(self):
        guard = Wave449LiquidityBlackHoleHorizonGuard(
            window_size=15,
            max_depth_contraction_ratio=0.90,
            max_evaporation_velocity=1.50
        )

        t = 10.0
        for i in range(6):
            t += 1.0
            guard.update(100.0, t)

        # Depth drops from 100 to 20 in 0.1s -> velocity = -(20-100)/0.1 / 20 = 800/20 = 40.0 s^-1 >> 1.50!
        t += 0.1
        guard.update(20.0, t)

        assert guard.is_blocked()
        assert "CATASTROPHIC_DEPTH_EVAPORATION" in guard.block_reason
        assert guard.evaporation_velocity > 1.50

    def test_depth_floor_collapse_triggers_block(self):
        guard = Wave449LiquidityBlackHoleHorizonGuard(min_depth_floor=5.0)
        t = 1.0
        for i in range(5):
            t += 1.0
            guard.update(50.0, t)

        t += 1.0
        guard.update(1.2, t)  # Below floor of 5.0
        assert guard.is_blocked()
        assert "ABSOLUTE_LIQUIDITY_COLLAPSE" in guard.block_reason

    def test_validation_and_reset(self):
        guard = Wave449LiquidityBlackHoleHorizonGuard()
        with pytest.raises(ValueError, match="total_depth must be non-negative"):
            guard.update(-1.0, 1.0)

        guard.update(10.0, 1.0)
        with pytest.raises(ValueError, match="timestamp must be strictly monotonic"):
            guard.update(10.0, 1.0)

        guard.reset()
        assert not guard.is_blocked()
        assert len(guard._depth_history) == 0


class TestWave450ApexSovereignCanopyMasterSynthesizerGuard:
    """Test suite for Wave 450: Apex Sovereign Canopy Master Synthesizer Guard."""

    def test_init_invalid_params(self):
        with pytest.raises(ValueError, match="critical_composite_threshold must be in"):
            Wave450ApexSovereignCanopyMasterSynthesizerGuard(critical_composite_threshold=0.10)

        with pytest.raises(ValueError, match="multi_vector_trigger_count must be in"):
            Wave450ApexSovereignCanopyMasterSynthesizerGuard(multi_vector_trigger_count=1)

        with pytest.raises(ValueError, match="vector_spike_threshold must be in"):
            Wave450ApexSovereignCanopyMasterSynthesizerGuard(vector_spike_threshold=0.40)

    def test_calm_canopy_no_block(self):
        guard = Wave450ApexSovereignCanopyMasterSynthesizerGuard(critical_composite_threshold=0.65)
        
        # Nominal calm conditions across all 9 dimensions
        guard.update(
            kernel_jump=0.10,
            depth_half_life=0.15,
            lead_lag_transfer=0.10,
            impact_decay_asymmetry=0.12,
            canopy_submatrix=0.14,
            rough_hurst=0.10,
            queue_cancellation=0.20,
            cross_impact=0.15,
            black_hole_horizon=0.08,
            timestamp=100.0
        )

        assert not guard.is_blocked()
        assert not guard.is_entry_blocked("BUY")
        assert guard.composite_score < 0.25
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave450ApexSovereignCanopyMasterSynthesizerGuard"
        assert "Wave 450 Grand Apex Complete" in telem["canopy_milestone"]

    def test_composite_fragility_spike_triggers_block(self):
        guard = Wave450ApexSovereignCanopyMasterSynthesizerGuard(critical_composite_threshold=0.65)

        # High fragility across vectors -> composite exceeds 0.65
        guard.update(
            kernel_jump=0.75,
            depth_half_life=0.70,
            lead_lag_transfer=0.65,
            impact_decay_asymmetry=0.70,
            canopy_submatrix=0.72,
            rough_hurst=0.68,
            queue_cancellation=0.65,
            cross_impact=0.70,
            black_hole_horizon=0.75,
            timestamp=100.0
        )

        assert guard.is_blocked()
        assert "APEX_SOVEREIGN_CANOPY_COLLAPSE" in guard.block_reason
        assert guard.composite_score >= 0.65

    def test_multi_vector_convergence_triggers_lockout(self):
        guard = Wave450ApexSovereignCanopyMasterSynthesizerGuard(
            critical_composite_threshold=0.75,  # High linear threshold
            multi_vector_trigger_count=3,
            vector_spike_threshold=0.80
        )

        # 3 vectors spiked (> 0.80), rest very low -> linear composite is moderate (< 0.75)
        # kernel_jump (0.90), rough_hurst (0.95), black_hole_horizon (0.90)
        guard.update(
            kernel_jump=0.90,
            depth_half_life=0.10,
            lead_lag_transfer=0.10,
            impact_decay_asymmetry=0.10,
            canopy_submatrix=0.10,
            rough_hurst=0.95,
            queue_cancellation=0.10,
            cross_impact=0.10,
            black_hole_horizon=0.90,
            timestamp=100.0
        )

        assert guard.is_blocked()
        assert "MULTI_VECTOR_CONVERGENCE_BURST" in guard.block_reason
        assert "kernel_jump" in guard.block_reason
        assert "rough_hurst" in guard.block_reason
        assert "black_hole_horizon" in guard.block_reason

    def test_monotonic_timestamp_and_reset(self):
        guard = Wave450ApexSovereignCanopyMasterSynthesizerGuard()
        with pytest.raises(ValueError, match="must be non-negative and finite"):
            guard.update(
                kernel_jump=-0.1, depth_half_life=0.1, lead_lag_transfer=0.1,
                impact_decay_asymmetry=0.1, canopy_submatrix=0.1, rough_hurst=0.1,
                queue_cancellation=0.1, cross_impact=0.1, black_hole_horizon=0.1,
                timestamp=100.0
            )

        guard.update(
            kernel_jump=0.1, depth_half_life=0.1, lead_lag_transfer=0.1,
            impact_decay_asymmetry=0.1, canopy_submatrix=0.1, rough_hurst=0.1,
            queue_cancellation=0.1, cross_impact=0.1, black_hole_horizon=0.1,
            timestamp=100.0
        )

        with pytest.raises(ValueError, match="timestamp must be strictly monotonic"):
            guard.update(
                kernel_jump=0.1, depth_half_life=0.1, lead_lag_transfer=0.1,
                impact_decay_asymmetry=0.1, canopy_submatrix=0.1, rough_hurst=0.1,
                queue_cancellation=0.1, cross_impact=0.1, black_hole_horizon=0.1,
                timestamp=100.0
            )

        guard.reset()
        assert not guard.is_blocked()
        assert guard.composite_score == 0.0
