"""
Test Batch 382: Rigorous Quantitative Verification Suite
=========================================================
Covers:
  - Wave 513: High-Frequency Limit Order Book Power-Law Hawkes Self-Excitation & Memory Kernel Decay Singularity Guard
  - Wave 514: Imperial Sovereign Master Apex Valhalla Reborn Canopy Master Guard
"""

import pytest
import numpy as np
from wave513_lob_hawkes_clustered_volatility_power_law_decay_guard import (
    Wave513LobHawkesClusteredVolatilityPowerLawDecayGuard,
)
from wave514_imperial_sovereign_master_apex_valhalla_reborn_guard import (
    Wave514ImperialSovereignMasterApexValhallaRebornGuard,
)


class TestWave513LobHawkesClusteredVolatilityPowerLawDecayGuard:
    """Rigorous verification of Wave 513 Power-Law Hawkes Guard."""

    def test_initialization_valid_and_invalid(self):
        guard = Wave513LobHawkesClusteredVolatilityPowerLawDecayGuard(
            max_branching_ratio=0.90,
            min_theta_threshold=0.15,
            critical_fragility_threshold=0.70,
            warning_branching_ratio=0.75,
            eta_warning_threshold=0.85,
            cooldown_sec=2.0,
        )
        assert guard.max_branching_ratio == 0.90
        assert guard.min_theta_threshold == 0.15
        assert guard.critical_fragility_threshold == 0.70
        assert guard.warning_branching_ratio == 0.75
        assert guard.eta_warning_threshold == 0.85
        assert guard.cooldown_sec == 2.0

        with pytest.raises(ValueError, match="max_branching_ratio"):
            Wave513LobHawkesClusteredVolatilityPowerLawDecayGuard(max_branching_ratio=0.50)

        with pytest.raises(ValueError, match="min_theta_threshold"):
            Wave513LobHawkesClusteredVolatilityPowerLawDecayGuard(min_theta_threshold=0.01)

        with pytest.raises(ValueError, match="critical_fragility_threshold"):
            Wave513LobHawkesClusteredVolatilityPowerLawDecayGuard(critical_fragility_threshold=0.30)

        with pytest.raises(ValueError, match="warning_branching_ratio"):
            Wave513LobHawkesClusteredVolatilityPowerLawDecayGuard(warning_branching_ratio=0.30)

        with pytest.raises(ValueError, match="eta_warning_threshold"):
            Wave513LobHawkesClusteredVolatilityPowerLawDecayGuard(eta_warning_threshold=0.40)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave513LobHawkesClusteredVolatilityPowerLawDecayGuard(cooldown_sec=0.05)

    def test_estimate_power_law_branching(self):
        guard = Wave513LobHawkesClusteredVolatilityPowerLawDecayGuard()

        with pytest.raises(ValueError, match="at least 16 inter-arrival intervals"):
            guard.estimate_power_law_branching([0.1] * 5)

        with pytest.raises(ValueError, match="t0_scale must be strictly positive"):
            guard.estimate_power_law_branching([0.1] * 20, t0_scale=-0.1)

        np.random.seed(42)
        dts = np.random.exponential(scale=0.1, size=40).tolist()
        res = guard.estimate_power_law_branching(dts)
        assert "theta" in res
        assert "alpha_0" in res
        assert "n_power" in res
        assert 0.05 <= res["theta"] <= 0.85
        assert 0.05 <= res["n_power"] <= 1.50

    def test_evaluate_input_validations(self):
        guard = Wave513LobHawkesClusteredVolatilityPowerLawDecayGuard()

        with pytest.raises(ValueError, match="n_power"):
            guard.evaluate(n_power=-0.1)

        with pytest.raises(ValueError, match="n_power"):
            guard.evaluate(n_power=3.5)

        with pytest.raises(ValueError, match="theta"):
            guard.evaluate(n_power=0.5, theta=0.005)

        with pytest.raises(ValueError, match="theta"):
            guard.evaluate(n_power=0.5, theta=2.5)

        with pytest.raises(ValueError, match="hawkes_eta_buy"):
            guard.evaluate(n_power=0.5, theta=0.4, hawkes_eta_buy=-0.5)

        with pytest.raises(ValueError, match="hawkes_eta_sell"):
            guard.evaluate(n_power=0.5, theta=0.4, hawkes_eta_sell=1.5)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave513LobHawkesClusteredVolatilityPowerLawDecayGuard()
        res = guard.evaluate(n_power=0.40, theta=0.50, timestamp=100.0)
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert res["psi_hawkes_pl"] == 0.0

    def test_supercritical_branching_ratio_breaker(self):
        guard = Wave513LobHawkesClusteredVolatilityPowerLawDecayGuard(max_branching_ratio=0.90)
        res = guard.evaluate(n_power=0.92, theta=0.45, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "SUPERCRITICAL_POWER_LAW_HAWKES_RUNAWAY" in res["reason"]

    def test_memory_decay_singularity_collapse_breaker(self):
        guard = Wave513LobHawkesClusteredVolatilityPowerLawDecayGuard(min_theta_threshold=0.15)
        res = guard.evaluate(n_power=0.50, theta=0.10, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "MEMORY_DECAY_SINGULARITY_COLLAPSE" in res["reason"]

    def test_asymmetric_directional_herd_cascades(self):
        guard = Wave513LobHawkesClusteredVolatilityPowerLawDecayGuard()
        # Buy cascade
        res_buy = guard.evaluate(n_power=0.80, theta=0.40, hawkes_eta_buy=0.90, timestamp=100.0)
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False
        assert "POWER_LAW_BUYER_HERD_CASCADE" in res_buy["reason"]

        guard.reset()
        # Sell cascade
        res_sell = guard.evaluate(n_power=0.80, theta=0.40, hawkes_eta_sell=0.90, timestamp=100.0)
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False
        assert "POWER_LAW_SELLER_LIQUIDATION_CASCADE" in res_sell["reason"]

    def test_cooldown_and_reset(self):
        guard = Wave513LobHawkesClusteredVolatilityPowerLawDecayGuard(cooldown_sec=5.0)
        res1 = guard.evaluate(n_power=0.95, theta=0.45, timestamp=100.0)
        assert res1["action"] == "HALT_ALL"
        assert res1["circuit_breaker"] is True

        # Within cooldown
        res2 = guard.evaluate(n_power=0.30, theta=0.50, timestamp=102.0)
        assert res2["action"] == "HALT_ALL"
        assert res2["circuit_breaker"] is True
        assert "COOLDOWN_ACTIVE" in res2["reason"]

        # After cooldown
        res3 = guard.evaluate(n_power=0.30, theta=0.50, timestamp=106.0)
        assert res3["action"] == "ALLOW_ALL"
        assert res3["circuit_breaker"] is False


class TestWave514ImperialSovereignMasterApexValhallaRebornGuard:
    """Rigorous verification of Wave 514 Imperial Valhalla Reborn Master Guard."""

    @pytest.fixture
    def base_kwargs(self):
        return {
            'hawkes_spectral_radius': 0.1,
            'resilience_fragility': 0.1,
            'xi_skew': 0.0,
            'omega_484': 0.1,
            'psi_impact': 0.1,
            'omega_486': 0.1,
            's_info': 0.1,
            'cross_spectral_radius': 0.1,
            'i_pressure': 0.0,
            'psi_momentum': 0.1,
            'psi_jump': 0.1,
            'psi_entropy': 0.1,
            'psi_wavelet': 0.1,
            'psi_sniping': 0.1,
            'psi_memory': 0.1,
            'psi_km': 0.1,
            'psi_mf': 0.1,
            'psi_rough': 0.1,
            'psi_hawkes_pl': 0.1,
        }

    def test_initialization_bounds(self):
        guard = Wave514ImperialSovereignMasterApexValhallaRebornGuard(
            critical_canopy_threshold=0.65,
            dual_spike_threshold=0.85,
            cooldown_sec=2.0,
        )
        assert guard.critical_canopy_threshold == 0.65
        assert guard.dual_spike_threshold == 0.85
        assert guard.cooldown_sec == 2.0
        assert len(guard.WEIGHTS) == 20
        assert np.isclose(np.sum(guard.WEIGHTS), 1.0)

        with pytest.raises(ValueError, match="critical_canopy_threshold"):
            Wave514ImperialSovereignMasterApexValhallaRebornGuard(critical_canopy_threshold=0.20)

        with pytest.raises(ValueError, match="dual_spike_threshold"):
            Wave514ImperialSovereignMasterApexValhallaRebornGuard(dual_spike_threshold=0.50)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave514ImperialSovereignMasterApexValhallaRebornGuard(cooldown_sec=0.01)

    def test_calm_equilibrium_allow_all(self, base_kwargs):
        guard = Wave514ImperialSovereignMasterApexValhallaRebornGuard()
        res = guard.evaluate(**base_kwargs, timestamp=100.0)
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert "IMPERIAL_VALHALLA_REBORN_EQUILIBRIUM_SECURE" in res["reason"]

    def test_valhalla_reborn_canopy_breach(self, base_kwargs):
        guard = Wave514ImperialSovereignMasterApexValhallaRebornGuard(critical_canopy_threshold=0.65)
        # All pillars elevated to high values
        elevated_kwargs = {k: 0.90 for k in base_kwargs}
        res = guard.evaluate(**elevated_kwargs, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "IMPERIAL_VALHALLA_REBORN_BREACH" in res["reason"]

    def test_dual_hazard_spike_trigger(self, base_kwargs):
        guard = Wave514ImperialSovereignMasterApexValhallaRebornGuard(
            critical_canopy_threshold=0.85,
            dual_spike_threshold=0.85,
        )
        # Only 2 pillars spike to >= 0.85
        spike_kwargs = dict(base_kwargs)
        spike_kwargs['hawkes_spectral_radius'] = 0.85  # phi_1 = 0.85 / 0.88 = 0.965 >= 0.85
        spike_kwargs['psi_impact'] = 0.65              # phi_5 = 0.65 / 0.70 = 0.928 >= 0.85
        res = guard.evaluate(**spike_kwargs, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "DUAL_HAZARD_SPIKE" in res["reason"]

    def test_asymmetric_directional_toxicity(self, base_kwargs):
        guard = Wave514ImperialSovereignMasterApexValhallaRebornGuard()

        # Buy toxic: d1_drift >= 0.75
        res_buy = guard.evaluate(**base_kwargs, d1_drift=0.80, timestamp=100.0)
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False
        assert "ASYMMETRIC_BUY_TOXICITY_OVERRIDE" in res_buy["reason"]

        guard.reset()
        # Sell toxic: d1_drift <= -0.75
        res_sell = guard.evaluate(**base_kwargs, d1_drift=-0.80, timestamp=100.0)
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False
        assert "ASYMMETRIC_SELL_TOXICITY_OVERRIDE" in res_sell["reason"]

        guard.reset()
        # Dual toxic
        dual_kwargs = dict(base_kwargs)
        dual_kwargs['d1_drift'] = 0.80
        dual_kwargs['i_pressure'] = 0.70
        res_dual = guard.evaluate(**dual_kwargs, timestamp=100.0)
        assert res_dual["action"] == "HALT_ALL"
        assert res_dual["circuit_breaker"] is False
        assert "DUAL_ASYMMETRIC_CROSS_TOXICITY_HALT" in res_dual["reason"]

    def test_cooldown_and_reset(self, base_kwargs):
        guard = Wave514ImperialSovereignMasterApexValhallaRebornGuard(cooldown_sec=5.0)
        elevated = {k: 0.95 for k in base_kwargs}
        res1 = guard.evaluate(**elevated, timestamp=100.0)
        assert res1["action"] == "HALT_ALL"
        assert res1["circuit_breaker"] is True

        # Within cooldown
        res2 = guard.evaluate(**base_kwargs, timestamp=102.0)
        assert res2["action"] == "HALT_ALL"
        assert res2["circuit_breaker"] is True
        assert "COOLDOWN_ACTIVE" in res2["reason"]

        # After cooldown
        res3 = guard.evaluate(**base_kwargs, timestamp=106.0)
        assert res3["action"] == "ALLOW_ALL"
        assert res3["circuit_breaker"] is False
