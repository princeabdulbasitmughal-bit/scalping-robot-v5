"""
Test Batch 367: Rigorous Quantitative Verification Suite
=========================================================
Covers:
  - Wave 483: Multi-Level Order Book Skewness Elasticity Guard
  - Wave 484: Imperial Sovereign Microstructure Canopy Master Guard
"""

import pytest
import numpy as np
from wave483_orderbook_skewness_elasticity_guard import Wave483OrderbookSkewnessElasticityGuard
from wave484_imperial_sovereign_microstructure_canopy_master_guard import Wave484ImperialSovereignMicrostructureCanopyMasterGuard


class TestWave483OrderbookSkewnessElasticityGuard:
    """Rigorous verification of Wave 483 Orderbook Skewness Elasticity Guard."""

    def test_initialization_valid_and_invalid(self):
        # Valid instantiation
        guard = Wave483OrderbookSkewnessElasticityGuard(
            skew_warning_threshold=0.65,
            skew_critical_threshold=0.85,
            max_velocity_threshold=1.80,
            cooldown_sec=2.0
        )
        assert guard.skew_warning_threshold == 0.65
        assert guard.skew_critical_threshold == 0.85

        # Invalid warning threshold
        with pytest.raises(ValueError, match="skew_warning_threshold"):
            Wave483OrderbookSkewnessElasticityGuard(skew_warning_threshold=0.20)

        # Invalid critical threshold
        with pytest.raises(ValueError, match="skew_critical_threshold"):
            Wave483OrderbookSkewnessElasticityGuard(skew_critical_threshold=0.99)

        # Inversion of thresholds
        with pytest.raises(ValueError, match="strictly less"):
            Wave483OrderbookSkewnessElasticityGuard(skew_warning_threshold=0.80, skew_critical_threshold=0.75)

        # Invalid max velocity
        with pytest.raises(ValueError, match="max_velocity_threshold"):
            Wave483OrderbookSkewnessElasticityGuard(max_velocity_threshold=0.10)

        # Invalid cooldown
        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave483OrderbookSkewnessElasticityGuard(cooldown_sec=0.05)

    def test_input_dimension_validations(self):
        guard = Wave483OrderbookSkewnessElasticityGuard()

        # Mismatched bid lengths
        with pytest.raises(ValueError, match="bid_prices length"):
            guard.evaluate([100.0, 99.0], [10.0], [101.0, 102.0], [10.0, 10.0])

        # Mismatched ask lengths
        with pytest.raises(ValueError, match="ask_prices length"):
            guard.evaluate([100.0, 99.0], [10.0, 10.0], [101.0], [10.0, 10.0])

        # Less than 2 levels
        with pytest.raises(ValueError, match="at least 2 levels"):
            guard.evaluate([100.0], [10.0], [101.0, 102.0], [10.0, 10.0])

        # Invalid tick size
        with pytest.raises(ValueError, match="tick_size must be positive"):
            guard.evaluate([100.0, 99.0], [10.0, 10.0], [101.0, 102.0], [10.0, 10.0], tick_size=-0.01)

    def test_zero_liquidity_handling(self):
        guard = Wave483OrderbookSkewnessElasticityGuard()
        res = guard.evaluate([100.0, 99.0], [0.0, 0.0], [101.0, 102.0], [10.0, 10.0])
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "ZERO_LIQUIDITY" in res["reason"]

    def test_symmetric_balanced_equilibrium(self):
        guard = Wave483OrderbookSkewnessElasticityGuard()
        # Symmetric 5-level book
        bid_p = [100.0, 99.9, 99.8, 99.7, 99.6]
        bid_v = [100.0, 80.0, 60.0, 40.0, 20.0]
        ask_p = [100.1, 100.2, 100.3, 100.4, 100.5]
        ask_v = [100.0, 80.0, 60.0, 40.0, 20.0]

        res = guard.evaluate(bid_p, bid_v, ask_p, ask_v, tick_size=0.1, timestamp=1000.0)
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert abs(res["xi_skew"]) < 1e-4

    def test_bid_hollowing_blocks_buy(self):
        guard = Wave483OrderbookSkewnessElasticityGuard(skew_warning_threshold=0.60, skew_critical_threshold=0.85)
        # Bid has tiny liquidity at top, huge volume deep down (d_bar_bid very large)
        # Ask has all volume at top of book (d_bar_ask ~ 1.0)
        bid_p = [100.0, 99.0, 98.0, 97.0, 96.0]
        bid_v = [0.1, 0.1, 0.1, 10.0, 500.0]
        ask_p = [100.1, 101.0, 102.0, 103.0, 104.0]
        ask_v = [500.0, 0.1, 0.1, 0.1, 0.1]

        res = guard.evaluate(bid_p, bid_v, ask_p, ask_v, tick_size=1.0, timestamp=1000.0)
        assert res["action"] == "BLOCK_BUY"
        assert res["circuit_breaker"] is False
        assert res["xi_skew"] >= 0.60

    def test_ask_hollowing_blocks_sell(self):
        guard = Wave483OrderbookSkewnessElasticityGuard(skew_warning_threshold=0.60, skew_critical_threshold=0.85)
        # Ask has tiny liquidity at top, huge volume deep down (d_bar_ask very large)
        # Bid has all volume at top of book (d_bar_bid ~ 1.0)
        bid_p = [100.0, 99.0, 98.0, 97.0, 96.0]
        bid_v = [500.0, 0.1, 0.1, 0.1, 0.1]
        ask_p = [100.1, 101.0, 102.0, 103.0, 104.0]
        ask_v = [0.1, 0.1, 0.1, 10.0, 500.0]

        res = guard.evaluate(bid_p, bid_v, ask_p, ask_v, tick_size=1.0, timestamp=1000.0)
        assert res["action"] == "BLOCK_SELL"
        assert res["circuit_breaker"] is False
        assert res["xi_skew"] <= -0.60

    def test_critical_skewness_breaker_and_cooldown(self):
        guard = Wave483OrderbookSkewnessElasticityGuard(skew_critical_threshold=0.80, cooldown_sec=3.0)
        # Extreme bid hollowing: bid 1000x volume at level 20, ask 100% volume at level 1
        bid_p = [100.0, 95.0, 90.0, 80.0, 50.0]
        bid_v = [0.001, 0.001, 0.001, 0.001, 10000.0]
        ask_p = [100.1, 101.0, 102.0, 103.0, 104.0]
        ask_v = [10000.0, 0.001, 0.001, 0.001, 0.001]

        res = guard.evaluate(bid_p, bid_v, ask_p, ask_v, tick_size=1.0, timestamp=1000.0)
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "SKEWNESS_CRITICAL_HALT" in res["reason"]

        # Cooldown check during 2 seconds (< 3.0s cooldown)
        res_cool = guard.evaluate(
            [100.0, 99.0], [100.0, 100.0],
            [101.0, 102.0], [100.0, 100.0],
            tick_size=1.0, timestamp=1002.0
        )
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        # Cooldown expired after 3.5 seconds
        res_exp = guard.evaluate(
            [100.0, 99.0], [100.0, 100.0],
            [101.0, 102.0], [100.0, 100.0],
            tick_size=1.0, timestamp=1003.5
        )
        assert res_exp["action"] == "ALLOW_ALL"
        assert res_exp["circuit_breaker"] is False

    def test_elasticity_velocity_breach(self):
        guard = Wave483OrderbookSkewnessElasticityGuard(max_velocity_threshold=1.50)
        # Step 1: Symmetric equilibrium (xi_skew ~ 0.0)
        guard.evaluate([100.0, 99.0], [50.0, 50.0], [101.0, 102.0], [50.0, 50.0], tick_size=1.0, timestamp=100.0)

        # Step 2: Sudden skew shift in dt = 0.1s
        # Bid becomes deep, ask becomes shallow
        res = guard.evaluate(
            [100.0, 95.0], [1.0, 100.0],
            [101.0, 102.0], [100.0, 1.0],
            tick_size=1.0, timestamp=100.1
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "ELASTICITY_VELOCITY_BREACH" in res["reason"]

    def test_reset(self):
        guard = Wave483OrderbookSkewnessElasticityGuard()
        guard.breaker_active = True
        guard.last_xi_skew = 0.88
        guard.reset()
        assert guard.breaker_active is False
        assert guard.last_xi_skew is None


class TestWave484ImperialSovereignMicrostructureCanopyMasterGuard:
    """Rigorous verification of Wave 484 Imperial Sovereign Canopy Master Guard."""

    def test_initialization_bounds(self):
        guard = Wave484ImperialSovereignMicrostructureCanopyMasterGuard(
            critical_canopy_threshold=0.65,
            dual_spike_threshold=0.85,
            cooldown_sec=2.0
        )
        assert guard.critical_canopy_threshold == 0.65
        assert guard.dual_spike_threshold == 0.85

        with pytest.raises(ValueError, match="critical_canopy_threshold"):
            Wave484ImperialSovereignMicrostructureCanopyMasterGuard(critical_canopy_threshold=0.30)

        with pytest.raises(ValueError, match="dual_spike_threshold"):
            Wave484ImperialSovereignMicrostructureCanopyMasterGuard(dual_spike_threshold=0.60)

        with pytest.raises(ValueError, match="cooldown_sec"):
            Wave484ImperialSovereignMicrostructureCanopyMasterGuard(cooldown_sec=0.05)

    def test_input_range_validations(self):
        guard = Wave484ImperialSovereignMicrostructureCanopyMasterGuard()

        with pytest.raises(ValueError, match="vpin"):
            guard.evaluate(vpin=-0.1, omega_480=0.2, hawkes_spectral_radius=0.5, resilience_fragility=0.2, xi_skew=0.0)

        with pytest.raises(ValueError, match="omega_480"):
            guard.evaluate(vpin=0.2, omega_480=1.5, hawkes_spectral_radius=0.5, resilience_fragility=0.2, xi_skew=0.0)

        with pytest.raises(ValueError, match="hawkes_spectral_radius"):
            guard.evaluate(vpin=0.2, omega_480=0.2, hawkes_spectral_radius=-0.1, resilience_fragility=0.2, xi_skew=0.0)

        with pytest.raises(ValueError, match="resilience_fragility"):
            guard.evaluate(vpin=0.2, omega_480=0.2, hawkes_spectral_radius=0.5, resilience_fragility=1.2, xi_skew=0.0)

        with pytest.raises(ValueError, match="xi_skew"):
            guard.evaluate(vpin=0.2, omega_480=0.2, hawkes_spectral_radius=0.5, resilience_fragility=0.2, xi_skew=1.5)

    def test_calm_equilibrium_allow_all(self):
        guard = Wave484ImperialSovereignMicrostructureCanopyMasterGuard()
        res = guard.evaluate(
            vpin=0.15,
            omega_480=0.10,
            hawkes_spectral_radius=0.30,
            resilience_fragility=0.15,
            xi_skew=0.05,
            hawkes_eta_buy=0.20,
            hawkes_eta_sell=0.20,
            timestamp=100.0
        )
        assert res["action"] == "ALLOW_ALL"
        assert res["circuit_breaker"] is False
        assert res["omega_canopy"] < 0.35
        assert res["spikes_count"] == 0

    def test_imperial_canopy_composite_breach(self):
        guard = Wave484ImperialSovereignMicrostructureCanopyMasterGuard(critical_canopy_threshold=0.65)
        # All pillars elevated to high values
        res = guard.evaluate(
            vpin=0.60,                   # phi_1 = 0.60 / 0.70 = 0.857
            omega_480=0.55,              # phi_2 = 0.55 / 0.65 = 0.846
            hawkes_spectral_radius=0.80, # phi_3 = 0.80 / 0.88 = 0.909
            resilience_fragility=0.60,   # phi_4 = 0.60 / 0.70 = 0.857
            xi_skew=0.65,                # phi_5 = 0.65 / 0.75 = 0.867
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "IMPERIAL_CANOPY_BREACH" in res["reason"]
        assert res["omega_canopy"] >= 0.65

    def test_dual_hazard_spike_trigger(self):
        guard = Wave484ImperialSovereignMicrostructureCanopyMasterGuard(
            critical_canopy_threshold=0.75,
            dual_spike_threshold=0.85
        )
        # Moderate overall canopy, but 2 pillars spike >= 0.85
        # phi_1: vpin=0.65 / 0.70 = 0.928 >= 0.85
        # phi_3: hawkes=0.80 / 0.88 = 0.909 >= 0.85
        # others very low
        res = guard.evaluate(
            vpin=0.65,
            omega_480=0.10,
            hawkes_spectral_radius=0.80,
            resilience_fragility=0.10,
            xi_skew=0.05,
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert res["circuit_breaker"] is True
        assert "DUAL_HAZARD_SPIKE" in res["reason"]
        assert res["spikes_count"] >= 2

    def test_asymmetric_directional_toxicity(self):
        guard = Wave484ImperialSovereignMicrostructureCanopyMasterGuard()

        # Buy side toxicity (Hawkes runaway buy or extreme bid hollowing)
        res_buy = guard.evaluate(
            vpin=0.20,
            omega_480=0.20,
            hawkes_spectral_radius=0.40,
            resilience_fragility=0.20,
            xi_skew=0.72, # xi_skew >= 0.70
            hawkes_eta_buy=0.40,
            hawkes_eta_sell=0.10,
            timestamp=100.0
        )
        assert res_buy["action"] == "BLOCK_BUY"
        assert res_buy["circuit_breaker"] is False

        # Sell side toxicity (Hawkes runaway sell)
        res_sell = guard.evaluate(
            vpin=0.20,
            omega_480=0.20,
            hawkes_spectral_radius=0.40,
            resilience_fragility=0.20,
            xi_skew=0.0,
            hawkes_eta_buy=0.10,
            hawkes_eta_sell=0.88, # eta_sell >= 0.85
            timestamp=100.0
        )
        assert res_sell["action"] == "BLOCK_SELL"
        assert res_sell["circuit_breaker"] is False

    def test_bilateral_directional_toxicity(self):
        guard = Wave484ImperialSovereignMicrostructureCanopyMasterGuard()
        res = guard.evaluate(
            vpin=0.20,
            omega_480=0.20,
            hawkes_spectral_radius=0.40,
            resilience_fragility=0.20,
            xi_skew=0.72,
            hawkes_eta_buy=0.20,
            hawkes_eta_sell=0.90,
            timestamp=100.0
        )
        assert res["action"] == "HALT_ALL"
        assert "BILATERAL" in res["reason"]

    def test_cooldown_and_reset(self):
        guard = Wave484ImperialSovereignMicrostructureCanopyMasterGuard(cooldown_sec=2.5)
        # Trigger breach
        res = guard.evaluate(0.70, 0.65, 0.88, 0.70, 0.75, timestamp=10.0)
        assert res["action"] == "HALT_ALL"
        assert guard.breaker_active is True

        # In cooldown
        res_cool = guard.evaluate(0.1, 0.1, 0.1, 0.1, 0.0, timestamp=11.5)
        assert res_cool["action"] == "HALT_ALL"
        assert "COOLDOWN_ACTIVE" in res_cool["reason"]

        # Reset
        guard.reset()
        assert guard.breaker_active is False
        res_after = guard.evaluate(0.1, 0.1, 0.1, 0.1, 0.0, timestamp=11.6)
        assert res_after["action"] == "ALLOW_ALL"
