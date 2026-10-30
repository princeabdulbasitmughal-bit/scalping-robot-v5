"""
Test Batch 365: Wave 479 Flow Toxicity Entropy Rate Guard & Wave 480 Grand Jubilee Apex Sovereign Canopy Guard
==============================================================================================================
Institutional unit test suite verifying volume-synchronized Shannon & Rényi entropy rates,
rolling VPIN toxicity, 8-dimensional Grand Jubilee Apex Risk Canopy synthesis, and dual-hazard spikes.
"""

import pytest
import math
import numpy as np
from wave479_order_flow_toxicity_entropy_rate_guard import Wave479OrderFlowToxicityEntropyRateGuard
from wave480_grand_jubilee_apex_sovereign_canopy_master_guard import Wave480GrandJubileeApexSovereignCanopyMasterGuard


class TestWave479OrderFlowToxicityEntropyRateGuard:
    """Test suite for Wave 479: Order Flow Toxicity Entropy Rate Guard."""

    def test_init_validation(self):
        with pytest.raises(ValueError, match="window_buckets must be >= 10"):
            Wave479OrderFlowToxicityEntropyRateGuard(window_buckets=8)
        with pytest.raises(ValueError, match="min_buckets must be >= 5"):
            Wave479OrderFlowToxicityEntropyRateGuard(min_buckets=3)
        with pytest.raises(ValueError, match="min_buckets .* cannot exceed window_buckets"):
            Wave479OrderFlowToxicityEntropyRateGuard(window_buckets=12, min_buckets=15)
        with pytest.raises(ValueError, match="min_entropy_threshold must be in"):
            Wave479OrderFlowToxicityEntropyRateGuard(min_entropy_threshold=0.10)
        with pytest.raises(ValueError, match="max_vpin_threshold must be in"):
            Wave479OrderFlowToxicityEntropyRateGuard(max_vpin_threshold=0.30)
        with pytest.raises(ValueError, match="max_negative_entropy_velocity must be <= -0.05"):
            Wave479OrderFlowToxicityEntropyRateGuard(max_negative_entropy_velocity=-0.01)
        with pytest.raises(ValueError, match="cooldown_sec must be >= 0.1"):
            Wave479OrderFlowToxicityEntropyRateGuard(cooldown_sec=0.05)

    def test_insufficient_samples(self):
        guard = Wave479OrderFlowToxicityEntropyRateGuard(min_buckets=8)
        for i in range(5):
            blocked = guard.update(50.0, 50.0, timestamp=10.0 + i)
            assert not blocked
            assert not guard.is_blocked()
            assert guard.block_reason == "INSUFFICIENT_SAMPLES"

    def test_calm_balanced_flow_no_block(self):
        guard = Wave479OrderFlowToxicityEntropyRateGuard(min_buckets=8)
        # Balanced 50/50 volume
        for i in range(12):
            guard.update(50.0, 50.0, timestamp=100.0 + i)

        assert not guard.is_blocked()
        assert not guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert guard.shannon_entropy > 0.95
        assert guard.vpin < 0.10
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave479OrderFlowToxicityEntropyRateGuard"
        assert telem["is_blocked"] is False

    def test_flow_toxicity_entropy_collapse_blocks_all(self):
        guard = Wave479OrderFlowToxicityEntropyRateGuard(min_buckets=8, min_entropy_threshold=0.45)
        for i in range(10):
            guard.update(50.0, 50.0, timestamp=100.0 + i)

        # Extreme one-sided volume: 95 buy, 5 sell -> p_buy = 0.95, H = 0.286 < 0.45
        blocked = guard.update(95.0, 5.0, timestamp=110.0)
        assert blocked
        assert guard.is_blocked()
        assert guard.shannon_entropy < 0.45

    def test_informed_buy_sweep_blocks_sell(self):
        guard = Wave479OrderFlowToxicityEntropyRateGuard(
            min_buckets=8,
            min_entropy_threshold=0.50
        )
        for i in range(10):
            guard.update(50.0, 50.0, timestamp=100.0 + i)

        # 90 buy, 10 sell: p_buy = 0.90 > 0.80 -> shorting is toxic
        blocked = guard.update(90.0, 10.0, timestamp=110.0)
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "SELL"
        assert guard.is_entry_blocked("SELL")
        assert not guard.is_entry_blocked("BUY")
        assert "INFORMED_BUY_SWEEP" in guard.block_reason

    def test_informed_sell_dump_blocks_buy(self):
        guard = Wave479OrderFlowToxicityEntropyRateGuard(
            min_buckets=8,
            min_entropy_threshold=0.50
        )
        for i in range(10):
            guard.update(50.0, 50.0, timestamp=100.0 + i)

        # 10 buy, 90 sell: p_sell = 0.90 > 0.80 -> buying is toxic
        blocked = guard.update(10.0, 90.0, timestamp=110.0)
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "BUY"
        assert guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert "INFORMED_SELL_DUMP" in guard.block_reason

    def test_vpin_toxicity_explosion(self):
        guard = Wave479OrderFlowToxicityEntropyRateGuard(
            min_buckets=8,
            max_vpin_threshold=0.65
        )
        # Persistent heavy flow imbalance: 85 buy, 15 sell -> imb = 0.70
        for i in range(10):
            guard.update(85.0, 15.0, timestamp=100.0 + i)

        assert guard.is_blocked()
        assert guard.vpin >= 0.65

    def test_entropy_evaporation_velocity_breach(self):
        guard = Wave479OrderFlowToxicityEntropyRateGuard(
            min_buckets=8,
            min_entropy_threshold=0.20, # Low floor so velocity triggers as primary breaker
            max_negative_entropy_velocity=-0.40
        )
        # Establish baseline over 8 buckets with balanced entropy H = 1.0 (timestamps 100.0 to 107.0)
        for i in range(8):
            guard.update(50.0, 50.0, timestamp=100.0 + i)

        # Sudden shift to 70/30 (H = 0.881 > 0.20) in dt = 0.2s (107.0 to 107.2) -> v_H = (0.881 - 1.0)/0.2 = -0.595 < -0.40
        blocked = guard.update(70.0, 30.0, timestamp=107.2)
        assert blocked
        assert guard.is_blocked()
        assert "ENTROPY_EVAPORATION_VELOCITY_BREACH" in guard.block_reason

    def test_cooldown_and_reset(self):
        guard = Wave479OrderFlowToxicityEntropyRateGuard(min_buckets=8, cooldown_sec=2.0)
        for i in range(10):
            guard.update(50.0, 50.0, timestamp=100.0 + i)

        guard.update(95.0, 5.0, timestamp=110.0) # Breach
        assert guard.is_blocked()

        # Cooldown active
        assert guard.update(50.0, 50.0, timestamp=111.0) is True

        # Cooldown expired and calm
        assert guard.update(50.0, 50.0, timestamp=113.0) is False

        guard.reset()
        assert guard.shannon_entropy == 1.0
        assert guard.is_blocked() is False

    def test_monotonicity_validation(self):
        guard = Wave479OrderFlowToxicityEntropyRateGuard()
        guard.update(50.0, 50.0, timestamp=10.0)
        with pytest.raises(ValueError, match="strictly monotonic"):
            guard.update(50.0, 50.0, timestamp=9.0)


