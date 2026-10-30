"""
Test Batch 369: Rigorous Quantitative Verification Suite
=========================================================
Covers:
  - Wave 487: Order Flow Kyle Lambda & Microstructure Price Discovery Share Guard
  - Wave 488: Imperial Millennium Apex Microstructure Sovereign Master Guard
"""

import pytest
import numpy as np
from wave487_kyle_lambda_price_discovery_share_guard import Wave487KyleLambdaPriceDiscoveryShareGuard
from wave488_imperial_millennium_apex_microstructure_master_guard import Wave488ImperialMillenniumApexMicrostructureMasterGuard


class TestWave487KyleLambdaPriceDiscoveryShareGuard:
    """Rigorous verification of Wave 487 Kyle Lambda & Price Discovery Guard."""

    def test_initialization_valid_and_invalid(self):
        guard = Wave487KyleLambdaPriceDiscoveryShareGuard(
            max_info_share=0.80,
            critical_lambda_threshold=0.85,
            lambda_skew_threshold=0.65,
            cooldown_sec=2.0
        )
        assert guard.max_info_share == 0.80
        assert guard.critical_lambda_threshold == 0.85

        with pytest.raises(ValueError, match="max_info_share"):
            Wave487KyleLambdaPriceDiscoveryShareGuard(max_info_share=0.40)

        with pytest.raises(ValueError, match="critical_lambda_threshold"):
            Wave487KyleLambdaPriceDiscoveryShareGuard(critical_lambda_threshold=0.30)

        with pytest.raises(ValueError, match="lambda_skew_threshold"):
            Wave487KyleLambdaPriceDiscoveryShareGuard(lambda_skew_threshold=0.20)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave487KyleLambdaPriceDiscoveryShareGuard(cooldown_sec=0.05)

    def test_estimate_kyle_metrics_synthetic(self):
        guard = Wave487KyleLambdaPriceDiscoveryShareGuard()

        # Insufficient data
        with pytest.raises(ValueError, match="at least 4 observations"):
            guard.estimate_kyle_metrics([10.0, -10.0], [0.1, -0.1])

        # Length mismatch
        with pytest.raises(ValueError, match="length"):
            guard.estimate_kyle_metrics([10.0, -10.0, 5.0, -5.0], [0.1, -0.1])

        # Synthetic linear relationship: Delta P = 0.05 * Q
        signed_q = [10.0, 20.0, 30.0, -10.0, -20.0, -30.0]
        dp = [0.5, 1.0, 1.5, -0.5, -1.0, -1.5]
        metrics = guard.estimate_kyle_metrics(signed_q, dp)

        assert abs(metrics["lambda"] - 0.05) < 1e-4
        assert abs(metrics["s_info"] - 1.0) < 1e-4
        assert abs(metrics["lambda_buy"] - 0.05) < 1e-4
        assert abs(metrics["lambda_sell"] - 0.05) < 1e-4
        assert abs(metrics["lambda_skew"]) < 1e-4

    def test_evaluate_input_validations(self):
        guard = Wave487KyleLambdaPriceDiscoveryShareGuard()

        with pytest.raises(ValueError, match="s_info"):
            guard.evaluate(s_info=-0.1, lambda_norm=0.5)

        with pytest.raises(ValueError, match="lambda_norm"):
            guard.evaluate(s_info=0.5, lambda_norm=2.5)

        with pytest.raises(ValueError, match="lambda_skew"):
            guard.evaluate(s_info=0.5, lambda_norm=0.5, lambda_skew=1.5)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave487KyleLambdaPriceDiscoveryShareGuard()
        res = guard.evaluate(s_info=0.25, lambda_norm=0.30, lambda_skew=0.05, timestamp=100.0)
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False

    def test_info_share_saturation_breach(self):
        guard = Wave487KyleLambdaPriceDiscoveryShareGuard(max_info_share=0.80)
        res = guard.evaluate(s_info=0.84, lambda_norm=0.40, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "INFORMATION_SHARE_SATURATION" in res["reason"]

    def test_kyle_lambda_critical_breach(self):
        guard = Wave487KyleLambdaPriceDiscoveryShareGuard(critical_lambda_threshold=0.85)
        res = guard.evaluate(s_info=0.40, lambda_norm=0.92, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "KYLE_LAMBDA_CRITICAL" in res["reason"]

    def test_directional_asymmetry_blocks(self):
        guard = Wave487KyleLambdaPriceDiscoveryShareGuard(lambda_skew_threshold=0.65)

        # Buy side adverse selection
        res_buy = guard.evaluate(s_info=0.40, lambda_norm=0.40, lambda_skew=0.72, timestamp=100.0)
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False

        # Sell side adverse selection
        res_sell = guard.evaluate(s_info=0.40, lambda_norm=0.40, lambda_skew=-0.75, timestamp=100.0)
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False

    def test_cooldown_and_reset(self):
        guard = Wave487KyleLambdaPriceDiscoveryShareGuard(cooldown_sec=2.0)
        res = guard.evaluate(s_info=0.95, lambda_norm=0.50, timestamp=10.0)
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        res_cool = guard.evaluate(s_info=0.20, lambda_norm=0.20, timestamp=11.0)
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate(s_info=0.20, lambda_norm=0.20, timestamp=11.1)
        assert res_ok["action"] == "ALLOW_ALL"


class TestWave488ImperialMillenniumApexMicrostructureMasterGuard:
    """Rigorous verification of Wave 488 Imperial Millennium Apex Master Guard."""

    def test_initialization_bounds(self):
        guard = Wave488ImperialMillenniumApexMicrostructureMasterGuard(
            critical_canopy_threshold=0.65,
            dual_spike_threshold=0.85,
            cooldown_sec=2.0
        )
        assert guard.critical_canopy_threshold == 0.65
        assert guard.dual_spike_threshold == 0.85

        with pytest.raises(ValueError, match="critical_canopy_threshold"):
            Wave488ImperialMillenniumApexMicrostructureMasterGuard(critical_canopy_threshold=0.30)

        with pytest.raises(ValueError, match="dual_spike_threshold"):
            Wave488ImperialMillenniumApexMicrostructureMasterGuard(dual_spike_threshold=0.60)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave488ImperialMillenniumApexMicrostructureMasterGuard(cooldown_sec=0.05)

    def test_input_range_validations(self):
        guard = Wave488ImperialMillenniumApexMicrostructureMasterGuard()

        with pytest.raises(ValueError, match="hawkes_spectral_radius"):
            guard.evaluate(-0.1, 0.2, 0.0, 0.2, 0.2, 0.2, 0.2)

        with pytest.raises(ValueError, match="resilience_fragility"):
            guard.evaluate(0.5, 1.5, 0.0, 0.2, 0.2, 0.2, 0.2)

        with pytest.raises(ValueError, match="xi_skew"):
            guard.evaluate(0.5, 0.2, -1.5, 0.2, 0.2, 0.2, 0.2)

        with pytest.raises(ValueError, match="omega_484"):
            guard.evaluate(0.5, 0.2, 0.0, 1.5, 0.2, 0.2, 0.2)

        with pytest.raises(ValueError, match="psi_impact"):
            guard.evaluate(0.5, 0.2, 0.0, 0.2, 1.5, 0.2, 0.2)

        with pytest.raises(ValueError, match="omega_486"):
            guard.evaluate(0.5, 0.2, 0.0, 0.2, 0.2, 1.5, 0.2)

        with pytest.raises(ValueError, match="s_info"):
            guard.evaluate(0.5, 0.2, 0.0, 0.2, 0.2, 0.2, 1.5)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave488ImperialMillenniumApexMicrostructureMasterGuard()
        res = guard.evaluate(
            hawkes_spectral_radius=0.30,
            resilience_fragility=0.15,
            xi_skew=0.05,
            omega_484=0.15,
            psi_impact=0.10,
            omega_486=0.15,
            s_info=0.20,
            timestamp=100.0
        )
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert res["omega_canopy"] < 0.35
        assert res["spikes_count"] == 0

    def test_millennium_canopy_breach(self):
        guard = Wave488ImperialMillenniumApexMicrostructureMasterGuard(critical_canopy_threshold=0.65)
        # All pillars elevated to high values
        res = guard.evaluate(
            hawkes_spectral_radius=0.80, # phi_1 = 0.80/0.88 = 0.909
            resilience_fragility=0.62,   # phi_2 = 0.62/0.70 = 0.886
            xi_skew=0.65,                # phi_3 = 0.65/0.75 = 0.867
            omega_484=0.58,              # phi_4 = 0.58/0.65 = 0.892
            psi_impact=0.60,             # phi_5 = 0.60/0.70 = 0.857
            omega_486=0.58,              # phi_6 = 0.58/0.65 = 0.892
            s_info=0.68,                 # phi_7 = 0.68/0.75 = 0.907
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "IMPERIAL_MILLENNIUM_BREACH" in res["reason"]
        assert res["omega_canopy"] >= 0.65

    def test_dual_hazard_spike_trigger(self):
        guard = Wave488ImperialMillenniumApexMicrostructureMasterGuard(
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
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "DUAL_HAZARD_SPIKE" in res["reason"]
        assert res["spikes_count"] >= 2

    def test_asymmetric_directional_toxicity(self):
        guard = Wave488ImperialMillenniumApexMicrostructureMasterGuard()

        # Buy side toxicity (Kyle lambda skewness)
        res_buy = guard.evaluate(
            hawkes_spectral_radius=0.40,
            resilience_fragility=0.20,
            xi_skew=0.0,
            omega_484=0.20,
            psi_impact=0.20,
            omega_486=0.20,
            s_info=0.20,
            lambda_skew=0.72, # lambda_skew >= 0.65
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
            lambda_skew=-0.75,
            timestamp=100.0
        )
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False

    def test_cooldown_and_reset(self):
        guard = Wave488ImperialMillenniumApexMicrostructureMasterGuard(cooldown_sec=2.5)
        res = guard.evaluate(0.88, 0.70, 0.75, 0.65, 0.70, 0.65, 0.75, timestamp=10.0)
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        res_cool = guard.evaluate(0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, timestamp=11.5)
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate(0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, timestamp=11.6)
        assert res_ok["action"] == "ALLOW_ALL"
