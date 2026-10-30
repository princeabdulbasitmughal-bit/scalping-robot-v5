"""
Test Batch 378: Rigorous Quantitative Verification Suite
=========================================================
Covers:
  - Wave 505: High-Frequency Limit Order Book Fractionally Integrated Autoregressive Noise & Long-Memory Liquidity Hurst Exponent Guard
  - Wave 506: Imperial Sovereign Master Apex Hyperion Canopy Master Guard
"""

import pytest
import numpy as np
from wave505_lob_arfima_long_memory_hurst_guard import Wave505LobArfimaLongMemoryHurstGuard
from wave506_imperial_sovereign_master_apex_hyperion_guard import Wave506ImperialSovereignMasterApexHyperionGuard


class TestWave505LobArfimaLongMemoryHurstGuard:
    """Rigorous verification of Wave 505 ARFIMA & Hurst Long-Memory Guard."""

    def test_initialization_valid_and_invalid(self):
        guard = Wave505LobArfimaLongMemoryHurstGuard(
            max_hurst_threshold=0.78,
            min_hurst_threshold=0.28,
            critical_fragility_threshold=0.70,
            z_memory_warning_threshold=2.50,
            cooldown_sec=2.0
        )
        assert guard.max_hurst_threshold == 0.78
        assert guard.min_hurst_threshold == 0.28

        with pytest.raises(ValueError, match="max_hurst_threshold"):
            Wave505LobArfimaLongMemoryHurstGuard(max_hurst_threshold=0.50)

        with pytest.raises(ValueError, match="min_hurst_threshold"):
            Wave505LobArfimaLongMemoryHurstGuard(min_hurst_threshold=0.10)

        with pytest.raises(ValueError, match="critical_fragility_threshold"):
            Wave505LobArfimaLongMemoryHurstGuard(critical_fragility_threshold=0.35)

        with pytest.raises(ValueError, match="z_memory_warning_threshold"):
            Wave505LobArfimaLongMemoryHurstGuard(z_memory_warning_threshold=1.20)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave505LobArfimaLongMemoryHurstGuard(cooldown_sec=0.05)

    def test_estimate_hurst_rs(self):
        guard = Wave505LobArfimaLongMemoryHurstGuard()

        # Insufficient data
        with pytest.raises(ValueError, match="at least 10 observations"):
            guard.estimate_hurst_rs([1.0, 2.0, 3.0])

        # Zero variance series
        res_zero = guard.estimate_hurst_rs([100.0] * 20)
        assert res_zero["h_hurst"] == 0.50

        # Normal random walk
        np.random.seed(42)
        rw = np.cumsum(np.random.normal(0, 1.0, size=50)).tolist()
        res_rw = guard.estimate_hurst_rs(rw)
        assert 0.20 <= res_rw["h_hurst"] <= 0.85

    def test_evaluate_input_validations(self):
        guard = Wave505LobArfimaLongMemoryHurstGuard()

        with pytest.raises(ValueError, match="h_hurst"):
            guard.evaluate(h_hurst=1.5)

        with pytest.raises(ValueError, match="z_memory"):
            guard.evaluate(h_hurst=0.5, z_memory=15.0)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave505LobArfimaLongMemoryHurstGuard()
        # Normal Hurst ~ 0.50, d ~ 0.0
        res = guard.evaluate(h_hurst=0.50, d_frac=0.0, z_memory=0.1, timestamp=100.0)
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert res["psi_memory"] == 0.0

    def test_critical_long_memory_herd_runaway(self):
        guard = Wave505LobArfimaLongMemoryHurstGuard(max_hurst_threshold=0.78)
        res = guard.evaluate(h_hurst=0.84, d_frac=0.34, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "LONG_MEMORY_HERD_RUNAWAY" in res["reason"]

    def test_critical_memory_fragility_breach(self):
        guard = Wave505LobArfimaLongMemoryHurstGuard(critical_fragility_threshold=0.70)
        # Elevated Hurst (0.77) and elevated d (0.38) -> psi_memory >= 0.70
        res = guard.evaluate(h_hurst=0.77, d_frac=0.38, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "MEMORY_FRAGILITY_CRITICAL" in res["reason"]

    def test_hyper_antipersistent_jitter(self):
        guard = Wave505LobArfimaLongMemoryHurstGuard(min_hurst_threshold=0.28)
        res = guard.evaluate(h_hurst=0.22, d_frac=-0.28, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "HYPER_ANTIPERSISTENT_JITTER" in res["reason"]

    def test_asymmetric_directional_memory_overextensions(self):
        guard = Wave505LobArfimaLongMemoryHurstGuard(z_memory_warning_threshold=2.50)

        # Upward herd runaway overextension
        res_buy = guard.evaluate(h_hurst=0.60, d_frac=0.10, z_memory=2.85, timestamp=100.0)
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False

        # Downward herd flush overextension
        res_sell = guard.evaluate(h_hurst=0.60, d_frac=0.10, z_memory=-2.85, timestamp=100.0)
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False

    def test_cooldown_and_reset(self):
        guard = Wave505LobArfimaLongMemoryHurstGuard(cooldown_sec=2.0)
        res = guard.evaluate(h_hurst=0.90, timestamp=10.0)
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        res_cool = guard.evaluate(h_hurst=0.50, timestamp=11.0)
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate(h_hurst=0.50, timestamp=11.1)
        assert res_ok["action"] == "ALLOW_ALL"


class TestWave506ImperialSovereignMasterApexHyperionGuard:
    """Rigorous verification of Wave 506 Imperial Hyperion Master Guard."""

    def test_initialization_bounds(self):
        guard = Wave506ImperialSovereignMasterApexHyperionGuard(
            critical_canopy_threshold=0.65,
            dual_spike_threshold=0.85,
            cooldown_sec=2.0
        )
        assert guard.critical_canopy_threshold == 0.65
        assert guard.dual_spike_threshold == 0.85

        with pytest.raises(ValueError, match="critical_canopy_threshold"):
            Wave506ImperialSovereignMasterApexHyperionGuard(critical_canopy_threshold=0.30)

        with pytest.raises(ValueError, match="dual_spike_threshold"):
            Wave506ImperialSovereignMasterApexHyperionGuard(dual_spike_threshold=0.60)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave506ImperialSovereignMasterApexHyperionGuard(cooldown_sec=0.05)

    def test_input_range_validations(self):
        guard = Wave506ImperialSovereignMasterApexHyperionGuard()

        with pytest.raises(ValueError, match="hawkes_spectral_radius"):
            guard.evaluate(-0.1, 0.2, 0.0, 0.2, 0.2, 0.2, 0.2, 0.5, 0.0, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2)

        with pytest.raises(ValueError, match="psi_memory"):
            guard.evaluate(0.5, 0.2, 0.0, 0.2, 0.2, 0.2, 0.2, 0.5, 0.0, 0.2, 0.2, 0.2, 0.2, 0.2, 1.5)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave506ImperialSovereignMasterApexHyperionGuard()
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
            timestamp=100.0
        )
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert res["omega_canopy"] < 0.35
        assert res["spikes_count"] == 0

    def test_hyperion_canopy_breach(self):
        guard = Wave506ImperialSovereignMasterApexHyperionGuard(critical_canopy_threshold=0.65)
        # All 16 pillars elevated
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
            r_bid=3.60,                  # phi_10 = 0.900
            r_ask=1.0,
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "IMPERIAL_HYPERION_BREACH" in res["reason"]
        assert res["omega_canopy"] >= 0.65

    def test_dual_hazard_spike_trigger(self):
        guard = Wave506ImperialSovereignMasterApexHyperionGuard(
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
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "DUAL_HAZARD_SPIKE" in res["reason"]
        assert res["spikes_count"] >= 2

    def test_asymmetric_directional_toxicity(self):
        guard = Wave506ImperialSovereignMasterApexHyperionGuard()

        # Buy side toxicity via long-memory buy overextension (z_memory >= 2.50)
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
            z_memory=2.85, # z_memory >= 2.50
            timestamp=100.0
        )
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False

        # Sell side toxicity via long-memory sell overextension (z_memory <= -2.50)
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
            z_memory=-2.85, # z_memory <= -2.50
            timestamp=100.0
        )
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False

    def test_cooldown_and_reset(self):
        guard = Wave506ImperialSovereignMasterApexHyperionGuard(cooldown_sec=2.5)
        res = guard.evaluate(
            0.88, 0.70, 0.75, 0.65, 0.70, 0.65, 0.75, 0.85, 0.75, 0.70, 0.70, 0.70, 0.70, 0.70, 0.70,
            timestamp=10.0
        )
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        res_cool = guard.evaluate(
            0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1,
            timestamp=11.5
        )
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate(
            0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1,
            timestamp=11.6
        )
        assert res_ok["action"] == "ALLOW_ALL"
