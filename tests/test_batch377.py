"""
Test Batch 377: Rigorous Quantitative Verification Suite
=========================================================
Covers:
  - Wave 503: High-Frequency Limit Order Book Dark Liquidity Latency Arbitrage & Fill Probability Hazard Guard
  - Wave 504: Imperial Sovereign Master Apex Aethelgard Canopy Master Guard
"""

import pytest
import numpy as np
from wave503_lob_dark_liquidity_latency_arbitrage_guard import Wave503LobDarkLiquidityLatencyArbitrageGuard
from wave504_imperial_sovereign_master_apex_aethelgard_guard import Wave504ImperialSovereignMasterApexAethelgardGuard


class TestWave503LobDarkLiquidityLatencyArbitrageGuard:
    """Rigorous verification of Wave 503 Dark Liquidity & Latency Arbitrage Guard."""

    def test_initialization_valid_and_invalid(self):
        guard = Wave503LobDarkLiquidityLatencyArbitrageGuard(
            max_arb_velocity_threshold=1.50,
            max_fill_asym_threshold=3.20,
            critical_sniping_threshold=0.70,
            delta_arb_warning=0.80,
            cooldown_sec=2.0
        )
        assert guard.max_arb_velocity_threshold == 1.50
        assert guard.max_fill_asym_threshold == 3.20

        with pytest.raises(ValueError, match="max_arb_velocity_threshold"):
            Wave503LobDarkLiquidityLatencyArbitrageGuard(max_arb_velocity_threshold=0.50)

        with pytest.raises(ValueError, match="max_fill_asym_threshold"):
            Wave503LobDarkLiquidityLatencyArbitrageGuard(max_fill_asym_threshold=1.50)

        with pytest.raises(ValueError, match="critical_sniping_threshold"):
            Wave503LobDarkLiquidityLatencyArbitrageGuard(critical_sniping_threshold=0.35)

        with pytest.raises(ValueError, match="delta_arb_warning"):
            Wave503LobDarkLiquidityLatencyArbitrageGuard(delta_arb_warning=0.20)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave503LobDarkLiquidityLatencyArbitrageGuard(cooldown_sec=0.05)

    def test_calculate_arbitrage_metrics(self):
        guard = Wave503LobDarkLiquidityLatencyArbitrageGuard()

        # Invalid prices
        with pytest.raises(ValueError, match="strictly positive"):
            guard.calculate_arbitrage_metrics(-100.0, 100.0)

        # Invalid tau
        with pytest.raises(ValueError, match="strictly positive"):
            guard.calculate_arbitrage_metrics(100.0, 100.0, tau_ms=-0.5)

        # Normal small disparity
        res_calm = guard.calculate_arbitrage_metrics(100.02, 100.01, tau_ms=0.5)
        assert abs(res_calm["delta_p"] - 0.01) < 1e-4
        assert res_calm["v_arb"] > 0.0

        # High latency arbitrage dislocation
        res_fast = guard.calculate_arbitrage_metrics(100.50, 100.00, tau_ms=0.2)
        assert res_fast["v_arb"] == 2.50

    def test_evaluate_input_validations(self):
        guard = Wave503LobDarkLiquidityLatencyArbitrageGuard()

        with pytest.raises(ValueError, match="v_arb"):
            guard.evaluate(v_arb=25.0)

        with pytest.raises(ValueError, match="f_asym"):
            guard.evaluate(v_arb=0.5, f_asym=-0.1)

        with pytest.raises(ValueError, match="delta_p_arb"):
            guard.evaluate(v_arb=0.5, delta_p_arb=15.0)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave503LobDarkLiquidityLatencyArbitrageGuard()
        res = guard.evaluate(v_arb=0.30, f_asym=1.00, delta_p_arb=0.05, timestamp=100.0)
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert res["psi_sniping"] == 0.0

    def test_critical_latency_arbitrage_breach(self):
        guard = Wave503LobDarkLiquidityLatencyArbitrageGuard(max_arb_velocity_threshold=1.50)
        res = guard.evaluate(v_arb=1.85, f_asym=1.20, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "LATENCY_ARBITRAGE_SNIPING" in res["reason"]

    def test_critical_sniping_fragility_breach(self):
        guard = Wave503LobDarkLiquidityLatencyArbitrageGuard(critical_sniping_threshold=0.70)
        # Moderate v_arb (1.40) and elevated f_asym (2.80) -> psi_sniping >= 0.70
        res = guard.evaluate(v_arb=1.40, f_asym=2.80, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "SNIPING_FRAGILITY_CRITICAL" in res["reason"]

    def test_critical_dark_fill_asymmetry(self):
        guard = Wave503LobDarkLiquidityLatencyArbitrageGuard(max_fill_asym_threshold=3.20)
        res = guard.evaluate(v_arb=0.20, f_asym=3.50, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "DARK_FILL_TOXICITY_ASYMMETRY" in res["reason"]

    def test_asymmetric_directional_toxicity_overrides(self):
        guard = Wave503LobDarkLiquidityLatencyArbitrageGuard(delta_arb_warning=0.80)

        # Buy side sniping hazard (delta_p_arb <= -0.80 or f_asym_buy >= 2.20)
        res_buy = guard.evaluate(v_arb=0.30, f_asym=1.0, delta_p_arb=-0.95, timestamp=100.0)
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False

        # Sell side sniping hazard (delta_p_arb >= 0.80 or f_asym_sell >= 2.20)
        res_sell = guard.evaluate(v_arb=0.30, f_asym=1.0, delta_p_arb=0.95, timestamp=100.0)
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False

    def test_cooldown_and_reset(self):
        guard = Wave503LobDarkLiquidityLatencyArbitrageGuard(cooldown_sec=2.0)
        res = guard.evaluate(v_arb=2.0, timestamp=10.0)
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        res_cool = guard.evaluate(v_arb=0.1, timestamp=11.0)
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate(v_arb=0.1, timestamp=11.1)
        assert res_ok["action"] == "ALLOW_ALL"


class TestWave504ImperialSovereignMasterApexAethelgardGuard:
    """Rigorous verification of Wave 504 Imperial Aethelgard Master Guard."""

    def test_initialization_bounds(self):
        guard = Wave504ImperialSovereignMasterApexAethelgardGuard(
            critical_canopy_threshold=0.65,
            dual_spike_threshold=0.85,
            cooldown_sec=2.0
        )
        assert guard.critical_canopy_threshold == 0.65
        assert guard.dual_spike_threshold == 0.85

        with pytest.raises(ValueError, match="critical_canopy_threshold"):
            Wave504ImperialSovereignMasterApexAethelgardGuard(critical_canopy_threshold=0.30)

        with pytest.raises(ValueError, match="dual_spike_threshold"):
            Wave504ImperialSovereignMasterApexAethelgardGuard(dual_spike_threshold=0.60)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave504ImperialSovereignMasterApexAethelgardGuard(cooldown_sec=0.05)

    def test_input_range_validations(self):
        guard = Wave504ImperialSovereignMasterApexAethelgardGuard()

        with pytest.raises(ValueError, match="hawkes_spectral_radius"):
            guard.evaluate(-0.1, 0.2, 0.0, 0.2, 0.2, 0.2, 0.2, 0.5, 0.0, 0.2, 0.2, 0.2, 0.2, 0.2)

        with pytest.raises(ValueError, match="psi_sniping"):
            guard.evaluate(0.5, 0.2, 0.0, 0.2, 0.2, 0.2, 0.2, 0.5, 0.0, 0.2, 0.2, 0.2, 0.2, 1.5)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave504ImperialSovereignMasterApexAethelgardGuard()
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
            timestamp=100.0
        )
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert res["omega_canopy"] < 0.35
        assert res["spikes_count"] == 0

    def test_aethelgard_canopy_breach(self):
        guard = Wave504ImperialSovereignMasterApexAethelgardGuard(critical_canopy_threshold=0.65)
        # All 15 pillars elevated
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
            r_bid=3.60,                  # phi_10 = 0.900
            r_ask=1.0,
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "IMPERIAL_AETHELGARD_BREACH" in res["reason"]
        assert res["omega_canopy"] >= 0.65

    def test_dual_hazard_spike_trigger(self):
        guard = Wave504ImperialSovereignMasterApexAethelgardGuard(
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
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "DUAL_HAZARD_SPIKE" in res["reason"]
        assert res["spikes_count"] >= 2

    def test_asymmetric_directional_toxicity(self):
        guard = Wave504ImperialSovereignMasterApexAethelgardGuard()

        # Buy side toxicity via dark pool buy adverse fill asymmetry (f_asym_buy >= 2.20)
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
            f_asym_buy=2.50, # f_asym_buy >= 2.20
            timestamp=100.0
        )
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False

        # Sell side toxicity via dark pool sell adverse fill asymmetry (f_asym_sell >= 2.20)
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
            f_asym_sell=2.50, # f_asym_sell >= 2.20
            timestamp=100.0
        )
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False

    def test_cooldown_and_reset(self):
        guard = Wave504ImperialSovereignMasterApexAethelgardGuard(cooldown_sec=2.5)
        res = guard.evaluate(
            0.88, 0.70, 0.75, 0.65, 0.70, 0.65, 0.75, 0.85, 0.75, 0.70, 0.70, 0.70, 0.70, 0.70,
            timestamp=10.0
        )
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        res_cool = guard.evaluate(
            0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1,
            timestamp=11.5
        )
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate(
            0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1,
            timestamp=11.6
        )
        assert res_ok["action"] == "ALLOW_ALL"
