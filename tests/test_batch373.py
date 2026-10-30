"""
Test Batch 373: Rigorous Quantitative Verification Suite
=========================================================
Covers:
  - Wave 495: Transient Cross-Sectional Momentum Dislocation & Mean-Reversion Half-Life Guard
  - Wave 496: Imperial Supreme Sovereign Apex Olympus Canopy Guard
"""

import pytest
import numpy as np
from wave495_transient_momentum_dislocation_halflife_guard import Wave495TransientMomentumDislocationHalflifeGuard
from wave496_imperial_supreme_sovereign_apex_olympus_guard import Wave496ImperialSupremeSovereignApexOlympusGuard


class TestWave495TransientMomentumDislocationHalflifeGuard:
    """Rigorous verification of Wave 495 Momentum Dislocation & Half-Life Guard."""

    def test_initialization_valid_and_invalid(self):
        guard = Wave495TransientMomentumDislocationHalflifeGuard(
            max_zscore_threshold=3.20,
            zscore_warning_threshold=2.20,
            max_halflife_threshold=8.0,
            cooldown_sec=2.0
        )
        assert guard.max_zscore_threshold == 3.20
        assert guard.zscore_warning_threshold == 2.20

        with pytest.raises(ValueError, match="max_zscore_threshold"):
            Wave495TransientMomentumDislocationHalflifeGuard(max_zscore_threshold=1.50)

        with pytest.raises(ValueError, match="zscore_warning_threshold"):
            Wave495TransientMomentumDislocationHalflifeGuard(zscore_warning_threshold=0.50)

        with pytest.raises(ValueError, match="strictly less"):
            Wave495TransientMomentumDislocationHalflifeGuard(zscore_warning_threshold=2.80, max_zscore_threshold=2.60)

        with pytest.raises(ValueError, match="max_halflife_threshold"):
            Wave495TransientMomentumDislocationHalflifeGuard(max_halflife_threshold=2.0)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave495TransientMomentumDislocationHalflifeGuard(cooldown_sec=0.05)

    def test_estimate_ou_parameters(self):
        guard = Wave495TransientMomentumDislocationHalflifeGuard()

        # Insufficient data
        with pytest.raises(ValueError, match="at least 6 points"):
            guard.estimate_ou_parameters([1.0, 2.0, 3.0])

        # Invalid dt
        with pytest.raises(ValueError, match="dt must be positive"):
            guard.estimate_ou_parameters([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], dt=-0.1)

        # Synthetic fast mean-reverting series around 100.0
        np.random.seed(42)
        series = [100.0]
        for _ in range(50):
            next_val = 100.0 + 0.5 * (series[-1] - 100.0) + np.random.normal(0, 0.5)
            series.append(next_val)

        ou_res = guard.estimate_ou_parameters(series, dt=0.1)
        assert ou_res["theta"] > 0.0
        assert ou_res["t_halflife"] > 0.0

    def test_evaluate_input_validations(self):
        guard = Wave495TransientMomentumDislocationHalflifeGuard()

        with pytest.raises(ValueError, match="z_score"):
            guard.evaluate(z_score=15.0, t_halflife=2.0)

        with pytest.raises(ValueError, match="t_halflife"):
            guard.evaluate(z_score=1.0, t_halflife=-1.0)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave495TransientMomentumDislocationHalflifeGuard()
        res = guard.evaluate(z_score=0.50, t_halflife=1.5, timestamp=100.0)
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert res["psi_momentum"] == 0.0

    def test_critical_dislocation_breach(self):
        guard = Wave495TransientMomentumDislocationHalflifeGuard(max_zscore_threshold=3.20)
        res = guard.evaluate(z_score=3.45, t_halflife=2.0, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "MOMENTUM_DISLOCATION_CRITICAL" in res["reason"]

    def test_mean_reversion_collapse(self):
        guard = Wave495TransientMomentumDislocationHalflifeGuard(max_halflife_threshold=8.0)
        # Dislocated by 2.50 sigma, and half-life is 9.5s (> 8.0s)
        res = guard.evaluate(z_score=2.50, t_halflife=9.5, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "MEAN_REVERSION_COLLAPSE" in res["reason"]

    def test_directional_overextension_blocks(self):
        guard = Wave495TransientMomentumDislocationHalflifeGuard(zscore_warning_threshold=2.20)

        # Parabolic blowoff top -> BLOCK_BUY
        res_buy = guard.evaluate(z_score=2.40, t_halflife=3.0, timestamp=100.0)
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False

        # Liquidation flush bottom -> BLOCK_SELL
        res_sell = guard.evaluate(z_score=-2.40, t_halflife=3.0, timestamp=100.0)
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False

    def test_cooldown_and_reset(self):
        guard = Wave495TransientMomentumDislocationHalflifeGuard(cooldown_sec=2.0)
        res = guard.evaluate(z_score=3.5, t_halflife=2.0, timestamp=10.0)
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        res_cool = guard.evaluate(z_score=0.1, t_halflife=1.0, timestamp=11.0)
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate(z_score=0.1, t_halflife=1.0, timestamp=11.1)
        assert res_ok["action"] == "ALLOW_ALL"


class TestWave496ImperialSupremeSovereignApexOlympusGuard:
    """Rigorous verification of Wave 496 Imperial Olympus Master Guard."""

    def test_initialization_bounds(self):
        guard = Wave496ImperialSupremeSovereignApexOlympusGuard(
            critical_canopy_threshold=0.65,
            dual_spike_threshold=0.85,
            cooldown_sec=2.0
        )
        assert guard.critical_canopy_threshold == 0.65
        assert guard.dual_spike_threshold == 0.85

        with pytest.raises(ValueError, match="critical_canopy_threshold"):
            Wave496ImperialSupremeSovereignApexOlympusGuard(critical_canopy_threshold=0.30)

        with pytest.raises(ValueError, match="dual_spike_threshold"):
            Wave496ImperialSupremeSovereignApexOlympusGuard(dual_spike_threshold=0.60)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave496ImperialSupremeSovereignApexOlympusGuard(cooldown_sec=0.05)

    def test_input_range_validations(self):
        guard = Wave496ImperialSupremeSovereignApexOlympusGuard()

        with pytest.raises(ValueError, match="hawkes_spectral_radius"):
            guard.evaluate(-0.1, 0.2, 0.0, 0.2, 0.2, 0.2, 0.2, 0.5, 0.0, 0.2)

        with pytest.raises(ValueError, match="psi_momentum"):
            guard.evaluate(0.5, 0.2, 0.0, 0.2, 0.2, 0.2, 0.2, 0.5, 0.0, 1.5)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave496ImperialSupremeSovereignApexOlympusGuard()
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
            timestamp=100.0
        )
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert res["omega_canopy"] < 0.35
        assert res["spikes_count"] == 0

    def test_olympus_canopy_breach(self):
        guard = Wave496ImperialSupremeSovereignApexOlympusGuard(critical_canopy_threshold=0.65)
        # All 11 pillars elevated to high hazard levels
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
            r_bid=3.60,                  # phi_10 = 0.900
            r_ask=1.0,
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "IMPERIAL_OLYMPUS_BREACH" in res["reason"]
        assert res["omega_canopy"] >= 0.65

    def test_dual_hazard_spike_trigger(self):
        guard = Wave496ImperialSupremeSovereignApexOlympusGuard(
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
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "DUAL_HAZARD_SPIKE" in res["reason"]
        assert res["spikes_count"] >= 2

    def test_asymmetric_directional_toxicity(self):
        guard = Wave496ImperialSupremeSovereignApexOlympusGuard()

        # Buy side toxicity (z_score >= 2.20)
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
            z_score=2.40, # z_score >= 2.20
            timestamp=100.0
        )
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False

        # Sell side toxicity (z_score <= -2.20)
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
            z_score=-2.40, # z_score <= -2.20
            timestamp=100.0
        )
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False

    def test_cooldown_and_reset(self):
        guard = Wave496ImperialSupremeSovereignApexOlympusGuard(cooldown_sec=2.5)
        res = guard.evaluate(0.88, 0.70, 0.75, 0.65, 0.70, 0.65, 0.75, 0.85, 0.75, 0.70, timestamp=10.0)
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        res_cool = guard.evaluate(0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.0, 0.1, timestamp=11.5)
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate(0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.0, 0.1, timestamp=11.6)
        assert res_ok["action"] == "ALLOW_ALL"