class TestWave480GrandJubileeApexSovereignCanopyMasterGuard:
    """Test suite for Wave 480: Grand Jubilee Apex Sovereign Canopy Master Guard."""

    def test_init_validation(self):
        with pytest.raises(ValueError, match="critical_canopy_threshold must be in"):
            Wave480GrandJubileeApexSovereignCanopyMasterGuard(critical_canopy_threshold=0.30)
        with pytest.raises(ValueError, match="dual_spike_threshold must be in"):
            Wave480GrandJubileeApexSovereignCanopyMasterGuard(dual_spike_threshold=0.60)
        with pytest.raises(ValueError, match="cooldown_sec must be >= 0.1"):
            Wave480GrandJubileeApexSovereignCanopyMasterGuard(cooldown_sec=0.05)

    def test_calm_safe_conditions_no_block(self):
        guard = Wave480GrandJubileeApexSovereignCanopyMasterGuard()
        blocked = guard.update(
            replenishment_halflife=0.50,
            cross_asset_dispersion=0.50,
            cross_venue_divergence=0.20,
            macro_canopy_omega=0.10,
            cancellation_velocity=0.20,
            markov_entropy=0.85,
            granger_intensity=0.05,
            flow_vpin=0.15,
            timestamp=10.0
        )
        assert not blocked
        assert not guard.is_blocked()
        assert guard.composite_canopy_index < 0.20
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave480GrandJubileeApexSovereignCanopyMasterGuard"
        assert telem["is_blocked"] is False

    def test_grand_jubilee_canopy_composite_breach(self):
        guard = Wave480GrandJubileeApexSovereignCanopyMasterGuard(critical_canopy_threshold=0.65)
        # Severe degradation across multiple dimensions:
        # phi_1 = (3.5 - 0.5)/3.0 = 1.0
        # phi_2 = 3.5 / 3.5 = 1.0
        # phi_3 = 1.6 / 1.6 = 1.0
        # phi_4 = 0.90
        # phi_5 = 3.0 / 3.0 = 1.0
        # phi_6 = (0.85 - 0.35)/0.5 = 1.0
        # phi_7 = 0.50 / 0.5 = 1.0
        # phi_8 = 0.70 / 0.7 = 1.0
        # Omega = 0.125 * (7.0 + 0.90) = 0.125 * 7.90 = 0.9875 > 0.65
        blocked = guard.update(
            replenishment_halflife=3.5,
            cross_asset_dispersion=3.5,
            cross_venue_divergence=1.6,
            macro_canopy_omega=0.90,
            cancellation_velocity=3.0,
            markov_entropy=0.35,
            granger_intensity=0.50,
            flow_vpin=0.70,
            timestamp=10.0
        )
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "ALL"
        assert guard.composite_canopy_index > 0.65
        assert "GRAND_JUBILEE_CANOPY_BREACH" in guard.block_reason

    def test_dual_hazard_spike_breach(self):
        guard = Wave480GrandJubileeApexSovereignCanopyMasterGuard(
            critical_canopy_threshold=0.85, # High threshold so dual spike triggers breaker
            dual_spike_threshold=0.85
        )
        # Only 2 metrics spike (cancellation velocity 3.0 -> phi_5 = 1.0, flow vpin 0.65 -> phi_8 = 0.928)
        # Others remain calm: Omega = 0.125 * (1.0 + 0.928) = 0.241 < 0.85, but spike_count = 2 >= 2!
        blocked = guard.update(
            replenishment_halflife=0.50,
            cross_asset_dispersion=0.50,
            cross_venue_divergence=0.20,
            macro_canopy_omega=0.10,
            cancellation_velocity=3.0,
            markov_entropy=0.85,
            granger_intensity=0.05,
            flow_vpin=0.65,
            timestamp=10.0
        )
        assert blocked
        assert guard.is_blocked()
        assert guard.spike_count >= 2
        assert "DUAL_HAZARD_SPIKE_BREACH" in guard.block_reason

    def test_cooldown_and_reset(self):
        guard = Wave480GrandJubileeApexSovereignCanopyMasterGuard(cooldown_sec=2.0)
        guard.update(cancellation_velocity=3.0, flow_vpin=0.65, timestamp=10.0) # Breach
        assert guard.is_blocked()

        # In cooldown
        assert guard.update(cancellation_velocity=0.2, flow_vpin=0.10, timestamp=11.0) is True

        # Cooldown expired and calm
        assert guard.update(cancellation_velocity=0.2, flow_vpin=0.10, timestamp=13.0) is False

        guard.reset()
        assert guard.composite_canopy_index == 0.0
        assert guard.is_blocked() is False

    def test_monotonicity_validation(self):
        guard = Wave480GrandJubileeApexSovereignCanopyMasterGuard()
        guard.update(timestamp=10.0)
        with pytest.raises(ValueError, match="strictly monotonic"):
            guard.update(timestamp=9.0)
