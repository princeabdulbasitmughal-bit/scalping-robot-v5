"""
Test Batch 372: Rigorous Quantitative Verification Suite
=========================================================
Covers:
  - Wave 493: Microstructure Hidden Liquidity Iceberg Detector & Adverse Selection Replenishment Guard
  - Wave 494: Imperial Sovereign Supreme Microstructure Apex Citadel Canopy Guard
"""

import pytest
import numpy as np
from wave493_hidden_iceberg_adverse_replenishment_guard import Wave493HiddenIcebergAdverseReplenishmentGuard
from wave494_imperial_sovereign_supreme_microstructure_apex_citadel_guard import Wave494ImperialSovereignSupremeMicrostructureApexCitadelGuard


class TestWave493HiddenIcebergAdverseReplenishmentGuard:
    """Rigorous verification of Wave 493 Hidden Iceberg Guard."""

    def test_initialization_valid_and_invalid(self):
        guard = Wave493HiddenIcebergAdverseReplenishmentGuard(
            iceberg_detect_threshold=2.50,
            critical_iceberg_threshold=5.0,
            cooldown_sec=2.0
        )
        assert guard.iceberg_detect_threshold == 2.50
        assert guard.critical_iceberg_threshold == 5.0

        with pytest.raises(ValueError, match="iceberg_detect_threshold"):
            Wave493HiddenIcebergAdverseReplenishmentGuard(iceberg_detect_threshold=0.80)

        with pytest.raises(ValueError, match="critical_iceberg_threshold"):
            Wave493HiddenIcebergAdverseReplenishmentGuard(critical_iceberg_threshold=2.0)

        with pytest.raises(ValueError, match="strictly less"):
            Wave493HiddenIcebergAdverseReplenishmentGuard(iceberg_detect_threshold=4.0, critical_iceberg_threshold=3.5)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave493HiddenIcebergAdverseReplenishmentGuard(cooldown_sec=0.05)

    def test_compute_iceberg_ratios(self):
        guard = Wave493HiddenIcebergAdverseReplenishmentGuard()

        # Negative volume
        with pytest.raises(ValueError, match="non-negative"):
            guard.compute_iceberg_ratios(-10.0, 10.0, 10.0, 10.0)

        # Standard calculation: exec=300, vis=100 -> hidden=200 -> ratio=2.0
        res = guard.compute_iceberg_ratios(300.0, 100.0, 100.0, 100.0)
        assert abs(res["r_bid"] - 2.0) < 1e-4
        assert abs(res["r_ask"] - 0.0) < 1e-4

    def test_evaluate_input_validations(self):
        guard = Wave493HiddenIcebergAdverseReplenishmentGuard()

        with pytest.raises(ValueError, match="r_bid"):
            guard.evaluate(r_bid=-0.5, r_ask=1.0)

        with pytest.raises(ValueError, match="r_ask"):
            guard.evaluate(r_bid=1.0, r_ask=-0.5)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave493HiddenIcebergAdverseReplenishmentGuard()
        res = guard.evaluate(r_bid=0.50, r_ask=0.50, timestamp=100.0)
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False

    def test_extreme_iceberg_breach(self):
        guard = Wave493HiddenIcebergAdverseReplenishmentGuard(critical_iceberg_threshold=5.0)
        res = guard.evaluate(r_bid=5.50, r_ask=1.0, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "EXTREME_ICEBERG_BREACH" in res["reason"]

    def test_iceberg_pin_halt(self):
        guard = Wave493HiddenIcebergAdverseReplenishmentGuard(iceberg_detect_threshold=2.50)
        res = guard.evaluate(r_bid=2.80, r_ask=3.0, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "ICEBERG_PIN_HALT" in res["reason"]

    def test_directional_iceberg_absorption(self):
        guard = Wave493HiddenIcebergAdverseReplenishmentGuard(iceberg_detect_threshold=2.50)

        # Ask ceiling iceberg -> BLOCK_BUY
        res_buy = guard.evaluate(r_bid=0.50, r_ask=2.80, timestamp=100.0)
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False

        # Bid floor iceberg -> BLOCK_SELL
        res_sell = guard.evaluate(r_bid=2.80, r_ask=0.50, timestamp=100.0)
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False

    def test_cooldown_and_reset(self):
        guard = Wave493HiddenIcebergAdverseReplenishmentGuard(cooldown_sec=2.0)
        res = guard.evaluate(r_bid=6.0, r_ask=0.0, timestamp=10.0)
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        res_cool = guard.evaluate(r_bid=0.1, r_ask=0.1, timestamp=11.0)
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate(r_bid=0.1, r_ask=0.1, timestamp=11.1)
        assert res_ok["action"] == "ALLOW_ALL"


class TestWave494ImperialSovereignSupremeMicrostructureApexCitadelGuard:
    """Rigorous verification of Wave 494 Imperial Citadel Master Guard."""

    def test_initialization_bounds(self):
        guard = Wave494ImperialSovereignSupremeMicrostructureApexCitadelGuard(
            critical_canopy_threshold=0.65,
            dual_spike_threshold=0.85,
            cooldown_sec=2.0
        )
        assert guard.critical_canopy_threshold == 0.65
        assert guard.dual_spike_threshold == 0.85

        with pytest.raises(ValueError, match="critical_canopy_threshold"):
            Wave494ImperialSovereignSupremeMicrostructureApexCitadelGuard(critical_canopy_threshold=0.30)

        with pytest.raises(ValueError, match="dual_spike_threshold"):
            Wave494ImperialSovereignSupremeMicrostructureApexCitadelGuard(dual_spike_threshold=0.60)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave494ImperialSovereignSupremeMicrostructureApexCitadelGuard(cooldown_sec=0.05)

    def test_input_range_validations(self):
        guard = Wave494ImperialSovereignSupremeMicrostructureApexCitadelGuard()

        with pytest.raises(ValueError, match="hawkes_spectral_radius"):
            guard.evaluate(-0.1, 0.2, 0.0, 0.2, 0.2, 0.2, 0.2, 0.5, 0.0)

        with pytest.raises(ValueError, match="r_bid and r_ask"):
            guard.evaluate(0.5, 0.2, 0.0, 0.2, 0.2, 0.2, 0.2, 0.5, 0.0, r_bid=-1.0)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave494ImperialSovereignSupremeMicrostructureApexCitadelGuard()
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
            r_bid=0.50,
            r_ask=0.50,
            timestamp=100.0
        )
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert res["omega_canopy"] < 0.35
        assert res["spikes_count"] == 0

    def test_citadel_canopy_breach(self):
        guard = Wave494ImperialSovereignSupremeMicrostructureApexCitadelGuard(critical_canopy_threshold=0.65)
        # All 10 pillars elevated to high values
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
            r_bid=3.60,                  # phi_10 = 3.60/4.0 = 0.900
            r_ask=1.0,
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "IMPERIAL_CITADEL_BREACH" in res["reason"]
        assert res["omega_canopy"] >= 0.65

    def test_dual_hazard_spike_trigger(self):
        guard = Wave494ImperialSovereignSupremeMicrostructureApexCitadelGuard(
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
            r_bid=0.10,
            r_ask=0.10,
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "DUAL_HAZARD_SPIKE" in res["reason"]
        assert res["spikes_count"] >= 2

    def test_asymmetric_directional_toxicity(self):
        guard = Wave494ImperialSovereignSupremeMicrostructureApexCitadelGuard()

        # Buy side toxicity (r_ask >= 2.50)
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
            r_bid=0.20,
            r_ask=2.80, # r_ask >= 2.50
            timestamp=100.0
        )
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False

        # Sell side toxicity (r_bid >= 2.50)
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
            r_bid=2.80, # r_bid >= 2.50
            r_ask=0.20,
            timestamp=100.0
        )
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False

    def test_cooldown_and_reset(self):
        guard = Wave494ImperialSovereignSupremeMicrostructureApexCitadelGuard(cooldown_sec=2.5)
        res = guard.evaluate(0.88, 0.70, 0.75, 0.65, 0.70, 0.65, 0.75, 0.85, 0.75, 3.5, 3.5, timestamp=10.0)
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        res_cool = guard.evaluate(0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.0, 0.1, 0.1, timestamp=11.5)
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate(0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.0, 0.1, 0.1, timestamp=11.6)
        assert res_ok["action"] == "ALLOW_ALL"
