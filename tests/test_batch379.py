"""
Test Batch 379: Rigorous Quantitative Verification Suite
=========================================================
Covers:
  - Wave 507: High-Frequency Limit Order Book Non-Equilibrium Kramers-Moyal Expansion & Drift-Diffusion Jump Singularity Guard
  - Wave 508: Imperial Sovereign Master Apex Ragnarok Canopy Master Guard
"""

import pytest
import numpy as np
from wave507_lob_kramers_moyal_jump_singularity_guard import Wave507LobKramersMoyalJumpSingularityGuard
from wave508_imperial_sovereign_master_apex_ragnarok_guard import Wave508ImperialSovereignMasterApexRagnarokGuard


class TestWave507LobKramersMoyalJumpSingularityGuard:
    """Rigorous verification of Wave 507 Kramers-Moyal Expansion & Drift-Diffusion Jump Guard."""

    def test_initialization_valid_and_invalid(self):
        guard = Wave507LobKramersMoyalJumpSingularityGuard(
            max_pawula_threshold=3.50,
            max_drift_threshold=1.20,
            critical_fragility_threshold=0.70,
            drift_warning_threshold=0.75,
            cooldown_sec=2.0
        )
        assert guard.max_pawula_threshold == 3.50
        assert guard.max_drift_threshold == 1.20
        assert guard.critical_fragility_threshold == 0.70
        assert guard.drift_warning_threshold == 0.75

        with pytest.raises(ValueError, match="max_pawula_threshold"):
            Wave507LobKramersMoyalJumpSingularityGuard(max_pawula_threshold=1.50)

        with pytest.raises(ValueError, match="max_drift_threshold"):
            Wave507LobKramersMoyalJumpSingularityGuard(max_drift_threshold=0.40)

        with pytest.raises(ValueError, match="critical_fragility_threshold"):
            Wave507LobKramersMoyalJumpSingularityGuard(critical_fragility_threshold=0.30)

        with pytest.raises(ValueError, match="drift_warning_threshold"):
            Wave507LobKramersMoyalJumpSingularityGuard(drift_warning_threshold=0.10)

        with pytest.raises(ValueError, match="drift_warning_threshold must be strictly less"):
            Wave507LobKramersMoyalJumpSingularityGuard(drift_warning_threshold=1.30, max_drift_threshold=1.20)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave507LobKramersMoyalJumpSingularityGuard(cooldown_sec=0.05)

    def test_calculate_km_coefficients(self):
        guard = Wave507LobKramersMoyalJumpSingularityGuard()

        # Insufficient data
        with pytest.raises(ValueError, match="at least 6 increments"):
            guard.calculate_km_coefficients([0.1, -0.2, 0.3])

        with pytest.raises(ValueError, match="tau_sec must be strictly positive"):
            guard.calculate_km_coefficients([0.1] * 10, tau_sec=0.0)

        # Constant increments (low variance)
        res_const = guard.calculate_km_coefficients([0.05] * 10, tau_sec=0.1)
        assert "d1" in res_const
        assert "d2" in res_const
        assert "d4" in res_const
        assert "q_pawula" in res_const
        assert res_const["d1"] > 0.0

        # Normal random walk increments
        np.random.seed(42)
        increments = np.random.normal(0.0, 0.5, size=50).tolist()
        res_norm = guard.calculate_km_coefficients(increments, tau_sec=0.1)
        assert 0.0 <= res_norm["q_pawula"] <= 20.0

    def test_evaluate_input_validations(self):
        guard = Wave507LobKramersMoyalJumpSingularityGuard()

        with pytest.raises(ValueError, match="q_pawula"):
            guard.evaluate(q_pawula=-1.0)

        with pytest.raises(ValueError, match="q_pawula"):
            guard.evaluate(q_pawula=25.0)

        with pytest.raises(ValueError, match="d1_drift"):
            guard.evaluate(q_pawula=1.0, d1_drift=15.0)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave507LobKramersMoyalJumpSingularityGuard()
        # Normal calm diffusive market: low pawula ratio and low drift
        res = guard.evaluate(q_pawula=1.0, d1_drift=0.10, timestamp=100.0)
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert res["psi_km"] == 0.0

    def test_critical_pawula_jump_singularity_breaker(self):
        guard = Wave507LobKramersMoyalJumpSingularityGuard(max_pawula_threshold=3.50)
        res = guard.evaluate(q_pawula=4.20, d1_drift=0.10, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "KRAMERS_MOYAL_JUMP_SINGULARITY" in res["reason"]

    def test_critical_km_fragility_breach(self):
        guard = Wave507LobKramersMoyalJumpSingularityGuard(critical_fragility_threshold=0.70)
        # Elevated pawula ratio (3.0) -> phi_q = (3.0 - 1.5)/2.0 = 0.75
        # Elevated drift (1.20) -> phi_drift = (1.20 - 0.5)/1.0 = 0.70
        # psi_km = 0.5*0.75 + 0.5*0.70 = 0.725 >= 0.70
        res = guard.evaluate(q_pawula=3.00, d1_drift=1.15, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "KM_FRAGILITY_CRITICAL" in res["reason"]

    def test_turbulent_drift_runaway_breaker(self):
        guard = Wave507LobKramersMoyalJumpSingularityGuard(max_drift_threshold=1.20)
        res = guard.evaluate(q_pawula=1.50, d1_drift=1.35, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "TURBULENT_DRIFT_RUNAWAY" in res["reason"]

    def test_asymmetric_directional_drift_overextensions(self):
        guard = Wave507LobKramersMoyalJumpSingularityGuard(
            max_drift_threshold=1.20,
            drift_warning_threshold=0.75
        )

        # Parabolic upward drift exhaustion
        res_buy = guard.evaluate(q_pawula=1.20, d1_drift=0.85, timestamp=100.0)
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False
        assert "PARABOLIC_DRIFT_EXHAUSTION" in res_buy["reason"]

        # Liquidation downward drift cascade
        res_sell = guard.evaluate(q_pawula=1.20, d1_drift=-0.85, timestamp=100.0)
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False
        assert "LIQUIDATION_DRIFT_CASCADE" in res_sell["reason"]

    def test_cooldown_and_reset(self):
        guard = Wave507LobKramersMoyalJumpSingularityGuard(cooldown_sec=2.0)
        res = guard.evaluate(q_pawula=5.0, timestamp=10.0)
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        res_cool = guard.evaluate(q_pawula=1.0, timestamp=11.0)
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate(q_pawula=1.0, timestamp=11.1)
        assert res_ok["action"] == "ALLOW_ALL"


class TestWave508ImperialSovereignMasterApexRagnarokGuard:
    """Rigorous verification of Wave 508 Imperial Ragnarok Master Guard."""

    def test_initialization_bounds(self):
        guard = Wave508ImperialSovereignMasterApexRagnarokGuard(
            critical_canopy_threshold=0.65,
            dual_spike_threshold=0.85,
            cooldown_sec=2.0
        )
        assert guard.critical_canopy_threshold == 0.65
        assert guard.dual_spike_threshold == 0.85

        with pytest.raises(ValueError, match="critical_canopy_threshold"):
            Wave508ImperialSovereignMasterApexRagnarokGuard(critical_canopy_threshold=0.30)

        with pytest.raises(ValueError, match="dual_spike_threshold"):
            Wave508ImperialSovereignMasterApexRagnarokGuard(dual_spike_threshold=0.60)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave508ImperialSovereignMasterApexRagnarokGuard(cooldown_sec=0.05)

    def test_input_range_validations(self):
        guard = Wave508ImperialSovereignMasterApexRagnarokGuard()

        with pytest.raises(ValueError, match="hawkes_spectral_radius"):
            guard.evaluate(-0.1, 0.2, 0.0, 0.2, 0.2, 0.2, 0.2, 0.5, 0.0, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2)

        with pytest.raises(ValueError, match="psi_km"):
            guard.evaluate(0.5, 0.2, 0.0, 0.2, 0.2, 0.2, 0.2, 0.5, 0.0, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 1.5)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave508ImperialSovereignMasterApexRagnarokGuard()
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
            timestamp=100.0
        )
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert res["omega_canopy"] < 0.35
        assert res["spikes_count"] == 0

    def test_ragnarok_canopy_breach(self):
        guard = Wave508ImperialSovereignMasterApexRagnarokGuard(critical_canopy_threshold=0.65)
        # All 17 pillars elevated
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
            r_bid=3.60,                  # phi_10 = 0.900
            r_ask=1.0,
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "IMPERIAL_RAGNAROK_BREACH" in res["reason"]
        assert res["omega_canopy"] >= 0.65

    def test_dual_hazard_spike_trigger(self):
        guard = Wave508ImperialSovereignMasterApexRagnarokGuard(
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
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "DUAL_HAZARD_SPIKE" in res["reason"]
        assert res["spikes_count"] >= 2

    def test_asymmetric_directional_toxicity(self):
        guard = Wave508ImperialSovereignMasterApexRagnarokGuard()

        # Buy side toxicity via d1_drift >= 0.75
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
            d1_drift=0.85, # d1_drift >= 0.75
            timestamp=100.0
        )
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False

        # Sell side toxicity via d1_drift <= -0.75
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
            d1_drift=-0.85, # d1_drift <= -0.75
            timestamp=100.0
        )
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False

    def test_cooldown_and_reset(self):
        guard = Wave508ImperialSovereignMasterApexRagnarokGuard(cooldown_sec=2.5)
        res = guard.evaluate(
            0.88, 0.70, 0.75, 0.65, 0.70, 0.65, 0.75, 0.85, 0.75, 0.70, 0.70, 0.70, 0.70, 0.70, 0.70, 0.70,
            timestamp=10.0
        )
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        res_cool = guard.evaluate(
            0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1,
            timestamp=11.5
        )
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate(
            0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1,
            timestamp=11.6
        )
        assert res_ok["action"] == "ALLOW_ALL"

