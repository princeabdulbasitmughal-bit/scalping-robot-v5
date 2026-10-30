"""
Test Batch 364: Wave 477 Cross-Asset Granger Causality & Wave 478 Grand Sovereign Apex Canopy Guard
====================================================================================================
Institutional unit test suite verifying bivariate Granger causality F-statistics, directional lead drift,
and 7-dimensional Grand Sovereign Apex Risk Canopy synthesis with dual-hazard spike circuit breakers.
"""

import pytest
import math
import numpy as np
from wave477_cross_asset_lead_lag_granger_causality_guard import Wave477CrossAssetLeadLagGrangerCausalityGuard
from wave478_grand_sovereign_apex_canopy_master_guard import Wave478GrandSovereignApexCanopyMasterGuard


class TestWave477CrossAssetLeadLagGrangerCausalityGuard:
    """Test suite for Wave 477: Cross-Asset Lead-Lag Granger Causality Guard."""

    def test_init_validation(self):
        with pytest.raises(ValueError, match="window_size must be >= 20"):
            Wave477CrossAssetLeadLagGrangerCausalityGuard(window_size=15)
        with pytest.raises(ValueError, match="min_samples must be >= 12"):
            Wave477CrossAssetLeadLagGrangerCausalityGuard(min_samples=8)
        with pytest.raises(ValueError, match="min_samples .* cannot exceed window_size"):
            Wave477CrossAssetLeadLagGrangerCausalityGuard(window_size=25, min_samples=30)
        with pytest.raises(ValueError, match="lag_order must be 1, 2, or 3"):
            Wave477CrossAssetLeadLagGrangerCausalityGuard(lag_order=4)
        with pytest.raises(ValueError, match="max_granger_intensity must be in"):
            Wave477CrossAssetLeadLagGrangerCausalityGuard(max_granger_intensity=0.10)
        with pytest.raises(ValueError, match="f_stat_critical must be > 1.0"):
            Wave477CrossAssetLeadLagGrangerCausalityGuard(f_stat_critical=0.50)
        with pytest.raises(ValueError, match="min_lead_drift must be > 0.0"):
            Wave477CrossAssetLeadLagGrangerCausalityGuard(min_lead_drift=0.0)
        with pytest.raises(ValueError, match="cooldown_sec must be >= 0.1"):
            Wave477CrossAssetLeadLagGrangerCausalityGuard(cooldown_sec=0.05)

    def test_insufficient_samples(self):
        guard = Wave477CrossAssetLeadLagGrangerCausalityGuard(min_samples=15)
        for i in range(10):
            blocked = guard.update(0.001, 0.5, timestamp=10.0 + i)
            assert not blocked
            assert not guard.is_blocked()
            assert guard.block_reason == "INSUFFICIENT_SAMPLES"

    def test_calm_uncorrelated_flows_no_block(self):
        guard = Wave477CrossAssetLeadLagGrangerCausalityGuard(min_samples=15, max_granger_intensity=0.40)
        # Independent white noise local returns and foreign flows
        np.random.seed(42)
        y = np.random.normal(0.0, 0.001, 25)
        x = np.random.normal(0.0, 1.0, 25)

        for i in range(25):
            guard.update(float(y[i]), float(x[i]), timestamp=100.0 + i)

        assert not guard.is_blocked()
        assert not guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert guard.granger_intensity < 0.40
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave477CrossAssetLeadLagGrangerCausalityGuard"
        assert telem["is_blocked"] is False

    def test_bullish_lead_lag_surge_blocks_sell(self):
        guard = Wave477CrossAssetLeadLagGrangerCausalityGuard(
            min_samples=15,
            lag_order=1,
            max_granger_intensity=0.35,
            f_stat_critical=3.0,
            min_lead_drift=0.002
        )
        # Deterministic lead relationship: Y_t = 0.01 * X_{t-1} + noise
        x_vals = [float(i % 5 + 1) for i in range(25)]
        y_vals = [0.0] + [0.01 * x_vals[i] for i in range(24)]

        for i in range(25):
            blocked = guard.update(y_vals[i], x_vals[i], timestamp=100.0 + i)

        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "SELL" # Strongly bullish lead relationship -> shorting is toxic
        assert guard.is_entry_blocked("SELL")
        assert not guard.is_entry_blocked("BUY")
        assert "BULLISH_LEAD_LAG_SURGE" in guard.block_reason

    def test_bearish_lead_lag_dump_blocks_buy(self):
        guard = Wave477CrossAssetLeadLagGrangerCausalityGuard(
            min_samples=15,
            lag_order=1,
            max_granger_intensity=0.35,
            f_stat_critical=3.0,
            min_lead_drift=0.002
        )
        # Inverse lead relationship: Y_t = -0.01 * X_{t-1}
        x_vals = [float(i % 5 + 1) for i in range(25)]
        y_vals = [0.0] + [-0.01 * x_vals[i] for i in range(24)]

        for i in range(25):
            blocked = guard.update(y_vals[i], x_vals[i], timestamp=100.0 + i)

        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "BUY" # Strongly bearish lead relationship -> buying is toxic
        assert guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert "BEARISH_LEAD_LAG_DUMP" in guard.block_reason

    def test_cooldown_and_reset(self):
        guard = Wave477CrossAssetLeadLagGrangerCausalityGuard(
            min_samples=15,
            lag_order=1,
            max_granger_intensity=0.30,
            f_stat_critical=2.0,
            cooldown_sec=2.0
        )
        x_vals = [float(i % 5 + 1) for i in range(25)]
        y_vals = [0.0] + [0.01 * x_vals[i] for i in range(24)]

        for i in range(25):
            guard.update(y_vals[i], x_vals[i], timestamp=100.0 + i)

        assert guard.is_blocked()

        # Cooldown prevents immediate unblock
        assert guard.update(0.0, 0.0, timestamp=125.5) is True

        guard.reset()
        assert guard.sample_count == 0
        assert guard.is_blocked() is False

    def test_monotonicity_validation(self):
        guard = Wave477CrossAssetLeadLagGrangerCausalityGuard()
        guard.update(0.001, 1.0, timestamp=10.0)
        with pytest.raises(ValueError, match="strictly monotonic"):
            guard.update(0.001, 1.0, timestamp=9.0)


