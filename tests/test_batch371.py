"""
Test Batch 371: Rigorous Quantitative Verification Suite
=========================================================
Covers:
  - Wave 491: High-Frequency Limit Order Book Pressure Gradient & Evaporation Velocity Guard
  - Wave 492: Imperial Sovereign Master Microstructure Apex Fortress Canopy Guard
"""

import pytest
import numpy as np
from wave491_lob_pressure_gradient_evaporation_guard import Wave491LobPressureGradientEvaporationGuard
from wave492_imperial_sovereign_master_microstructure_apex_fortress_guard import Wave492ImperialSovereignMasterMicrostructureApexFortressGuard


class TestWave491LobPressureGradientEvaporationGuard:
    """Rigorous verification of Wave 491 LOB Pressure Gradient Guard."""

    def test_initialization_valid_and_invalid(self):
        guard = Wave491LobPressureGradientEvaporationGuard(
            max_pressure_imbalance=0.85,
            max_gradient_breach=1.40,
            max_evap_velocity=1.80,
            gamma=0.40,
            cooldown_sec=2.0
        )
        assert guard.max_pressure_imbalance == 0.85
        assert guard.max_gradient_breach == 1.40

        with pytest.raises(ValueError, match="max_pressure_imbalance"):
            Wave491LobPressureGradientEvaporationGuard(max_pressure_imbalance=0.30)

        with pytest.raises(ValueError, match="max_gradient_breach"):
            Wave491LobPressureGradientEvaporationGuard(max_gradient_breach=0.50)

        with pytest.raises(ValueError, match="max_evap_velocity"):
            Wave491LobPressureGradientEvaporationGuard(max_evap_velocity=0.20)

        with pytest.raises(ValueError, match="gamma"):
            Wave491LobPressureGradientEvaporationGuard(gamma=0.05)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave491LobPressureGradientEvaporationGuard(cooldown_sec=0.05)

    def test_dimension_validations(self):
        guard = Wave491LobPressureGradientEvaporationGuard()

        with pytest.raises(ValueError, match="length"):
            guard.evaluate([10.0, 20.0], [10.0])

        with pytest.raises(ValueError, match="at least 2 book levels"):
            guard.evaluate([10.0], [10.0])

    def test_zero_liquidity_handling(self):
        guard = Wave491LobPressureGradientEvaporationGuard()
        res = guard.evaluate([0.0, 0.0], [10.0, 10.0])
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "ZERO_LIQUIDITY" in res["reason"]

    def test_symmetric_balanced_equilibrium(self):
        guard = Wave491LobPressureGradientEvaporationGuard()
        bv = [100.0, 80.0, 60.0, 40.0, 20.0]
        av = [100.0, 80.0, 60.0, 40.0, 20.0]
        res = guard.evaluate(bv, av, timestamp=100.0)
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert abs(res["i_pressure"]) < 1e-4

    def test_pressure_critical_breach(self):
        guard = Wave491LobPressureGradientEvaporationGuard(max_pressure_imbalance=0.85)
        # Bid side massively dominant
        bv = [1000.0, 1000.0, 1000.0]
        av = [0.1, 0.1, 0.1]
        res = guard.evaluate(bv, av, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "PRESSURE_GRADIENT_CRITICAL" in res["reason"]

    def test_spatial_gradient_breach(self):
        guard = Wave491LobPressureGradientEvaporationGuard(max_gradient_breach=1.40)
        # Bid: all at top (bv[0]=1000, bv[-1]=0) -> grad_bid ~ 1.0
        # Ask: all at deep (av[0]=0, av[-1]=1000) -> grad_ask ~ -1.0
        # grad_net ~ 2.0 >= 1.40
        bv = [1000.0, 0.1, 0.0]
        av = [0.0, 0.1, 1000.0]
        res = guard.evaluate(bv, av, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "SPATIAL_GRADIENT_BREACH" in res["reason"]

    def test_flash_evaporation_velocity(self):
        guard = Wave491LobPressureGradientEvaporationGuard(max_evap_velocity=1.80)
        # Step 1: Equilibrium
        guard.evaluate([100.0, 100.0], [100.0, 100.0], timestamp=10.0)

        # Step 2: Instant collapse in 0.1s: bv drops to 40, av stays 100
        # |I_pressure| ~ 0.43 < 0.85, but v_evap ~ 4.3/s >= 1.80/s
        res = guard.evaluate([40.0, 40.0], [100.0, 100.0], timestamp=10.1)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "FLASH_EVAPORATION_VELOCITY" in res["reason"]

    def test_directional_evaporation_blocks(self):
        guard = Wave491LobPressureGradientEvaporationGuard()

        # Bid side depth collapsed (i_pressure <= -0.65)
        res_buy = guard.evaluate([10.0, 10.0], [100.0, 100.0], timestamp=100.0)
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False

        # Ask side depth collapsed (i_pressure >= 0.65)
        res_sell = guard.evaluate([100.0, 100.0], [10.0, 10.0], timestamp=100.0)
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False

    def test_cooldown_and_reset(self):
        guard = Wave491LobPressureGradientEvaporationGuard(cooldown_sec=2.0)
        res = guard.evaluate([1000.0, 1000.0], [0.01, 0.01], timestamp=10.0)
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        res_cool = guard.evaluate([50.0, 50.0], [50.0, 50.0], timestamp=11.0)
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate([50.0, 50.0], [50.0, 50.0], timestamp=11.1)
        assert res_ok["action"] == "ALLOW_ALL"


class TestWave492ImperialSovereignMasterMicrostructureApexFortressGuard:
    """Rigorous verification of Wave 492 Imperial Fortress Master Guard."""

    def test_initialization_bounds(self):
        guard = Wave492ImperialSovereignMasterMicrostructureApexFortressGuard(
            critical_canopy_threshold=0.65,
            dual_spike_threshold=0.85,
            cooldown_sec=2.0
        )
        assert guard.critical_canopy_threshold == 0.65
        assert guard.dual_spike_threshold == 0.85

        with pytest.raises(ValueError, match="critical_canopy_threshold"):
            Wave492ImperialSovereignMasterMicrostructureApexFortressGuard(critical_canopy_threshold=0.30)

        with pytest.raises(ValueError, match="dual_spike_threshold"):
            Wave492ImperialSovereignMasterMicrostructureApexFortressGuard(dual_spike_threshold=0.60)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave492ImperialSovereignMasterMicrostructureApexFortressGuard(cooldown_sec=0.05)

    def test_input_range_validations(self):
        guard = Wave492ImperialSovereignMasterMicrostructureApexFortressGuard()

        with pytest.raises(ValueError, match="hawkes_spectral_radius"):
            guard.evaluate(-0.1, 0.2, 0.0, 0.2, 0.2, 0.2, 0.2, 0.5, 0.0)

        with pytest.raises(ValueError, match="resilience_fragility"):
            guard.evaluate(0.5, 1.5, 0.0, 0.2, 0.2, 0.2, 0.2, 0.5, 0.0)

        with pytest.raises(ValueError, match="xi_skew"):
            guard.evaluate(0.5, 0.2, -1.5, 0.2, 0.2, 0.2, 0.2, 0.5, 0.0)

        with pytest.raises(ValueError, match="omega_484"):
            guard.evaluate(0.5, 0.2, 0.0, 1.5, 0.2, 0.2, 0.2, 0.5, 0.0)

        with pytest.raises(ValueError, match="psi_impact"):
            guard.evaluate(0.5, 0.2, 0.0, 0.2, 1.5, 0.2, 0.2, 0.5, 0.0)

        with pytest.raises(ValueError, match="omega_486"):
            guard.evaluate(0.5, 0.2, 0.0, 0.2, 0.2, 1.5, 0.2, 0.5, 0.0)

        with pytest.raises(ValueError, match="s_info"):
            guard.evaluate(0.5, 0.2, 0.0, 0.2, 0.2, 0.2, 1.5, 0.5, 0.0)

        with pytest.raises(ValueError, match="cross_spectral_radius"):
            guard.evaluate(0.5, 0.2, 0.0, 0.2, 0.2, 0.2, 0.2, 3.5, 0.0)

        with pytest.raises(ValueError, match="i_pressure"):
            guard.evaluate(0.5, 0.2, 0.0, 0.2, 0.2, 0.2, 0.2, 0.5, 1.5)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave492ImperialSovereignMasterMicrostructureApexFortressGuard()
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
            timestamp=100.0
        )
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert res["omega_canopy"] < 0.35
        assert res["spikes_count"] == 0

    def test_fortress_canopy_breach(self):
        guard = Wave492ImperialSovereignMasterMicrostructureApexFortressGuard(critical_canopy_threshold=0.65)
        # All 9 pillars elevated to severe danger levels
        res = guard.evaluate(
            hawkes_spectral_radius=0.80, # phi_1 = 0.80/0.88 = 0.909
            resilience_fragility=0.62,   # phi_2 = 0.62/0.70 = 0.886
            xi_skew=0.65,                # phi_3 = 0.65/0.75 = 0.867
            omega_484=0.58,              # phi_4 = 0.58/0.65 = 0.892
            psi_impact=0.60,             # phi_5 = 0.60/0.70 = 0.857
            omega_486=0.58,              # phi_6 = 0.58/0.65 = 0.892
            s_info=0.68,                 # phi_7 = 0.68/0.75 = 0.907
            cross_spectral_radius=0.78,  # phi_8 = 0.78/0.85 = 0.918
            i_pressure=0.68,             # phi_9 = 0.68/0.75 = 0.907
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "IMPERIAL_FORTRESS_BREACH" in res["reason"]
        assert res["omega_canopy"] >= 0.65

    def test_dual_hazard_spike_trigger(self):
        guard = Wave492ImperialSovereignMasterMicrostructureApexFortressGuard(
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
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "DUAL_HAZARD_SPIKE" in res["reason"]
        assert res["spikes_count"] >= 2

    def test_asymmetric_directional_toxicity(self):
        guard = Wave492ImperialSovereignMasterMicrostructureApexFortressGuard()

        # Buy side toxicity (i_pressure <= -0.65)
        res_buy = guard.evaluate(
            hawkes_spectral_radius=0.40,
            resilience_fragility=0.20,
            xi_skew=0.0,
            omega_484=0.20,
            psi_impact=0.20,
            omega_486=0.20,
            s_info=0.20,
            cross_spectral_radius=0.30,
            i_pressure=-0.72, # i_pressure <= -0.65
            timestamp=100.0
        )
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False

        # Sell side toxicity (i_pressure >= 0.65)
        res_sell = guard.evaluate(
            hawkes_spectral_radius=0.40,
            resilience_fragility=0.20,
            xi_skew=0.0,
            omega_484=0.20,
            psi_impact=0.20,
            omega_486=0.20,
            s_info=0.20,
            cross_spectral_radius=0.30,
            i_pressure=0.75, # i_pressure >= 0.65
            timestamp=100.0
        )
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False

    def test_cooldown_and_reset(self):
        guard = Wave492ImperialSovereignMasterMicrostructureApexFortressGuard(cooldown_sec=2.5)
        res = guard.evaluate(0.88, 0.70, 0.75, 0.65, 0.70, 0.65, 0.75, 0.85, 0.75, timestamp=10.0)
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        res_cool = guard.evaluate(0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.0, timestamp=11.5)
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate(0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.0, timestamp=11.6)
        assert res_ok["action"] == "ALLOW_ALL"
