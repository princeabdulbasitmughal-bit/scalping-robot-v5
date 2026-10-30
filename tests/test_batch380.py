"""
Test Batch 380: Rigorous Quantitative Verification Suite
=========================================================
Covers:
  - Wave 509: High-Frequency Limit Order Book Multi-Fractal Detrended Fluctuation Analysis (MF-DFA) & Singularity Spectrum Guard
  - Wave 510: Imperial Sovereign Master Apex Yggdrasil Canopy Master Guard
"""

import pytest
import numpy as np
from wave509_lob_multifractal_dfa_singularity_spectrum_guard import Wave509LobMultifractalDfaSingularitySpectrumGuard
from wave510_imperial_sovereign_master_apex_yggdrasil_guard import Wave510ImperialSovereignMasterApexYggdrasilGuard


class TestWave509LobMultifractalDfaSingularitySpectrumGuard:
    """Rigorous verification of Wave 509 MF-DFA & Singularity Spectrum Guard."""

    def test_initialization_valid_and_invalid(self):
        guard = Wave509LobMultifractalDfaSingularitySpectrumGuard(
            max_multifractal_width=0.65,
            max_asymmetry_threshold=0.80,
            critical_fragility_threshold=0.70,
            z_mf_warning_threshold=2.00,
            cooldown_sec=2.0
        )
        assert guard.max_multifractal_width == 0.65
        assert guard.max_asymmetry_threshold == 0.80
        assert guard.critical_fragility_threshold == 0.70
        assert guard.z_mf_warning_threshold == 2.00

        with pytest.raises(ValueError, match="max_multifractal_width"):
            Wave509LobMultifractalDfaSingularitySpectrumGuard(max_multifractal_width=0.20)

        with pytest.raises(ValueError, match="max_asymmetry_threshold"):
            Wave509LobMultifractalDfaSingularitySpectrumGuard(max_asymmetry_threshold=0.40)

        with pytest.raises(ValueError, match="critical_fragility_threshold"):
            Wave509LobMultifractalDfaSingularitySpectrumGuard(critical_fragility_threshold=0.30)

        with pytest.raises(ValueError, match="z_mf_warning_threshold"):
            Wave509LobMultifractalDfaSingularitySpectrumGuard(z_mf_warning_threshold=0.50)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave509LobMultifractalDfaSingularitySpectrumGuard(cooldown_sec=0.05)

    def test_compute_mf_dfa_scaling(self):
        guard = Wave509LobMultifractalDfaSingularitySpectrumGuard()

        # Insufficient data
        with pytest.raises(ValueError, match="at least 16 observations"):
            guard.compute_mf_dfa_scaling([1.0, 2.0, 3.0])

        # Random walk series
        np.random.seed(42)
        rw = np.cumsum(np.random.normal(0, 1.0, size=64)).tolist()
        res_rw = guard.compute_mf_dfa_scaling(rw)
        assert "h_q" in res_rw
        assert "delta_h" in res_rw
        assert 0.0 <= res_rw["delta_h"] <= 1.50

    def test_evaluate_input_validations(self):
        guard = Wave509LobMultifractalDfaSingularitySpectrumGuard()

        with pytest.raises(ValueError, match="delta_h"):
            guard.evaluate(delta_h=-0.1)

        with pytest.raises(ValueError, match="delta_h"):
            guard.evaluate(delta_h=3.5)

        with pytest.raises(ValueError, match="a_mf"):
            guard.evaluate(delta_h=0.2, a_mf=1.5)

        with pytest.raises(ValueError, match="z_mf"):
            guard.evaluate(delta_h=0.2, a_mf=0.0, z_mf=15.0)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave509LobMultifractalDfaSingularitySpectrumGuard()
        # Normal monofractal / low intermittency market
        res = guard.evaluate(delta_h=0.15, a_mf=0.05, z_mf=0.1, timestamp=100.0)
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert res["psi_mf"] == 0.0

    def test_critical_multifractal_intermittency_breaker(self):
        guard = Wave509LobMultifractalDfaSingularitySpectrumGuard(max_multifractal_width=0.65)
        res = guard.evaluate(delta_h=0.72, a_mf=0.10, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "MULTIFRACTAL_INTERMITTENCY_CRITICAL" in res["reason"]

    def test_critical_multifractal_fragility_breach(self):
        guard = Wave509LobMultifractalDfaSingularitySpectrumGuard(critical_fragility_threshold=0.70)
        # Elevated delta_h (0.60) -> phi_delta = (0.60 - 0.25)/0.40 = 0.875
        # Elevated a_mf (0.65) -> phi_asym = (0.65 - 0.20)/0.60 = 0.750
        # psi_mf = 0.5*0.875 + 0.5*0.750 = 0.8125 >= 0.70
        res = guard.evaluate(delta_h=0.60, a_mf=0.65, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "MULTIFRACTAL_FRAGILITY_CRITICAL" in res["reason"]

    def test_critical_spectrum_asymmetry_breaker(self):
        guard = Wave509LobMultifractalDfaSingularitySpectrumGuard(max_asymmetry_threshold=0.80)
        res = guard.evaluate(delta_h=0.30, a_mf=-0.88, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "MULTIFRACTAL_SPECTRUM_ASYMMETRY_CRITICAL" in res["reason"]

    def test_asymmetric_directional_toxicity_overextensions(self):
        guard = Wave509LobMultifractalDfaSingularitySpectrumGuard(z_mf_warning_threshold=2.00)

        # Parabolic extreme tail meltup (a_mf <= -0.50 and z_mf >= 2.0)
        res_buy = guard.evaluate(delta_h=0.30, a_mf=-0.60, z_mf=2.40, timestamp=100.0)
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False
        assert "MULTIFRACTAL_PARABOLIC_TAIL_EXHAUSTION" in res_buy["reason"]

        # Liquidation extreme tail cascade (a_mf <= -0.50 and z_mf <= -2.0)
        res_sell = guard.evaluate(delta_h=0.30, a_mf=-0.60, z_mf=-2.40, timestamp=100.0)
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False
        assert "MULTIFRACTAL_LIQUIDATION_TAIL_CASCADE" in res_sell["reason"]

    def test_cooldown_and_reset(self):
        guard = Wave509LobMultifractalDfaSingularitySpectrumGuard(cooldown_sec=2.0)
        res = guard.evaluate(delta_h=0.85, timestamp=10.0)
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        res_cool = guard.evaluate(delta_h=0.10, timestamp=11.0)
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate(delta_h=0.10, timestamp=11.1)
        assert res_ok["action"] == "ALLOW_ALL"


class TestWave510ImperialSovereignMasterApexYggdrasilGuard:
    """Rigorous verification of Wave 510 Imperial Yggdrasil Master Guard."""

    def test_initialization_bounds(self):
        guard = Wave510ImperialSovereignMasterApexYggdrasilGuard(
            critical_canopy_threshold=0.65,
            dual_spike_threshold=0.85,
            cooldown_sec=2.0
        )
        assert guard.critical_canopy_threshold == 0.65
        assert guard.dual_spike_threshold == 0.85

        with pytest.raises(ValueError, match="critical_canopy_threshold"):
            Wave510ImperialSovereignMasterApexYggdrasilGuard(critical_canopy_threshold=0.30)

        with pytest.raises(ValueError, match="dual_spike_threshold"):
            Wave510ImperialSovereignMasterApexYggdrasilGuard(dual_spike_threshold=0.60)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave510ImperialSovereignMasterApexYggdrasilGuard(cooldown_sec=0.05)

    def test_input_range_validations(self):
        guard = Wave510ImperialSovereignMasterApexYggdrasilGuard()

        with pytest.raises(ValueError, match="hawkes_spectral_radius"):
            guard.evaluate(-0.1, 0.2, 0.0, 0.2, 0.2, 0.2, 0.2, 0.5, 0.0, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2)

        with pytest.raises(ValueError, match="psi_mf"):
            guard.evaluate(0.5, 0.2, 0.0, 0.2, 0.2, 0.2, 0.2, 0.5, 0.0, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 1.5)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave510ImperialSovereignMasterApexYggdrasilGuard()
        res = guard.evaluate(
            hawkes_spectral_radius=0.30,
            resilience_fragility=0.15,
            xi_skew=0.05,
            omega_484=0.15,
            psi_impact=0.10,
            omega_486=0.15,
            s_info=0.20,
            cross_spectral_radius=0.30,
            i_pressure=0.05,
            psi_momentum=0.10,
            psi_jump=0.10,
            psi_entropy=0.10,
            psi_wavelet=0.10,
            psi_sniping=0.10,
            psi_memory=0.10,
            psi_km=0.10,
            psi_mf=0.10,
            timestamp=100.0
        )
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert res["omega_canopy"] < 0.35
        assert res["spikes_count"] == 0

    def test_yggdrasil_canopy_breach(self):
        guard = Wave510ImperialSovereignMasterApexYggdrasilGuard(critical_canopy_threshold=0.65)
        # All 18 pillars elevated
        res = guard.evaluate(
            hawkes_spectral_radius=0.80, # phi_1 = 0.909
            resilience_fragility=0.62,   # phi_2 = 0.886
            xi_skew=0.65,                # phi_3 = 0.867
            omega_484=0.58,              # phi_4 = 0.892
            psi_impact=0.60,             # phi_5 = 0.857
            omega_486=0.58,              # phi_6 = 0.892
            s_info=0.68,                 # phi_7 = 0.907
            cross_spectral_radius=0.78,  # phi_8 = 0.918
            i_pressure=0.68,             # phi_9 = 0.907
            psi_momentum=0.62,           # phi_11 = 0.886
            psi_jump=0.62,               # phi_12 = 0.886
            psi_entropy=0.62,            # phi_13 = 0.886
            psi_wavelet=0.62,            # phi_14 = 0.886
            psi_sniping=0.62,            # phi_15 = 0.886
            psi_memory=0.62,             # phi_16 = 0.886
            psi_km=0.62,                 # phi_17 = 0.886
            psi_mf=0.62,                 # phi_18 = 0.886
            r_bid=3.60,                  # phi_10 = 0.900
            r_ask=1.0,
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "IMPERIAL_YGGDRASIL_BREACH" in res["reason"]
        assert res["omega_canopy"] >= 0.65

    def test_dual_hazard_spike_trigger(self):
        guard = Wave510ImperialSovereignMasterApexYggdrasilGuard(
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
            i_pressure=0.05,
            psi_momentum=0.05,
            psi_jump=0.05,
            psi_entropy=0.05,
            psi_wavelet=0.05,
            psi_sniping=0.05,
            psi_memory=0.05,
            psi_km=0.05,
            psi_mf=0.05,
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "DUAL_HAZARD_SPIKE" in res["reason"]
        assert res["spikes_count"] >= 2

    def test_asymmetric_directional_toxicity(self):
        guard = Wave510ImperialSovereignMasterApexYggdrasilGuard()

        # Buy side toxicity via multifractal meltup (a_mf <= -0.50 and z_mf >= 2.00)
        res_buy = guard.evaluate(
            hawkes_spectral_radius=0.40,
            resilience_fragility=0.20,
            xi_skew=0.0,
            omega_484=0.20,
            psi_impact=0.20,
            omega_486=0.20,
            s_info=0.20,
            cross_spectral_radius=0.30,
            i_pressure=0.0,
            psi_momentum=0.20,
            psi_jump=0.20,
            psi_entropy=0.20,
            psi_wavelet=0.20,
            psi_sniping=0.20,
            psi_memory=0.20,
            psi_km=0.20,
            psi_mf=0.20,
            a_mf=-0.60,
            z_mf=2.40,
            timestamp=100.0
        )
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False

        # Sell side toxicity via multifractal crash (a_mf <= -0.50 and z_mf <= -2.00)
        res_sell = guard.evaluate(
            hawkes_spectral_radius=0.40,
            resilience_fragility=0.20,
            xi_skew=0.0,
            omega_484=0.20,
            psi_impact=0.20,
            omega_486=0.20,
            s_info=0.20,
            cross_spectral_radius=0.30,
            i_pressure=0.0,
            psi_momentum=0.20,
            psi_jump=0.20,
            psi_entropy=0.20,
            psi_wavelet=0.20,
            psi_sniping=0.20,
            psi_memory=0.20,
            psi_km=0.20,
            psi_mf=0.20,
            a_mf=-0.60,
            z_mf=-2.40,
            timestamp=100.0
        )
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False

    def test_cooldown_and_reset(self):
        guard = Wave510ImperialSovereignMasterApexYggdrasilGuard(cooldown_sec=2.5)
        res = guard.evaluate(
            0.88, 0.70, 0.75, 0.65, 0.70, 0.65, 0.75, 0.85, 0.75, 0.70, 0.70, 0.70, 0.70, 0.70, 0.70, 0.70, 0.70,
            timestamp=10.0
        )
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        res_cool = guard.evaluate(
            0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1,
            timestamp=11.5
        )
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate(
            0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1,
            timestamp=11.6
        )
        assert res_ok["action"] == "ALLOW_ALL"
