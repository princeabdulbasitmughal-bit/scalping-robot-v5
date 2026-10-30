"""
Test Batch 375: Historical Quantitative Milestone Verification Suite
===================================================================
Covers:
  - Wave 499: High-Frequency Limit Order Book Shannon & Tsallis Information Entropy Decay Guard
  - Wave 500: Imperial Sovereign Grand Jubilee Apex Pantheon Master Canopy Fortress Guard
"""

import pytest
import numpy as np
from wave499_lob_information_entropy_decay_guard import Wave499LobInformationEntropyDecayGuard
from wave500_imperial_sovereign_grand_jubilee_apex_pantheon_master_guard import Wave500ImperialSovereignGrandJubileeApexPantheonMasterGuard


class TestWave499LobInformationEntropyDecayGuard:
    """Rigorous verification of Wave 499 LOB Information Entropy Guard."""

    def test_initialization_valid_and_invalid(self):
        guard = Wave499LobInformationEntropyDecayGuard(
            min_entropy_threshold=0.35,
            max_entropy_threshold=0.92,
            critical_fragility_threshold=0.75,
            max_decay_rate_threshold=1.20,
            cooldown_sec=2.0
        )
        assert guard.min_entropy_threshold == 0.35
        assert guard.max_entropy_threshold == 0.92

        with pytest.raises(ValueError, match="min_entropy_threshold"):
            Wave499LobInformationEntropyDecayGuard(min_entropy_threshold=0.10)

        with pytest.raises(ValueError, match="max_entropy_threshold"):
            Wave499LobInformationEntropyDecayGuard(max_entropy_threshold=0.60)

        with pytest.raises(ValueError, match="critical_fragility_threshold"):
            Wave499LobInformationEntropyDecayGuard(critical_fragility_threshold=0.40)

        with pytest.raises(ValueError, match="max_decay_rate_threshold"):
            Wave499LobInformationEntropyDecayGuard(max_decay_rate_threshold=0.20)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave499LobInformationEntropyDecayGuard(cooldown_sec=0.05)

    def test_compute_orderbook_entropy(self):
        guard = Wave499LobInformationEntropyDecayGuard()

        # Insufficient levels
        with pytest.raises(ValueError, match="at least 2 depth levels"):
            guard.compute_orderbook_entropy([100.0])

        # Negative volume
        with pytest.raises(ValueError, match="non-negative"):
            guard.compute_orderbook_entropy([100.0, -50.0])

        # Uniform depth distribution (maximum Shannon entropy = 1.0)
        res_uniform = guard.compute_orderbook_entropy([100.0, 100.0, 100.0, 100.0])
        assert abs(res_uniform["h_norm"] - 1.0) < 1e-4

        # Highly concentrated depth distribution (pinned at level 0)
        res_pinned = guard.compute_orderbook_entropy([1000.0, 0.01, 0.01, 0.01])
        assert res_pinned["h_norm"] < 0.15

        # All zero volumes
        res_zero = guard.compute_orderbook_entropy([0.0, 0.0, 0.0])
        assert res_zero["h_norm"] == 0.0

    def test_evaluate_input_validations(self):
        guard = Wave499LobInformationEntropyDecayGuard()

        with pytest.raises(ValueError, match="h_norm"):
            guard.evaluate(h_norm=1.5)

        with pytest.raises(ValueError, match="h_bid"):
            guard.evaluate(h_norm=0.7, h_bid=-0.1)

        with pytest.raises(ValueError, match="h_ask"):
            guard.evaluate(h_norm=0.7, h_ask=1.2)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave499LobInformationEntropyDecayGuard()
        res = guard.evaluate(h_norm=0.70, h_bid=0.70, h_ask=0.70, timestamp=100.0)
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert res["psi_entropy"] == 0.0

    def test_critical_entropy_collapse(self):
        guard = Wave499LobInformationEntropyDecayGuard(min_entropy_threshold=0.35)
        res = guard.evaluate(h_norm=0.25, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "LOB_ENTROPY_COLLAPSE" in res["reason"]

    def test_critical_entropy_disorganization(self):
        guard = Wave499LobInformationEntropyDecayGuard(max_entropy_threshold=0.92)
        res = guard.evaluate(h_norm=0.95, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "LOB_ENTROPY_DISORGANIZATION" in res["reason"]

    def test_critical_decay_velocity(self):
        guard = Wave499LobInformationEntropyDecayGuard(max_decay_rate_threshold=1.20)
        # First reading at 100.0s
        guard.evaluate(h_norm=0.85, timestamp=100.0)
        # Second reading 0.1s later with severe sudden shift: 0.85 -> 0.65 (rate = 2.0/s)
        res = guard.evaluate(h_norm=0.65, timestamp=100.1)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "ENTROPY_DECAY_VELOCITY_CRITICAL" in res["reason"]

    def test_asymmetric_directional_vacuums(self):
        guard = Wave499LobInformationEntropyDecayGuard()

        # Bid side vacuum (h_bid <= 0.35, h_ask >= 0.60)
        res_bid = guard.evaluate(h_norm=0.68, h_bid=0.28, h_ask=0.72, timestamp=100.0)
        assert res_bid["action"] == "BLOCK_SELL"
        assert res_bid["circuit_breaker"] is False

        # Ask side vacuum (h_ask <= 0.35, h_bid >= 0.60)
        res_ask = guard.evaluate(h_norm=0.68, h_bid=0.72, h_ask=0.28, timestamp=100.0)
        assert res_ask["action"] == "BLOCK_BUY"
        assert res_ask["circuit_breaker"] is False

    def test_cooldown_and_reset(self):
        guard = Wave499LobInformationEntropyDecayGuard(cooldown_sec=2.0)
        res = guard.evaluate(h_norm=0.20, timestamp=10.0)
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        res_cool = guard.evaluate(h_norm=0.70, timestamp=11.0)
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate(h_norm=0.70, timestamp=11.1)
        assert res_ok["action"] == "ALLOW_ALL"


class TestWave500ImperialSovereignGrandJubileeApexPantheonMasterGuard:
    """Rigorous verification of Historic Wave 500 Imperial Pantheon Master Guard."""

    def test_initialization_bounds(self):
        guard = Wave500ImperialSovereignGrandJubileeApexPantheonMasterGuard(
            critical_canopy_threshold=0.65,
            dual_spike_threshold=0.85,
            cooldown_sec=2.0
        )
        assert guard.critical_canopy_threshold == 0.65
        assert guard.dual_spike_threshold == 0.85

        with pytest.raises(ValueError, match="critical_canopy_threshold"):
            Wave500ImperialSovereignGrandJubileeApexPantheonMasterGuard(critical_canopy_threshold=0.30)

        with pytest.raises(ValueError, match="dual_spike_threshold"):
            Wave500ImperialSovereignGrandJubileeApexPantheonMasterGuard(dual_spike_threshold=0.60)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave500ImperialSovereignGrandJubileeApexPantheonMasterGuard(cooldown_sec=0.05)

    def test_input_range_validations(self):
        guard = Wave500ImperialSovereignGrandJubileeApexPantheonMasterGuard()

        with pytest.raises(ValueError, match="hawkes_spectral_radius"):
            guard.evaluate(-0.1, 0.2, 0.0, 0.2, 0.2, 0.2, 0.2, 0.5, 0.0, 0.2, 0.2, 0.2)

        with pytest.raises(ValueError, match="psi_entropy"):
            guard.evaluate(0.5, 0.2, 0.0, 0.2, 0.2, 0.2, 0.2, 0.5, 0.0, 0.2, 0.2, 1.5)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave500ImperialSovereignGrandJubileeApexPantheonMasterGuard()
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
            timestamp=100.0
        )
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert res["omega_canopy"] < 0.35
        assert res["spikes_count"] == 0

    def test_pantheon_canopy_breach(self):
        guard = Wave500ImperialSovereignGrandJubileeApexPantheonMasterGuard(critical_canopy_threshold=0.65)
        # All 13 pillars elevated
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
            r_bid=3.60,                  # phi_10 = 0.900
            r_ask=1.0,
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "IMPERIAL_PANTHEON_BREACH" in res["reason"]
        assert res["omega_canopy"] >= 0.65

    def test_dual_hazard_spike_trigger(self):
        guard = Wave500ImperialSovereignGrandJubileeApexPantheonMasterGuard(
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
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "DUAL_HAZARD_SPIKE" in res["reason"]
        assert res["spikes_count"] >= 2

    def test_asymmetric_directional_toxicity(self):
        guard = Wave500ImperialSovereignGrandJubileeApexPantheonMasterGuard()

        # Buy side toxicity via ask-side entropy collapse (h_ask <= 0.35)
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
            h_ask=0.25, # h_ask <= 0.35
            timestamp=100.0
        )
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False

        # Sell side toxicity via bid-side entropy collapse (h_bid <= 0.35)
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
            h_bid=0.25, # h_bid <= 0.35
            timestamp=100.0
        )
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False

    def test_cooldown_and_reset(self):
        guard = Wave500ImperialSovereignGrandJubileeApexPantheonMasterGuard(cooldown_sec=2.5)
        res = guard.evaluate(
            0.88, 0.70, 0.75, 0.65, 0.70, 0.65, 0.75, 0.85, 0.75, 0.70, 0.70, 0.70,
            timestamp=10.0
        )
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        res_cool = guard.evaluate(
            0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.0, 0.1, 0.1, 0.1,
            timestamp=11.5
        )
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate(
            0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.0, 0.1, 0.1, 0.1,
            timestamp=11.6
        )
        assert res_ok["action"] == "ALLOW_ALL"
