"""
Test Batch 370: Rigorous Quantitative Verification Suite
=========================================================
Covers:
  - Wave 489: Cross-Impact Matrix Eigenvalue & Lead-Lag Asymmetry Guard
  - Wave 490: Imperial Supreme Sovereign Apex Microstructure Master Guard
"""

import pytest
import numpy as np
from wave489_cross_impact_eigenvalue_leadlag_guard import Wave489CrossImpactEigenvalueLeadlagGuard
from wave490_imperial_supreme_sovereign_apex_microstructure_master_guard import Wave490ImperialSupremeSovereignApexMicrostructureMasterGuard


class TestWave489CrossImpactEigenvalueLeadlagGuard:
    """Rigorous verification of Wave 489 Cross-Impact Guard."""

    def test_initialization_valid_and_invalid(self):
        guard = Wave489CrossImpactEigenvalueLeadlagGuard(
            max_spectral_threshold=0.85,
            max_asymmetry_threshold=0.65,
            distortion_threshold=0.60,
            cooldown_sec=2.0
        )
        assert guard.max_spectral_threshold == 0.85
        assert guard.max_asymmetry_threshold == 0.65

        with pytest.raises(ValueError, match="max_spectral_threshold"):
            Wave489CrossImpactEigenvalueLeadlagGuard(max_spectral_threshold=0.30)

        with pytest.raises(ValueError, match="max_asymmetry_threshold"):
            Wave489CrossImpactEigenvalueLeadlagGuard(max_asymmetry_threshold=0.20)

        with pytest.raises(ValueError, match="distortion_threshold"):
            Wave489CrossImpactEigenvalueLeadlagGuard(distortion_threshold=0.10)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave489CrossImpactEigenvalueLeadlagGuard(cooldown_sec=0.05)

    def test_compute_matrix_metrics(self):
        guard = Wave489CrossImpactEigenvalueLeadlagGuard()

        # Non-square matrix
        with pytest.raises(ValueError, match="square 2D matrix"):
            guard.compute_matrix_metrics([[0.5, 0.2, 0.1], [0.1, 0.5, 0.2]])

        # 1x1 matrix
        with pytest.raises(ValueError, match="at least 2x2"):
            guard.compute_matrix_metrics([[0.5]])

        # Symmetric 2x2 matrix: A = 0, chi_asym = 0
        mat_sym = [
            [0.5, 0.2],
            [0.2, 0.5]
        ]
        res_sym = guard.compute_matrix_metrics(mat_sym)
        assert abs(res_sym["chi_asym"]) < 1e-4
        assert abs(res_sym["spectral_radius"] - 0.70) < 1e-4

        # Anti-symmetric component dominant
        mat_asym = [
            [0.1, 0.8],
            [0.0, 0.1]
        ]
        res_asym = guard.compute_matrix_metrics(mat_asym)
        assert res_asym["chi_asym"] > 0.50

    def test_evaluate_input_validations(self):
        guard = Wave489CrossImpactEigenvalueLeadlagGuard()

        with pytest.raises(ValueError, match="spectral_radius"):
            guard.evaluate(spectral_radius=-0.1, chi_asym=0.5)

        with pytest.raises(ValueError, match="chi_asym"):
            guard.evaluate(spectral_radius=0.5, chi_asym=-0.1)

        with pytest.raises(ValueError, match="cross_buy_distortion"):
            guard.evaluate(spectral_radius=0.5, chi_asym=0.2, cross_buy_distortion=1.5)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave489CrossImpactEigenvalueLeadlagGuard()
        res = guard.evaluate(spectral_radius=0.35, chi_asym=0.20, timestamp=100.0)
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False

    def test_spectral_radius_breach(self):
        guard = Wave489CrossImpactEigenvalueLeadlagGuard(max_spectral_threshold=0.85)
        res = guard.evaluate(spectral_radius=0.92, chi_asym=0.20, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "CROSS_IMPACT_SPECTRAL_CRITICAL" in res["reason"]

    def test_lead_lag_asymmetry_breach(self):
        guard = Wave489CrossImpactEigenvalueLeadlagGuard(max_asymmetry_threshold=0.65)
        res = guard.evaluate(spectral_radius=0.50, chi_asym=0.72, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "LEAD_LAG_ASYMMETRY_BREACH" in res["reason"]

    def test_directional_cross_distortion(self):
        guard = Wave489CrossImpactEigenvalueLeadlagGuard(distortion_threshold=0.60)

        # Cross-buy distortion
        res_buy = guard.evaluate(spectral_radius=0.40, chi_asym=0.30, cross_buy_distortion=0.68, timestamp=100.0)
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False

        # Cross-sell distortion
        res_sell = guard.evaluate(spectral_radius=0.40, chi_asym=0.30, cross_sell_distortion=0.75, timestamp=100.0)
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False

    def test_cooldown_and_reset(self):
        guard = Wave489CrossImpactEigenvalueLeadlagGuard(cooldown_sec=2.0)
        res = guard.evaluate(spectral_radius=0.95, chi_asym=0.20, timestamp=10.0)
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        res_cool = guard.evaluate(spectral_radius=0.20, chi_asym=0.10, timestamp=11.0)
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate(spectral_radius=0.20, chi_asym=0.10, timestamp=11.1)
        assert res_ok["action"] == "ALLOW_ALL"


class TestWave490ImperialSupremeSovereignApexMicrostructureMasterGuard:
    """Rigorous verification of Wave 490 Imperial Supreme Sovereign Apex Master Guard."""

    def test_initialization_bounds(self):
        guard = Wave490ImperialSupremeSovereignApexMicrostructureMasterGuard(
            critical_canopy_threshold=0.65,
            dual_spike_threshold=0.85,
            cooldown_sec=2.0
        )
        assert guard.critical_canopy_threshold == 0.65
        assert guard.dual_spike_threshold == 0.85

        with pytest.raises(ValueError, match="critical_canopy_threshold"):
            Wave490ImperialSupremeSovereignApexMicrostructureMasterGuard(critical_canopy_threshold=0.30)

        with pytest.raises(ValueError, match="dual_spike_threshold"):
            Wave490ImperialSupremeSovereignApexMicrostructureMasterGuard(dual_spike_threshold=0.60)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave490ImperialSupremeSovereignApexMicrostructureMasterGuard(cooldown_sec=0.05)

    def test_input_range_validations(self):
        guard = Wave490ImperialSupremeSovereignApexMicrostructureMasterGuard()

        with pytest.raises(ValueError, match="hawkes_spectral_radius"):
            guard.evaluate(-0.1, 0.2, 0.0, 0.2, 0.2, 0.2, 0.2, 0.5)

        with pytest.raises(ValueError, match="resilience_fragility"):
            guard.evaluate(0.5, 1.5, 0.0, 0.2, 0.2, 0.2, 0.2, 0.5)

        with pytest.raises(ValueError, match="xi_skew"):
            guard.evaluate(0.5, 0.2, -1.5, 0.2, 0.2, 0.2, 0.2, 0.5)

        with pytest.raises(ValueError, match="omega_484"):
            guard.evaluate(0.5, 0.2, 0.0, 1.5, 0.2, 0.2, 0.2, 0.5)

        with pytest.raises(ValueError, match="psi_impact"):
            guard.evaluate(0.5, 0.2, 0.0, 0.2, 1.5, 0.2, 0.2, 0.5)

        with pytest.raises(ValueError, match="omega_486"):
            guard.evaluate(0.5, 0.2, 0.0, 0.2, 0.2, 1.5, 0.2, 0.5)

        with pytest.raises(ValueError, match="s_info"):
            guard.evaluate(0.5, 0.2, 0.0, 0.2, 0.2, 0.2, 1.5, 0.5)

        with pytest.raises(ValueError, match="cross_spectral_radius"):
            guard.evaluate(0.5, 0.2, 0.0, 0.2, 0.2, 0.2, 0.2, 3.5)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave490ImperialSupremeSovereignApexMicrostructureMasterGuard()
        res = guard.evaluate(
            hawkes_spectral_radius=0.30,
            resilience_fragility=0.15,
            xi_skew=0.05,
            omega_484=0.15,
            psi_impact=0.10,
            omega_486=0.15,
            s_info=0.20,
            cross_spectral_radius=0.30,
            timestamp=100.0
        )
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert res["omega_canopy"] < 0.35
        assert res["spikes_count"] == 0

    def test_supreme_canopy_breach(self):
        guard = Wave490ImperialSupremeSovereignApexMicrostructureMasterGuard(critical_canopy_threshold=0.65)
        # Elevate all 8 pillars to high levels
        res = guard.evaluate(
            hawkes_spectral_radius=0.80, # phi_1 = 0.80/0.88 = 0.909
            resilience_fragility=0.62,   # phi_2 = 0.62/0.70 = 0.886
            xi_skew=0.65,                # phi_3 = 0.65/0.75 = 0.867
            omega_484=0.58,              # phi_4 = 0.58/0.65 = 0.892
            psi_impact=0.60,             # phi_5 = 0.60/0.70 = 0.857
            omega_486=0.58,              # phi_6 = 0.58/0.65 = 0.892
            s_info=0.68,                 # phi_7 = 0.68/0.75 = 0.907
            cross_spectral_radius=0.78,  # phi_8 = 0.78/0.85 = 0.918
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "IMPERIAL_SUPREME_BREACH" in res["reason"]
        assert res["omega_canopy"] >= 0.65

    def test_dual_hazard_spike_trigger(self):
        guard = Wave490ImperialSupremeSovereignApexMicrostructureMasterGuard(
            critical_canopy_threshold=0.75,
            dual_spike_threshold=0.85
        )
        res = guard.evaluate(
            hawkes_spectral_radius=0.80, # phi_1 = 0.909 >= 0.85
            resilience_fragility=0.65,   # phi_2 = 0.928 >= 0.85
            xi_skew=0.0,
            omega_484=0.05,
            psi_impact=0.05,
            omega_486=0.05,
            s_info=0.05,
            cross_spectral_radius=0.05,
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "DUAL_HAZARD_SPIKE" in res["reason"]
        assert res["spikes_count"] >= 2

    def test_asymmetric_directional_toxicity(self):
        guard = Wave490ImperialSupremeSovereignApexMicrostructureMasterGuard()

        # Buy side toxicity (cross-buy distortion)
        res_buy = guard.evaluate(
            hawkes_spectral_radius=0.40,
            resilience_fragility=0.20,
            xi_skew=0.0,
            omega_484=0.20,
            psi_impact=0.20,
            omega_486=0.20,
            s_info=0.20,
            cross_spectral_radius=0.30,
            cross_buy_distortion=0.72, # cross_buy >= 0.60
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
            omega_486=0.20,
            s_info=0.20,
            cross_spectral_radius=0.30,
            cross_sell_distortion=0.75,
            timestamp=100.0
        )
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False

    def test_cooldown_and_reset(self):
        guard = Wave490ImperialSupremeSovereignApexMicrostructureMasterGuard(cooldown_sec=2.5)
        res = guard.evaluate(0.88, 0.70, 0.75, 0.65, 0.70, 0.65, 0.75, 0.85, timestamp=10.0)
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        res_cool = guard.evaluate(0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, timestamp=11.5)
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate(0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, timestamp=11.6)
        assert res_ok["action"] == "ALLOW_ALL"
