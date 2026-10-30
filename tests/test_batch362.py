"""
Test Batch 362: Wave 473 Cross-Venue Queue Guard & Wave 474 Apex Macro-Microstructure Canopy Guard
===================================================================================================
Institutional unit test suite verifying cross-venue queue imbalance divergence,
fragmentation decoupling, 5-dimensional macro-microstructure canopy synthesis, and dual-hazard spikes.
"""

import pytest
import math
import numpy as np
from wave473_cross_venue_queue_imbalance_dispersion_guard import Wave473CrossVenueQueueImbalanceDispersionGuard
from wave474_apex_macro_microstructure_canopy_synthesizer_guard import Wave474ApexMacroMicrostructureCanopySynthesizerGuard


class TestWave473CrossVenueQueueImbalanceDispersionGuard:
    """Test suite for Wave 473: Cross-Venue Queue Imbalance Dispersion Guard."""

    def test_init_validation(self):
        with pytest.raises(ValueError, match="max_divergence_threshold must be in"):
            Wave473CrossVenueQueueImbalanceDispersionGuard(max_divergence_threshold=0.50)
        with pytest.raises(ValueError, match="max_imbalance_std_threshold must be in"):
            Wave473CrossVenueQueueImbalanceDispersionGuard(max_imbalance_std_threshold=0.20)
        with pytest.raises(ValueError, match="directional_bias_threshold must be in"):
            Wave473CrossVenueQueueImbalanceDispersionGuard(directional_bias_threshold=0.10)
        with pytest.raises(ValueError, match="cooldown_sec must be >= 0.1"):
            Wave473CrossVenueQueueImbalanceDispersionGuard(cooldown_sec=0.05)

    def test_input_validation(self):
        guard = Wave473CrossVenueQueueImbalanceDispersionGuard()
        with pytest.raises(ValueError, match="must contain at least 2 venues"):
            guard.update([10.0], [10.0], timestamp=10.0)
        with pytest.raises(ValueError, match="must have equal length"):
            guard.update([10.0, 20.0], [10.0], timestamp=10.0)

    def test_calm_aligned_venues_no_block(self):
        guard = Wave473CrossVenueQueueImbalanceDispersionGuard()
        # Venues aligned: balanced depth (20 bid, 20 ask across 3 venues)
        blocked = guard.update([20.0, 25.0, 22.0], [20.0, 24.0, 23.0], timestamp=10.0)
        assert not blocked
        assert not guard.is_blocked()
        assert guard.divergence < 0.20
        assert guard.imbalance_std < 0.20
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave473CrossVenueQueueImbalanceDispersionGuard"
        assert telem["is_blocked"] is False

    def test_cross_venue_imbalance_divergence_blocks_all(self):
        guard = Wave473CrossVenueQueueImbalanceDispersionGuard(max_divergence_threshold=1.40)
        # Venue A is heavily bid-dominated: 90 bid, 10 ask -> I_A = (90-10)/100 = +0.80
        # Venue B is heavily ask-dominated: 10 bid, 90 ask -> I_B = (10-90)/100 = -0.80
        # Divergence = 0.80 - (-0.80) = 1.60 > 1.40
        blocked = guard.update([90.0, 10.0], [10.0, 90.0], timestamp=10.0)
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "ALL" # Contradictory queues indicate cross-venue latency arbitrage
        assert "CROSS_VENUE_IMBALANCE_DIVERGENCE" in guard.block_reason

    def test_cross_venue_ask_overhang_blocks_buy(self):
        guard = Wave473CrossVenueQueueImbalanceDispersionGuard(
            max_divergence_threshold=1.10,
            directional_bias_threshold=0.50
        )
        # Both venues heavily ask-dominated: Venue A (10 bid, 90 ask -> -0.80), Venue B (5 bid, 95 ask -> -0.90)
        # Divergence = 0.10, but let's test a divergence breach where mean imbalance is negative
        # Venue A: (5 bid, 95 ask -> -0.90), Venue B: (20 bid, 80 ask -> -0.60), Venue C: (10 bid, 90 ask -> -0.80)
        # mean_I = -0.767 < -0.50. Let's make divergence 1.25 > 1.10: Venue A (-0.95), Venue B (25 bid, 75 ask -> -0.50)
        # Divergence = -0.50 - (-0.95) = 0.45, so let's use:
        # Venue A (2 bid, 98 ask -> -0.96), Venue B (45 bid, 55 ask -> -0.10) -> Div = 0.86, mean = -0.53
        # With threshold 0.80:
        guard_dir = Wave473CrossVenueQueueImbalanceDispersionGuard(
            max_divergence_threshold=0.85,
            directional_bias_threshold=0.50
        )
        blocked = guard_dir.update([2.0, 45.0], [98.0, 55.0], timestamp=10.0)
        # I_1 = (2 - 98)/100 = -0.96, I_2 = (45 - 55)/100 = -0.10 -> Div = 0.86 > 0.85, mean_I = -0.53 < -0.50
        assert blocked
        assert guard_dir.is_blocked()
        assert guard_dir.blocked_side == "BUY" # Ask overhang -> buying is toxic
        assert guard_dir.is_entry_blocked("BUY")
        assert not guard_dir.is_entry_blocked("SELL")
        assert "CROSS_VENUE_ASK_OVERHANG" in guard_dir.block_reason

    def test_cross_venue_bid_overhang_blocks_sell(self):
        guard_dir = Wave473CrossVenueQueueImbalanceDispersionGuard(
            max_divergence_threshold=0.85,
            directional_bias_threshold=0.50
        )
        # I_1 = (98 - 2)/100 = +0.96, I_2 = (55 - 45)/100 = +0.10 -> Div = 0.86 > 0.85, mean_I = +0.53 > 0.50
        blocked = guard_dir.update([98.0, 55.0], [2.0, 45.0], timestamp=10.0)
        assert blocked
        assert guard_dir.is_blocked()
        assert guard_dir.blocked_side == "SELL" # Bid overhang -> selling is toxic
        assert guard_dir.is_entry_blocked("SELL")
        assert not guard_dir.is_entry_blocked("BUY")
        assert "CROSS_VENUE_BID_OVERHANG" in guard_dir.block_reason

    def test_cross_venue_imbalance_dispersion_breach(self):
        guard = Wave473CrossVenueQueueImbalanceDispersionGuard(max_imbalance_std_threshold=0.65)
        # 3 venues: I_1 = +0.90, I_2 = -0.90, I_3 = 0.0 -> std = 0.90 > 0.65
        blocked = guard.update([95.0, 5.0, 50.0], [5.0, 95.0, 50.0], timestamp=10.0)
        assert blocked
        assert guard.is_blocked()
        assert guard.imbalance_std > 0.65

    def test_cooldown_and_reset(self):
        guard = Wave473CrossVenueQueueImbalanceDispersionGuard(cooldown_sec=2.0)
        guard.update([90.0, 10.0], [10.0, 90.0], timestamp=10.0) # Breach
        assert guard.is_blocked()

        # Cooldown active
        assert guard.update([50.0, 50.0], [50.0, 50.0], timestamp=11.0) is True

        # Cooldown expired and calm
        assert guard.update([50.0, 50.0], [50.0, 50.0], timestamp=13.0) is False

        guard.reset()
        assert guard.divergence == 0.0
        assert guard.is_blocked() is False