class TestWave478GrandSovereignApexCanopyMasterGuard:
    """Test suite for Wave 478: Grand Sovereign Apex Canopy Master Guard."""

    def test_init_validation(self):
        with pytest.raises(ValueError, match="critical_canopy_threshold must be in"):
            Wave478GrandSovereignApexCanopyMasterGuard(critical_canopy_threshold=0.30)
        with pytest.raises(ValueError, match="dual_spike_threshold must be in"):
            Wave478GrandSovereignApexCanopyMasterGuard(dual_spike_threshold=0.60)
        with pytest.raises(ValueError, match="cooldown_sec must be >= 0.1"):
            Wave478GrandSovereignApexCanopyMasterGuard(cooldown_sec=0.05)

    def test_calm_safe_conditions_no_block(self):
        guard = Wave478GrandSovereignApexCanopyMasterGuard()
        blocked = guard.update(
            replenishment_halflife=0.50,
            cross_asset_dispersion=0.50,
            cross_venue_divergence=0.20,
            macro_canopy_omega=0.10,
            cancellation_velocity=0.20,
            markov_entropy=0.85,
            granger_intensity=0.05,
            timestamp=10.0
        )
        assert not blocked
        assert not guard.is_blocked()
        assert guard.composite_canopy_index < 0.20
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave478GrandSovereignApexCanopyMasterGuard"
        assert telem["is_blocked"] is False

    def test_grand_sovereign_canopy_composite_breach(self):
        guard = Wave478GrandSovereignApexCanopyMasterGuard(critical_canopy_threshold=0.65)
        # Severe degradation across multiple dimensions:
        # phi_1 = (3.5 - 0.5)/3.0 = 1.0
        # phi_2 = 3.5 / 3.5 = 1.0
        # phi_3 = 1.6 / 1.6 = 1.0
        # phi_4 = 0.90
        # phi_5 = 3.0 / 3.0 = 1.0
        # phi_6 = (0.85 - 0.35)/0.5 = 1.0
        # phi_7 = 0.50 / 0.5 = 1.0
        # Omega = 0.15 * 5 + 0.15 * 0.9 + 0.10 * 1.0 = 0.75 + 0.135 + 0.10 = 0.985 > 0.65
        blocked = guard.update(
            replenishment_halflife=3.5,
            cross_asset_dispersion=3.5,
            cross_venue_divergence=1.6,
            macro_canopy_omega=0.90,
            cancellation_velocity=3.0,
            markov_entropy=0.35,
            granger_intensity=0.50,
            timestamp=10.0
        )
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "ALL"
        assert guard.composite_canopy_index > 0.65
        assert "GRAND_SOVEREIGN_CANOPY_BREACH" in guard.block_reason

    def test_dual_hazard_spike_breach(self):
        guard = Wave478GrandSovereignApexCanopyMasterGuard(
            critical_canopy_threshold=0.85, # High threshold so dual spike triggers breaker
            dual_spike_threshold=0.85
        )
        # Only 2 metrics spike (cancellation velocity 3.0 -> phi_5 = 1.0, markov entropy 0.35 -> phi_6 = 1.0)
        # Others remain calm: Omega = 0.15 * 2 = 0.30 < 0.85, but spike_count = 2 >= 2!
        blocked = guard.update(
            replenishment_halflife=0.50,
            cross_asset_dispersion=0.50,
            cross_venue_divergence=0.20,
            macro_canopy_omega=0.10,
            cancellation_velocity=3.0,
            markov_entropy=0.35,
            granger_intensity=0.05,
            timestamp=10.0
        )
        assert blocked
        assert guard.is_blocked()
        assert guard.spike_count >= 2
        assert "DUAL_HAZARD_SPIKE_BREACH" in guard.block_reason

    def test_cooldown_and_reset(self):
        guard = Wave478GrandSovereignApexCanopyMasterGuard(cooldown_sec=2.0)
        guard.update(cancellation_velocity=3.0, markov_entropy=0.35, timestamp=10.0) # Breach
        assert guard.is_blocked()

        # In cooldown
        assert guard.update(cancellation_velocity=0.2, markov_entropy=0.85, timestamp=11.0) is True

        # Cooldown expired and calm
        assert guard.update(cancellation_velocity=0.2, markov_entropy=0.85, timestamp=13.0) is False

        guard.reset()
        assert guard.composite_canopy_index == 0.0
        assert guard.is_blocked() is False

    def test_monotonicity_validation(self):
        guard = Wave478GrandSovereignApexCanopyMasterGuard()
        guard.update(timestamp=10.0)
        with pytest.raises(ValueError, match="strictly monotonic"):
            guard.update(timestamp=9.0)
