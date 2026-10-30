"""
Test Batch 376: Rigorous Quantitative Verification Suite
=========================================================
Covers:
  - Wave 501: High-Frequency Limit Order Book Multi-Scale Wavelet Variance Decomposition & Transient Liquidity Singularity Guard
  - Wave 502: Imperial Sovereign Master Apex Elysium Canopy Master Guard
"""

import pytest
import numpy as np
from wave501_lob_wavelet_variance_singularity_guard import Wave501LobWaveletVarianceSingularityGuard
from wave502_imperial_sovereign_master_apex_elysium_guard import Wave502ImperialSovereignMasterApexElysiumGuard


class TestWave501LobWaveletVarianceSingularityGuard:
    """Rigorous verification of Wave 501 Wavelet Variance & Singularity Guard."""

    def test_initialization_valid_and_invalid(self):
        guard = Wave501LobWaveletVarianceSingularityGuard(
            max_noise_ratio_threshold=0.75,
            min_holder_threshold=0.20,
            critical_fragility_threshold=0.70,
            z_wavelet_warning_threshold=2.50,
            cooldown_sec=2.0
        )
        assert guard.max_noise_ratio_threshold == 0.75
        assert guard.min_holder_threshold == 0.20

        with pytest.raises(ValueError, match="max_noise_ratio_threshold"):
            Wave501LobWaveletVarianceSingularityGuard(max_noise_ratio_threshold=0.40)

        with pytest.raises(ValueError, match="min_holder_threshold"):
            Wave501LobWaveletVarianceSingularityGuard(min_holder_threshold=0.05)

        with pytest.raises(ValueError, match="critical_fragility_threshold"):
            Wave501LobWaveletVarianceSingularityGuard(critical_fragility_threshold=0.35)

        with pytest.raises(ValueError, match="z_wavelet_warning_threshold"):
            Wave501LobWaveletVarianceSingularityGuard(z_wavelet_warning_threshold=1.20)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave501LobWaveletVarianceSingularityGuard(cooldown_sec=0.05)

    def test_decompose_wavelet_variances(self):
        guard = Wave501LobWaveletVarianceSingularityGuard()

        # Insufficient data
        with pytest.raises(ValueError, match="at least 8 observations"):
            guard.decompose_wavelet_variances([1.0, 2.0, 3.0, 4.0])

        # Smooth series (trend dominant -> low noise ratio)
        smooth = [100.0 + 0.5 * i for i in range(16)]
        res_smooth = guard.decompose_wavelet_variances(smooth)
        assert res_smooth["r_wavelet"] <= 0.60
        assert 0.0 <= res_smooth["h_singularity"] <= 1.0

        # Ultra high frequency ping-pong noise
        noisy = [100.0 + (1.0 if i % 2 == 0 else -1.0) for i in range(16)]
        res_noisy = guard.decompose_wavelet_variances(noisy)
        assert res_noisy["r_wavelet"] >= 0.70

    def test_evaluate_input_validations(self):
        guard = Wave501LobWaveletVarianceSingularityGuard()

        with pytest.raises(ValueError, match="r_wavelet"):
            guard.evaluate(r_wavelet=1.5, h_singularity=0.5)

        with pytest.raises(ValueError, match="h_singularity"):
            guard.evaluate(r_wavelet=0.5, h_singularity=-0.1)

        with pytest.raises(ValueError, match="z_wavelet"):
            guard.evaluate(r_wavelet=0.5, h_singularity=0.5, z_wavelet=15.0)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave501LobWaveletVarianceSingularityGuard()
        res = guard.evaluate(r_wavelet=0.35, h_singularity=0.55, z_wavelet=0.1, timestamp=100.0)
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert res["psi_wavelet"] == 0.0

    def test_critical_wavelet_noise_breach(self):
        guard = Wave501LobWaveletVarianceSingularityGuard(max_noise_ratio_threshold=0.75)
        res = guard.evaluate(r_wavelet=0.82, h_singularity=0.45, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "WAVELET_NOISE_SINGULARITY" in res["reason"]

    def test_critical_fragility_breach(self):
        guard = Wave501LobWaveletVarianceSingularityGuard(critical_fragility_threshold=0.70)
        # Elevated r_wavelet (0.72) and depressed Hölder exponent (0.15)
        res = guard.evaluate(r_wavelet=0.72, h_singularity=0.15, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert ("WAVELET_FRAGILITY_CRITICAL" in res["reason"] or "HOLDER_REGULARITY_BREAKDOWN" in res["reason"])

    def test_holder_regularity_breakdown(self):
        guard = Wave501LobWaveletVarianceSingularityGuard(min_holder_threshold=0.20)
        # h_singularity <= 0.20 and r_wavelet >= 0.40
        res = guard.evaluate(r_wavelet=0.55, h_singularity=0.12, timestamp=100.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "HOLDER_REGULARITY_BREAKDOWN" in res["reason"]

    def test_asymmetric_directional_wavelet_overextension(self):
        guard = Wave501LobWaveletVarianceSingularityGuard(z_wavelet_warning_threshold=2.50)

        # Parabolic upward blowout
        res_buy = guard.evaluate(r_wavelet=0.40, h_singularity=0.45, z_wavelet=2.85, timestamp=100.0)
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False

        # Liquidation singularity cascade
        res_sell = guard.evaluate(r_wavelet=0.40, h_singularity=0.45, z_wavelet=-2.85, timestamp=100.0)
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False

    def test_cooldown_and_reset(self):
        guard = Wave501LobWaveletVarianceSingularityGuard(cooldown_sec=2.0)
        res = guard.evaluate(r_wavelet=0.85, h_singularity=0.50, timestamp=10.0)
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        res_cool = guard.evaluate(r_wavelet=0.20, h_singularity=0.50, timestamp=11.0)
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate(r_wavelet=0.20, h_singularity=0.50, timestamp=11.1)
        assert res_ok["action"] == "ALLOW_ALL"


class TestWave502ImperialSovereignMasterApexElysiumGuard:
    """Rigorous verification of Wave 502 Imperial Elysium Master Guard."""

    def test_initialization_bounds(self):
        guard = Wave502ImperialSovereignMasterApexElysiumGuard(
            critical_canopy_threshold=0.65,
            dual_spike_threshold=0.85,
            cooldown_sec=2.0
        )
        assert guard.critical_canopy_threshold == 0.65
        assert guard.dual_spike_threshold == 0.85

        with pytest.raises(ValueError, match="critical_canopy_threshold"):
            Wave502ImperialSovereignMasterApexElysiumGuard(critical_canopy_threshold=0.30)

        with pytest.raises(ValueError, match="dual_spike_threshold"):
            Wave502ImperialSovereignMasterApexElysiumGuard(dual_spike_threshold=0.60)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave502ImperialSovereignMasterApexElysiumGuard(cooldown_sec=0.05)

    def test_input_range_validations(self):
        guard = Wave502ImperialSovereignMasterApexElysiumGuard()

        with pytest.raises(ValueError, match="hawkes_spectral_radius"):
            guard.evaluate(-0.1, 0.2, 0.0, 0.2, 0.2, 0.2, 0.2, 0.5, 0.0, 0.2, 0.2, 0.2, 0.2)

        with pytest.raises(ValueError, match="psi_wavelet"):
            guard.evaluate(0.5, 0.2, 0.0, 0.2, 0.2, 0.2, 0.2, 0.5, 0.0, 0.2, 0.2, 0.2, 1.5)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave502ImperialSovereignMasterApexElysiumGuard()
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
            timestamp=100.0
        )
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert res["omega_canopy"] < 0.35
        assert res["spikes_count"] == 0

    def test_elysium_canopy_breach(self):
        guard = Wave502ImperialSovereignMasterApexElysiumGuard(critical_canopy_threshold=0.65)
        # All 14 pillars elevated
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
            r_bid=3.60,                  # phi_10 = 0.900
            r_ask=1.0,
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "IMPERIAL_ELYSIUM_BREACH" in res["reason"]
        assert res["omega_canopy"] >= 0.65

    def test_dual_hazard_spike_trigger(self):
        guard = Wave502ImperialSovereignMasterApexElysiumGuard(
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
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "DUAL_HAZARD_SPIKE" in res["reason"]
        assert res["spikes_count"] >= 2

    def test_asymmetric_directional_toxicity(self):
        guard = Wave502ImperialSovereignMasterApexElysiumGuard()

        # Buy side toxicity via wavelet blowout (z_wavelet >= 2.50)
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
            z_wavelet=2.85, # z_wavelet >= 2.50
            timestamp=100.0
        )
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False

        # Sell side toxicity via wavelet liquidation cascade (z_wavelet <= -2.50)
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
            z_wavelet=-2.85, # z_wavelet <= -2.50
            timestamp=100.0
        )
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False

    def test_cooldown_and_reset(self):
        guard = Wave502ImperialSovereignMasterApexElysiumGuard(cooldown_sec=2.5)
        res = guard.evaluate(
            0.88, 0.70, 0.75, 0.65, 0.70, 0.65, 0.75, 0.85, 0.75, 0.70, 0.70, 0.70, 0.70,
            timestamp=10.0
        )
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        res_cool = guard.evaluate(
            0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1,
            timestamp=11.5
        )
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        guard.reset()
        assert guard.breaker_active is False
        res_ok = guard.evaluate(
            0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.0, 0.1, 0.1, 0.1, 0.1,
            timestamp=11.6
        )
        assert res_ok["action"] == "ALLOW_ALL"