class TestWave474ApexMacroMicrostructureCanopySynthesizerGuard:
    """Test suite for Wave 474: Apex Macro-Microstructure Canopy Synthesizer Guard."""

    def test_init_validation(self):
        with pytest.raises(ValueError, match="critical_canopy_threshold must be in"):
            Wave474ApexMacroMicrostructureCanopySynthesizerGuard(critical_canopy_threshold=0.30)
        with pytest.raises(ValueError, match="dual_spike_threshold must be in"):
            Wave474ApexMacroMicrostructureCanopySynthesizerGuard(dual_spike_threshold=0.60)
        with pytest.raises(ValueError, match="cooldown_sec must be >= 0.1"):
            Wave474ApexMacroMicrostructureCanopySynthesizerGuard(cooldown_sec=0.05)

    def test_calm_safe_conditions_no_block(self):
        guard = Wave474ApexMacroMicrostructureCanopySynthesizerGuard()
        # Normal, calm market across all 5 inputs
        blocked = guard.update(
            event_horizon_ratio=0.95,
            depth_curvature=1.5,
            replenishment_halflife=0.40,
            cross_asset_dispersion=0.30,
            cross_venue_divergence=0.20,
            timestamp=10.0
        )
        assert not blocked
        assert not guard.is_blocked()
        assert guard.composite_canopy_index < 0.20
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave474ApexMacroMicrostructureCanopySynthesizerGuard"
        assert telem["is_blocked"] is False

    def test_apex_canopy_composite_breach(self):
        guard = Wave474ApexMacroMicrostructureCanopySynthesizerGuard(critical_canopy_threshold=0.65)
        # Severe multi-dimensional degradation:
        # R_H = 0.20 -> phi_1 = (0.7 - 0.2)/0.5 = 1.0
        # kappa = -2.5 -> phi_2 = 2.5 / 2.5 = 1.0
        # t_1/2 = 3.5 -> phi_3 = (3.5 - 0.5)/3.0 = 1.0
        # sigma_flow = 2.8 -> phi_4 = 2.8 / 3.5 = 0.80
        # Delta_I = 1.4 -> phi_5 = 1.4 / 1.6 = 0.875
        # Omega = 0.2 * (1.0 + 1.0 + 1.0 + 0.80 + 0.875) = 0.935 > 0.65
        blocked = guard.update(
            event_horizon_ratio=0.20,
            depth_curvature=-2.5,
            replenishment_halflife=3.5,
            cross_asset_dispersion=2.8,
            cross_venue_divergence=1.4,
            timestamp=10.0
        )
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "ALL"
        assert guard.composite_canopy_index > 0.65
        assert "APEX_CANOPY_FRAGILITY_BREACH" in guard.block_reason

    def test_dual_hazard_spike_breach(self):
        guard = Wave474ApexMacroMicrostructureCanopySynthesizerGuard(
            critical_canopy_threshold=0.80, # High threshold so dual spike triggers breaker
            dual_spike_threshold=0.85
        )
        # Only 2 metrics spike, others are calm:
        # phi_1 = 1.0 (R_H = 0.20)
        # phi_2 = 1.0 (kappa = -2.5)
        # Others near 0.0 -> Omega = 0.2 * 2 = 0.40 < 0.80, but spike_count = 2 >= 2!
        blocked = guard.update(
            event_horizon_ratio=0.20,
            depth_curvature=-2.5,
            replenishment_halflife=0.50,
            cross_asset_dispersion=0.20,
            cross_venue_divergence=0.10,
            timestamp=10.0
        )
        assert blocked
        assert guard.is_blocked()
        assert guard.spike_count >= 2
        assert "DUAL_HAZARD_SPIKE_BREACH" in guard.block_reason

    def test_cooldown_and_reset(self):
        guard = Wave474ApexMacroMicrostructureCanopySynthesizerGuard(cooldown_sec=2.0)
        # Dual hazard spike (R_H = 0.10 and kappa = -2.5) trips circuit breaker
        guard.update(event_horizon_ratio=0.10, depth_curvature=-2.5, timestamp=10.0)
        assert guard.is_blocked()

        # In cooldown
        assert guard.update(event_horizon_ratio=1.0, depth_curvature=1.0, timestamp=11.0) is True

        # Cooldown expired and calm
        assert guard.update(event_horizon_ratio=1.0, depth_curvature=1.0, timestamp=13.0) is False

        guard.reset()
        assert guard.composite_canopy_index == 0.0
        assert guard.is_blocked() is False

    def test_monotonicity_validation(self):
        guard = Wave474ApexMacroMicrostructureCanopySynthesizerGuard()
        guard.update(timestamp=10.0)
        with pytest.raises(ValueError, match="strictly monotonic"):
            guard.update(timestamp=9.0)
