"""
Test Batch 374: Rigorous Quantitative Verification Suite
=========================================================
Covers:
  - Wave 497: High-Frequency Limit Order Book Jump Diffusion & Lévy Flight Liquidity Shock Guard
  - Wave 498: Imperial Supreme Sovereign Apex Valhalla Master Guard
"""

import pytest
import numpy as np
from wave497_lob_jump_diffusion_levy_flight_guard import Wave497LobJumpDiffusionLevyFlightGuard
from wave498_imperial_supreme_sovereign_apex_valhalla_guard import Wave498ImperialSupremeSovereignApexValhallaGuard


class TestWave497LobJumpDiffusionLevyFlightGuard:
    """Rigorous verification of Wave 497 Jump Diffusion & Lévy Flight Guard."""

    def test_initialization_valid_and_invalid(self):
        guard = Wave497LobJumpDiffusionLevyFlightGuard(
            max_jratio_threshold=0.75,
            min_alpha_threshold=1.30,
            critical_fragility_threshold=0.70,
            zjump_warning_threshold=2.50,
            cooldown_sec=2.0
        )
        assert guard.max_jratio_threshold == 0.75
        assert guard.min_alpha_threshold == 1.30

        with pytest.raises(ValueError, match="max_jratio_threshold"):
            Wave497LobJumpDiffusionLevyFlightGuard(max_jratio_threshold=0.30)

        with pytest.raises(ValueError, match="min_alpha_threshold"):
            Wave497LobJumpDiffusionLevyFlightGuard(min_alpha_threshold=0.50)

        with pytest.raises(ValueError, match="critical_fragility_threshold"):
            Wave497LobJumpDiffusionLevyFlightGuard(critical_fragility_threshold=0.35)

        with pytest.raises(ValueError, match="zjump_warning_threshold"):
            Wave497LobJumpDiffusionLevyFlightGuard(zjump_warning_threshold=1.00)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave497LobJumpDiffusionLevyFlightGuard(cooldown_sec=0.05)

    def test_estimate_bipower_jump(self):
        guard = Wave497LobJumpDiffusionLevyFlightGuard()

        # Insufficient data
        with pytest.raises(ValueError, match="at least 4 prices"):
            guard.estimate_bipower_jump([100.0, 101.0, 100.5])

        # Negative price
        with pytest.raises(ValueError, match="strictly positive"):
            guard.estimate_bipower_jump([100.0, 101.0, -100.5, 102.0])

        # Smooth geometric random walk (low jump ratio)
        np.random.seed(42)
        rets = np.random.normal(0, 0.001, size=100)
        smooth_prices = [100.0]
        for r in rets:
            smooth_prices.append(smooth_prices[-1] * np.exp(r))

        res_smooth = guard.estimate_bipower_jump(smooth_prices)
        assert res_smooth["qv"] > 0.0
        assert res_smooth["bv"] > 0.0
        assert res_smooth["j_ratio"] <= 0.35

        # Series with a massive discontinuous jump in the middle
        jump_prices = list(smooth_prices)
        jump_prices[50] = jump_prices[49] * 1.10  # 10% instant jump
        res_jump = guard.estimate_bipower_jump(jump_prices)
        assert res_jump["j_ratio"] > res_smooth["j_ratio"]

    def test_estimate_levy_alpha(self):
        guard = Wave497LobJumpDiffusionLevyFlightGuard()

        with pytest.raises(ValueError, match="at least 6 returns"):
            guard.estimate_levy_alpha([0.01, -0.01, 0.02])

        # Gaussian returns -> alpha close to 2.0
        np.random.seed(42)
        gaussian_rets = np.random.normal(0, 0.001, size=200).tolist()
        alpha_gauss = guard.estimate_levy_alpha(gaussian_rets)
        assert 1.40 <= alpha_gauss <= 2.00

        # Heavy-tailed Pareto / Student-t returns
        heavy_rets = (np.random.standard_t(df=2.0, size=200) * 0.001).tolist()
        alpha_heavy = guard.estimate_levy_alpha(heavy_rets)
        assert 0.50 <= alpha_heavy <= 2.00

    def test_evaluate_input_validations(self):
        guard = Wave497LobJumpDiffusionLevyFlightGuard()

        with pytest.raises(ValueError, match="j_ratio"):
            guard.evaluate(j_ratio=-0.1, alpha_levy=1.5)

        with pytest.raises(ValueError, match="alpha_levy"):
            guard.evaluate(j_ratio=0.2, alpha_levy=0.2)

        with pytest.raises(ValueError, match="z_jump"):
            guard.evaluate(j_ratio=0.2, alpha_levy=1.5, z_jump=15.0)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave497LobJumpDiffusionLevyFlightGuard()
        res = guard.evaluate(j_ratio=0.10, alpha_levy=1.85, z_jump=0.2, timestamp=100.0)
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert res["psi_jump"] == 0.0

    def test_critical_jump_diffusion_breach(self):
        guard = Wave497LobJumpDiffusionLevyFlightGuard(max_jratio_threshold=0.75)
        # Extreme jump ratio
        res = guard.evaluate(j_ratio=0.82, alpha_levy=1.60, z_jump=1.0, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "LOB_JUMP_DIFFUSION_CRITICAL" in res["reason"]

    def test_critical_jump_fragility_breach(self):
        guard = Wave497LobJumpDiffusionLevyFlightGuard(critical_fragility_threshold=0.70)
        # Moderate j_ratio (0.65) and low alpha (1.10) -> psi_jump >= 0.70
        res = guard.evaluate(j_ratio=0.68, alpha_levy=1.05, z_jump=0.5, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "JUMP_FRAGILITY_CRITICAL" in res["reason"]

    def test_levy_flight_liquidity_shock(self):
        guard = Wave497LobJumpDiffusionLevyFlightGuard(min_alpha_threshold=1.30)
        # alpha=1.15 <= 1.30 and j_ratio=0.45 >= 0.40
        res = guard.evaluate(j_ratio=0.45, alpha_levy=1.15, z_jump=0.0, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "LEVY_FLIGHT_SHOCK" in res["reason"]

    def test_asymmetric_jump_overextension(self):
        guard = Wave497LobJumpDiffusionLevyFlightGuard(zjump_warning_threshold=2.50)

        # Upward flash squeeze jump
        res_buy = guard.evaluate(j_ratio=0.20, alpha_levy=1.70, z_jump=2.85, timestamp=100.0)
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False

        # Downward flush liquidation jump
        res_sell = guard.evaluate(j_ratio=0.20, alpha_levy=1.70, z_jump=-2.85, timestamp=100.0)
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False

    def test_cooldown_and_reset(self):
        guard = Wave497LobJumpDiffusionLevyFlightGuard(cooldown_sec=2.0)
        res = guard.evaluate(j_ratio=0.85, alpha_levy=1.80, timestamp=10.0)
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        res_cool = guard.evaluate(j_ratio=0.10, alpha_levy=1.80, timestamp=11.0)
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate(j_ratio=0.10, alpha_levy=1.80, timestamp=11.1)
        assert res_ok["action"] == "ALLOW_ALL"


class TestWave498ImperialSupremeSovereignApexValhallaGuard:
    """Rigorous verification of Wave 498 Imperial Valhalla Master Guard."""

    def test_initialization_bounds(self):
        guard = Wave498ImperialSupremeSovereignApexValhallaGuard(
            critical_canopy_threshold=0.65,
            dual_spike_threshold=0.85,
            cooldown_sec=2.0
        )
        assert guard.critical_canopy_threshold == 0.65
        assert guard.dual_spike_threshold == 0.85

        with pytest.raises(ValueError, match="critical_canopy_threshold"):
            Wave498ImperialSupremeSovereignApexValhallaGuard(critical_canopy_threshold=0.30)

        with pytest.raises(ValueError, match="dual_spike_threshold"):
            Wave498ImperialSupremeSovereignApexValhallaGuard(dual_spike_threshold=0.60)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave498ImperialSupremeSovereignApexValhallaGuard(cooldown_sec=0.05)

    def test_input_range_validations(self):
        guard = Wave498ImperialSupremeSovereignApexValhallaGuard()

        with pytest.raises(ValueError, match="hawkes_spectral_radius"):
            guard.evaluate(-0.1, 0.2, 0.0, 0.2, 0.2, 0.2, 0.2, 0.5, 0.0, 0.2, 0.2)

        with pytest.raises(ValueError, match="psi_jump"):
            guard.evaluate(0.5, 0.2, 0.0, 0.2, 0.2, 0.2, 0.2, 0.5, 0.0, 0.2, 1.5)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave498ImperialSupremeSovereignApexValhallaGuard()
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
            timestamp=100.0
        )
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert res["omega_canopy"] < 0.35
        assert res["spikes_count"] == 0

    def test_valhalla_canopy_breach(self):
        guard = Wave498ImperialSupremeSovereignApexValhallaGuard(critical_canopy_threshold=0.65)
        # All 12 pillars elevated
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
            r_bid=3.60,                  # phi_10 = 0.900
            r_ask=1.0,
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "IMPERIAL_VALHALLA_BREACH" in res["reason"]
        assert res["omega_canopy"] >= 0.65

    def test_dual_hazard_spike_trigger(self):
        guard = Wave498ImperialSupremeSovereignApexValhallaGuard(
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
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "DUAL_HAZARD_SPIKE" in res["reason"]
        assert res["spikes_count"] >= 2

    def test_asymmetric_directional_toxicity(self):
        guard = Wave498ImperialSupremeSovereignApexValhallaGuard()

        # Buy side toxicity via upward jump exhaustion (z_jump >= 2.50)
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
            z_jump=2.80, # z_jump >= 2.50
            timestamp=100.0
        )
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False

        # Sell side toxicity via downward jump flush (z_jump <= -2.50)
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
            z_jump=-2.80, # z_jump <= -2.50
            timestamp=100.0
        )
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False

    def test_cooldown_and_reset(self):
        guard = Wave498ImperialSupremeSovereignApexValhallaGuard(cooldown_sec=2.5)
        res = guard.evaluate(
            0.88, 0.70, 0.75, 0.65, 0.70, 0.65, 0.75, 0.85, 0.75, 0.70, 0.70,
            timestamp=10.0
        )
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        res_cool = guard.evaluate(
            0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.0, 0.1, 0.1,
            timestamp=11.5
        )
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate(
            0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.0, 0.1, 0.1,
            timestamp=11.6
        )
        assert res_ok["action"] == "ALLOW_ALL"
