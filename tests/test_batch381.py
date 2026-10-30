"""
Test Batch 381: Rigorous Quantitative Verification Suite
=========================================================
Covers:
  - Wave 511: High-Frequency Limit Order Book Rough Volatility Fractional Brownian Motion & Cauchy-Lorentz Heavy Tail Singularity Guard
  - Wave 512: Imperial Sovereign Master Apex Bifrost Canopy Master Guard
"""

import pytest
import numpy as np
from wave511_lob_rough_volatility_fbm_cauchy_tail_guard import Wave511LobRoughVolatilityFbmCauchyTailGuard
from wave512_imperial_sovereign_master_apex_bifrost_guard import Wave512ImperialSovereignMasterApexBifrostGuard


class TestWave511LobRoughVolatilityFbmCauchyTailGuard:
    """Rigorous verification of Wave 511 Rough Volatility & Cauchy Tail Guard."""

    def test_initialization_valid_and_invalid(self):
        guard = Wave511LobRoughVolatilityFbmCauchyTailGuard(
            min_h_vol_threshold=0.08,
            max_h_vol_threshold=0.40,
            min_cauchy_ratio=0.35,
            max_cauchy_ratio=1.40,
            critical_fragility_threshold=0.70,
            z_rough_warning_threshold=2.20,
            cooldown_sec=2.0
        )
        assert guard.min_h_vol_threshold == 0.08
        assert guard.max_h_vol_threshold == 0.40
        assert guard.min_cauchy_ratio == 0.35
        assert guard.max_cauchy_ratio == 1.40

        with pytest.raises(ValueError, match="min_h_vol_threshold"):
            Wave511LobRoughVolatilityFbmCauchyTailGuard(min_h_vol_threshold=0.01)

        with pytest.raises(ValueError, match="max_h_vol_threshold"):
            Wave511LobRoughVolatilityFbmCauchyTailGuard(max_h_vol_threshold=0.20)

        with pytest.raises(ValueError, match="min_cauchy_ratio"):
            Wave511LobRoughVolatilityFbmCauchyTailGuard(min_cauchy_ratio=0.10)

        with pytest.raises(ValueError, match="max_cauchy_ratio"):
            Wave511LobRoughVolatilityFbmCauchyTailGuard(max_cauchy_ratio=0.90)

        with pytest.raises(ValueError, match="critical_fragility_threshold"):
            Wave511LobRoughVolatilityFbmCauchyTailGuard(critical_fragility_threshold=0.30)

        with pytest.raises(ValueError, match="z_rough_warning_threshold"):
            Wave511LobRoughVolatilityFbmCauchyTailGuard(z_rough_warning_threshold=0.50)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave511LobRoughVolatilityFbmCauchyTailGuard(cooldown_sec=0.05)

    def test_estimate_roughness_and_cauchy(self):
        guard = Wave511LobRoughVolatilityFbmCauchyTailGuard()

        # Insufficient data
        with pytest.raises(ValueError, match="at least 16 log-volatility points"):
            guard.estimate_roughness_and_cauchy([1.0] * 5, [0.1] * 16)

        with pytest.raises(ValueError, match="at least 16 return increments"):
            guard.estimate_roughness_and_cauchy([1.0] * 16, [0.1] * 5)

        # Normal test series
        np.random.seed(42)
        log_vols = np.cumsum(np.random.normal(0, 0.1, size=32)).tolist()
        rets = np.random.normal(0, 0.01, size=32).tolist()
        res = guard.estimate_roughness_and_cauchy(log_vols, rets)
        assert "h_vol" in res
        assert "r_cauchy" in res
        assert 0.02 <= res["h_vol"] <= 0.65
        assert 0.01 <= res["r_cauchy"] <= 3.0

    def test_evaluate_input_validations(self):
        guard = Wave511LobRoughVolatilityFbmCauchyTailGuard()

        with pytest.raises(ValueError, match="h_vol"):
            guard.evaluate(h_vol=0.001)

        with pytest.raises(ValueError, match="h_vol"):
            guard.evaluate(h_vol=1.5)

        with pytest.raises(ValueError, match="r_cauchy"):
            guard.evaluate(h_vol=0.14, r_cauchy=0.005)

        with pytest.raises(ValueError, match="z_rough"):
            guard.evaluate(h_vol=0.14, r_cauchy=0.675, z_rough=15.0)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave511LobRoughVolatilityFbmCauchyTailGuard()
        # Normal calm rough volatility market: H_vol ~ 0.14, R_cauchy ~ 0.675
        res = guard.evaluate(h_vol=0.14, r_cauchy=0.675, z_rough=0.1, timestamp=100.0)
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert res["psi_rough"] == 0.0

    def test_hyper_rough_volatility_collapse_breaker(self):
        guard = Wave511LobRoughVolatilityFbmCauchyTailGuard(min_h_vol_threshold=0.08)
        res = guard.evaluate(h_vol=0.05, r_cauchy=0.675, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "HYPER_ROUGH_VOLATILITY_COLLAPSE" in res["reason"]

    def test_rough_volatility_fragility_critical_breach(self):
        guard = Wave511LobRoughVolatilityFbmCauchyTailGuard(critical_fragility_threshold=0.70)
        # Elevated roughness (h_vol = 0.07) -> phi_h = (0.14 - 0.07)/0.08 = 0.875
        # Elevated cauchy dispersion blowout (r_cauchy = 1.20) -> phi_cauchy = (0.525 - 0.15)/0.40 = 0.9375
        # psi_rough = 0.5*0.875 + 0.5*0.9375 = 0.90625 >= 0.70
        res = guard.evaluate(h_vol=0.07, r_cauchy=1.20, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True

    def test_cauchy_tail_dispersion_breakers(self):
        guard = Wave511LobRoughVolatilityFbmCauchyTailGuard(
            min_cauchy_ratio=0.35,
            max_cauchy_ratio=1.40
        )

        # Cauchy tail collapse / extreme compression
        res_low = guard.evaluate(h_vol=0.15, r_cauchy=0.25, timestamp=100.0)
        assert res_low["action"] == "HALT_ALL"
        assert res_low["circuit_breaker"] is True
        assert "CAUCHY_TAIL_COMPRESSION_COLLAPSE" in res_low["reason"]

        guard.reset()
        # Cauchy tail blowout / extreme fat tail dispersion
        res_high = guard.evaluate(h_vol=0.15, r_cauchy=1.55, timestamp=100.0)
        assert res_high["action"] == "HALT_ALL"
        assert res_high["circuit_breaker"] is True
        assert "CAUCHY_TAIL_DISPERSION_BLOWOUT" in res_high["reason"]

    def test_asymmetric_directional_rough_volatility_overextensions(self):
        guard = Wave511LobRoughVolatilityFbmCauchyTailGuard(z_rough_warning_threshold=2.20)

        # Parabolic rough squeeze (h_vol <= 0.12 and z_rough >= 2.20)
        res_buy = guard.evaluate(h_vol=0.10, r_cauchy=0.675, z_rough=2.50, timestamp=100.0)
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False
        assert "PARABOLIC_ROUGH_VOLATILITY_SQUEEZE" in res_buy["reason"]

        # Liquidation rough cascade (h_vol <= 0.12 and z_rough <= -2.20)
        res_sell = guard.evaluate(h_vol=0.10, r_cauchy=0.675, z_rough=-2.50, timestamp=100.0)
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False
        assert "LIQUIDATION_ROUGH_VOLATILITY_CASCADE" in res_sell["reason"]

    def test_cooldown_and_reset(self):
        guard = Wave511LobRoughVolatilityFbmCauchyTailGuard(cooldown_sec=2.0)
        res = guard.evaluate(h_vol=0.03, timestamp=10.0)
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        res_cool = guard.evaluate(h_vol=0.14, timestamp=11.0)
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate(h_vol=0.14, timestamp=11.1)
        assert res_ok["action"] == "ALLOW_ALL"


class TestWave512ImperialSovereignMasterApexBifrostGuard:
    """Rigorous verification of Wave 512 Imperial Bifrost Master Guard."""

    def test_initialization_bounds(self):
        guard = Wave512ImperialSovereignMasterApexBifrostGuard(
            critical_canopy_threshold=0.65,
            dual_spike_threshold=0.85,
            cooldown_sec=2.0
        )
        assert guard.critical_canopy_threshold == 0.65
        assert guard.dual_spike_threshold == 0.85

        with pytest.raises(ValueError, match="critical_canopy_threshold"):
            Wave512ImperialSovereignMasterApexBifrostGuard(critical_canopy_threshold=0.30)

        with pytest.raises(ValueError, match="dual_spike_threshold"):
            Wave512ImperialSovereignMasterApexBifrostGuard(dual_spike_threshold=0.60)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave512ImperialSovereignMasterApexBifrostGuard(cooldown_sec=0.05)

    def test_input_range_validations(self):
        guard = Wave512ImperialSovereignMasterApexBifrostGuard()

        with pytest.raises(ValueError, match="hawkes_spectral_radius"):
            guard.evaluate(-0.1, 0.2, 0.0, 0.2, 0.2, 0.2, 0.2, 0.5, 0.0, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2)

        with pytest.raises(ValueError, match="psi_rough"):
            guard.evaluate(0.5, 0.2, 0.0, 0.2, 0.2, 0.2, 0.2, 0.5, 0.0, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 1.5)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave512ImperialSovereignMasterApexBifrostGuard()
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
            psi_rough=0.10,
            timestamp=100.0
        )
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert res["omega_canopy"] < 0.35
        assert res["spikes_count"] == 0

    def test_bifrost_canopy_breach(self):
        guard = Wave512ImperialSovereignMasterApexBifrostGuard(critical_canopy_threshold=0.65)
        # All 19 pillars elevated
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
            psi_rough=0.62,              # phi_19 = 0.886
            r_bid=3.60,                  # phi_10 = 0.900
            r_ask=1.0,
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "IMPERIAL_BIFROST_BREACH" in res["reason"]
        assert res["omega_canopy"] >= 0.65

    def test_dual_hazard_spike_trigger(self):
        guard = Wave512ImperialSovereignMasterApexBifrostGuard(
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
            psi_rough=0.05,
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "DUAL_HAZARD_SPIKE" in res["reason"]
        assert res["spikes_count"] >= 2

    def test_asymmetric_directional_toxicity(self):
        guard = Wave512ImperialSovereignMasterApexBifrostGuard()

        # Buy side toxicity via rough squeeze (h_vol <= 0.12 and z_rough >= 2.20)
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
            psi_rough=0.20,
            h_vol=0.10,
            z_rough=2.40,
            timestamp=100.0
        )
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False

        # Sell side toxicity via rough cascade (h_vol <= 0.12 and z_rough <= -2.20)
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
            psi_rough=0.20,
            h_vol=0.10,
            z_rough=-2.40,
            timestamp=100.0
        )
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False

    def test_cooldown_and_reset(self):
        guard = Wave512ImperialSovereignMasterApexBifrostGuard(cooldown_sec=2.5)
        res = guard.evaluate(
            0.88, 0.70, 0.75, 0.65, 0.70, 0.65, 0.75, 0.85, 0.75, 0.70, 0.70, 0.70, 0.70, 0.70, 0.70, 0.70, 0.70, 0.70, 0.70,
            timestamp=10.0
        )
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        res_cool = guard.evaluate(
            0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1,
            timestamp=11.5
        )
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate(
            0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1,
            timestamp=11.6
        )
        assert res_ok["action"] == "ALLOW_ALL"
