"""
Test Batch 368: Rigorous Quantitative Verification Suite
=========================================================
Covers:
  - Wave 485: Non-Linear Market Impact Curvature & Power-Law Decay Guard
  - Wave 486: Imperial Grand Jubilee Apex Microstructure Master Guard
"""

import pytest
import numpy as np
from wave485_nonlinear_impact_powerlaw_decay_guard import Wave485NonlinearImpactPowerlawDecayGuard
from wave486_imperial_grand_jubilee_apex_microstructure_master_guard import Wave486ImperialGrandJubileeApexMicrostructureMasterGuard


class TestWave485NonlinearImpactPowerlawDecayGuard:
    """Rigorous verification of Wave 485 Non-Linear Market Impact Guard."""

    def test_initialization_valid_and_invalid(self):
        guard = Wave485NonlinearImpactPowerlawDecayGuard(
            critical_fragility_threshold=0.70,
            max_curvature_threshold=0.88,
            min_decay_threshold=0.15,
            cooldown_sec=2.0
        )
        assert guard.critical_fragility_threshold == 0.70
        assert guard.max_curvature_threshold == 0.88

        with pytest.raises(ValueError, match="critical_fragility_threshold"):
            Wave485NonlinearImpactPowerlawDecayGuard(critical_fragility_threshold=0.30)

        with pytest.raises(ValueError, match="max_curvature_threshold"):
            Wave485NonlinearImpactPowerlawDecayGuard(max_curvature_threshold=1.50)

        with pytest.raises(ValueError, match="min_decay_threshold"):
            Wave485NonlinearImpactPowerlawDecayGuard(min_decay_threshold=0.01)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave485NonlinearImpactPowerlawDecayGuard(cooldown_sec=0.05)

    def test_estimate_curvature_ols(self):
        guard = Wave485NonlinearImpactPowerlawDecayGuard()

        # Insufficient data
        with pytest.raises(ValueError, match="at least 3 points"):
            guard.estimate_curvature([10.0, 20.0], [0.1, 0.2])

        # Length mismatch
        with pytest.raises(ValueError, match="length"):
            guard.estimate_curvature([10.0, 20.0, 30.0], [0.1, 0.2])

        # Synthetic square-root data: Delta P ~ c * Q^0.50
        vols = [100.0, 400.0, 900.0, 1600.0, 2500.0]
        dislocations = [10.0, 20.0, 30.0, 40.0, 50.0]
        alpha = guard.estimate_curvature(vols, dislocations)
        assert abs(alpha - 0.50) < 0.05

        # Synthetic linear data: Delta P ~ c * Q^1.0
        dislocations_lin = [1.0, 4.0, 9.0, 16.0, 25.0]
        alpha_lin = guard.estimate_curvature(vols, dislocations_lin)
        assert abs(alpha_lin - 1.0) < 0.05

    def test_evaluate_input_validations(self):
        guard = Wave485NonlinearImpactPowerlawDecayGuard()

        with pytest.raises(ValueError, match="alpha_eff"):
            guard.evaluate(alpha_eff=0.01, beta_eff=0.5)

        with pytest.raises(ValueError, match="beta_eff"):
            guard.evaluate(alpha_eff=0.5, beta_eff=-0.1)

        with pytest.raises(ValueError, match="alpha_buy"):
            guard.evaluate(alpha_eff=0.5, beta_eff=0.5, alpha_buy=0.01)

        with pytest.raises(ValueError, match="alpha_sell"):
            guard.evaluate(alpha_eff=0.5, beta_eff=0.5, alpha_sell=2.5)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave485NonlinearImpactPowerlawDecayGuard()
        res = guard.evaluate(
            alpha_eff=0.50,
            beta_eff=0.50,
            alpha_buy=0.50,
            alpha_sell=0.50,
            timestamp=100.0
        )
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert res["psi_impact"] == 0.0

    def test_superlinear_impact_breach(self):
        guard = Wave485NonlinearImpactPowerlawDecayGuard(max_curvature_threshold=0.88)
        res = guard.evaluate(
            alpha_eff=0.92,
            beta_eff=0.50,
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "SUPERLINEAR_IMPACT_BREACH" in res["reason"]

    def test_critical_fragility_breach(self):
        guard = Wave485NonlinearImpactPowerlawDecayGuard(critical_fragility_threshold=0.70)
        # alpha_eff=0.80 -> term_alpha = (0.80 - 0.50)/0.40 = 0.75
        # beta_eff=0.15 -> term_beta = (0.50 - 0.15)/0.40 = 0.875
        # psi_impact = 0.50 * 0.75 + 0.50 * 0.875 = 0.8125 >= 0.70
        res = guard.evaluate(
            alpha_eff=0.80,
            beta_eff=0.15,
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "IMPACT_FRAGILITY_CRITICAL" in res["reason"]
        assert res["psi_impact"] >= 0.70

    def test_asymmetric_directional_impact(self):
        guard = Wave485NonlinearImpactPowerlawDecayGuard()

        # Buy side superlinear toxicity
        res_buy = guard.evaluate(
            alpha_eff=0.55,
            beta_eff=0.45,
            alpha_buy=0.78,
            alpha_sell=0.52,
            timestamp=100.0
        )
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False

        # Sell side superlinear toxicity
        res_sell = guard.evaluate(
            alpha_eff=0.55,
            beta_eff=0.45,
            alpha_buy=0.52,
            alpha_sell=0.82,
            timestamp=100.0
        )
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False

    def test_cooldown_and_reset(self):
        guard = Wave485NonlinearImpactPowerlawDecayGuard(cooldown_sec=2.0)
        # Trigger
        res = guard.evaluate(alpha_eff=0.95, beta_eff=0.10, timestamp=10.0)
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        # In cooldown
        res_cool = guard.evaluate(alpha_eff=0.50, beta_eff=0.50, timestamp=11.0)
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        # Reset
        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate(alpha_eff=0.50, beta_eff=0.50, timestamp=11.1)
        assert res_ok["action"] == "ALLOW_ALL"


class TestWave486ImperialGrandJubileeApexMicrostructureMasterGuard:
    """Rigorous verification of Wave 486 Imperial Grand Jubilee Apex Microstructure Master Guard."""

    def test_initialization_bounds(self):
        guard = Wave486ImperialGrandJubileeApexMicrostructureMasterGuard(
            critical_canopy_threshold=0.65,
            dual_spike_threshold=0.85,
            cooldown_sec=2.0
        )
        assert guard.critical_canopy_threshold == 0.65
        assert guard.dual_spike_threshold == 0.85

        with pytest.raises(ValueError, match="critical_canopy_threshold"):
            Wave486ImperialGrandJubileeApexMicrostructureMasterGuard(critical_canopy_threshold=0.30)

        with pytest.raises(ValueError, match="dual_spike_threshold"):
            Wave486ImperialGrandJubileeApexMicrostructureMasterGuard(dual_spike_threshold=0.60)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave486ImperialGrandJubileeApexMicrostructureMasterGuard(cooldown_sec=0.05)

    def test_input_range_validations(self):
        guard = Wave486ImperialGrandJubileeApexMicrostructureMasterGuard()

        with pytest.raises(ValueError, match="hawkes_spectral_radius"):
            guard.evaluate(-0.1, 0.2, 0.0, 0.2, 0.2, 0.5)

        with pytest.raises(ValueError, match="resilience_fragility"):
            guard.evaluate(0.5, 1.5, 0.0, 0.2, 0.2, 0.5)

        with pytest.raises(ValueError, match="xi_skew"):
            guard.evaluate(0.5, 0.2, -1.5, 0.2, 0.2, 0.5)

        with pytest.raises(ValueError, match="omega_484"):
            guard.evaluate(0.5, 0.2, 0.0, 1.5, 0.2, 0.5)

        with pytest.raises(ValueError, match="psi_impact"):
            guard.evaluate(0.5, 0.2, 0.0, 0.2, 1.5, 0.5)

        with pytest.raises(ValueError, match="alpha_eff"):
            guard.evaluate(0.5, 0.2, 0.0, 0.2, 0.2, 0.01)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave486ImperialGrandJubileeApexMicrostructureMasterGuard()
        res = guard.evaluate(
            hawkes_spectral_radius=0.30,
            resilience_fragility=0.15,
            xi_skew=0.05,
            omega_484=0.15,
            psi_impact=0.10,
            alpha_eff=0.50,
            timestamp=100.0
        )
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert res["omega_canopy"] < 0.35
        assert res["spikes_count"] == 0

    def test_canopy_composite_breach(self):
        guard = Wave486ImperialGrandJubileeApexMicrostructureMasterGuard(critical_canopy_threshold=0.65)
        res = guard.evaluate(
            hawkes_spectral_radius=0.80, # phi_1 = 0.80/0.88 = 0.909
            resilience_fragility=0.62,   # phi_2 = 0.62/0.70 = 0.886
            xi_skew=0.65,                # phi_3 = 0.65/0.75 = 0.867
            omega_484=0.58,              # phi_4 = 0.58/0.65 = 0.892
            psi_impact=0.60,             # phi_5 = 0.60/0.70 = 0.857
            alpha_eff=0.85,              # phi_6 = (0.85-0.45)/0.45 = 0.889
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "IMPERIAL_GRAND_JUBILEE_BREACH" in res["reason"]
        assert res["omega_canopy"] >= 0.65

    def test_dual_hazard_spike_trigger(self):
        guard = Wave486ImperialGrandJubileeApexMicrostructureMasterGuard(
            critical_canopy_threshold=0.75,
            dual_spike_threshold=0.85
        )
        # 2 pillars spike >= 0.85, rest are zero
        res = guard.evaluate(
            hawkes_spectral_radius=0.80, # phi_1 = 0.909 >= 0.85
            resilience_fragility=0.65,   # phi_2 = 0.928 >= 0.85
            xi_skew=0.0,
            omega_484=0.05,
            psi_impact=0.05,
            alpha_eff=0.45,
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "DUAL_HAZARD_SPIKE" in res["reason"]
        assert res["spikes_count"] >= 2

    def test_asymmetric_directional_toxicity(self):
        guard = Wave486ImperialGrandJubileeApexMicrostructureMasterGuard()

        # Buy side toxicity
        res_buy = guard.evaluate(
            hawkes_spectral_radius=0.40,
            resilience_fragility=0.20,
            xi_skew=0.72, # xi_skew >= 0.70
            omega_484=0.20,
            psi_impact=0.20,
            alpha_eff=0.50,
            timestamp=100.0
        )
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False

        # Sell side toxicity
        res_sell = guard.evaluate(
            hawkes_spectral_radius=0.40,
            resilience_fragility=0.20,
            xi_skew=0.0,
            omega_484=0.20,
            psi_impact=0.20,
            alpha_eff=0.50,
            alpha_sell=0.80, # alpha_sell >= 0.75
            timestamp=100.0
        )
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False

    def test_cooldown_and_reset(self):
        guard = Wave486ImperialGrandJubileeApexMicrostructureMasterGuard(cooldown_sec=2.5)
        res = guard.evaluate(0.88, 0.70, 0.75, 0.65, 0.70, 0.90, timestamp=10.0)
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        # In cooldown
        res_cool = guard.evaluate(0.1, 0.1, 0.0, 0.1, 0.1, 0.5, timestamp=11.5)
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        # Reset
        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate(0.1, 0.1, 0.0, 0.1, 0.1, 0.5, timestamp=11.6)
        assert res_ok["action"] == "ALLOW_ALL"
