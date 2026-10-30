"""
Test Batch 366: Wave 481 Hawkes Branching Ratio Guard & Wave 482 Microstructure Resilience Tensor Guard
========================================================================================================
Institutional unit test suite verifying 2D Hawkes self/cross-excitation spectral radius,
directional branching cascades, multidimensional spread-depth resilience tensors, and recovery rate collapse.
"""

import pytest
import math
import numpy as np
from wave481_hawkes_cross_excitation_branching_ratio_guard import Wave481HawkesCrossExcitationBranchingRatioGuard
from wave482_microstructure_resilience_recovery_tensor_guard import Wave482MicrostructureResilienceRecoveryTensorGuard


class TestWave481HawkesCrossExcitationBranchingRatioGuard:
    """Test suite for Wave 481: Hawkes Cross-Excitation Branching Ratio Guard."""

    def test_init_validation(self):
        with pytest.raises(ValueError, match="max_spectral_radius must be in"):
            Wave481HawkesCrossExcitationBranchingRatioGuard(max_spectral_radius=0.40)
        with pytest.raises(ValueError, match="max_branching_ratio must be in"):
            Wave481HawkesCrossExcitationBranchingRatioGuard(max_branching_ratio=0.30)
        with pytest.raises(ValueError, match="asymmetry_threshold must be in"):
            Wave481HawkesCrossExcitationBranchingRatioGuard(asymmetry_threshold=0.05)
        with pytest.raises(ValueError, match="cooldown_sec must be >= 0.1"):
            Wave481HawkesCrossExcitationBranchingRatioGuard(cooldown_sec=0.05)

    def test_calm_subcritical_market_no_block(self):
        guard = Wave481HawkesCrossExcitationBranchingRatioGuard()
        # Subcritical entries: Gamma = [[0.2, 0.1], [0.1, 0.2]] -> rho = 0.30
        blocked = guard.update(g_bb=0.20, g_ba=0.10, g_ab=0.10, g_aa=0.20, timestamp=10.0)
        assert not blocked
        assert not guard.is_blocked()
        assert guard.spectral_radius < 0.50
        assert guard.eta_buy < 0.50
        assert guard.eta_sell < 0.50
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave481HawkesCrossExcitationBranchingRatioGuard"
        assert telem["is_blocked"] is False

    def test_hawkes_supercritical_cascade_blocks_all(self):
        guard = Wave481HawkesCrossExcitationBranchingRatioGuard(max_spectral_radius=0.88)
        # Supercritical: Gamma = [[0.70, 0.35], [0.35, 0.70]] -> eigenvalues: 0.70 + 0.35 = 1.05 > 0.88
        blocked = guard.update(g_bb=0.70, g_ba=0.35, g_ab=0.35, g_aa=0.70, timestamp=10.0)
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "ALL"
        assert guard.spectral_radius >= 0.88
        assert "HAWKES_SUPERCRITICAL_CASCADE" in guard.block_reason

    def test_runaway_buy_excitation_blocks_sell(self):
        guard = Wave481HawkesCrossExcitationBranchingRatioGuard(
            max_spectral_radius=0.88,
            max_branching_ratio=0.85,
            asymmetry_threshold=0.25
        )
        # Buy runaway: g_bb = 0.80, g_ab = 0.08 -> eta_buy = 0.88 > 0.85
        # g_aa = 0.05, g_ba = 0.05 -> eta_sell = 0.10, rho = 0.805 < 0.88
        # asymmetry = 0.88 - 0.10 = 0.78 > 0.25
        blocked = guard.update(g_bb=0.80, g_ba=0.05, g_ab=0.08, g_aa=0.05, timestamp=10.0)
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "SELL" # Heavy buyer runaway cascade -> shorting is toxic
        assert guard.is_entry_blocked("SELL")
        assert not guard.is_entry_blocked("BUY")
        assert "RUNAWAY_BUY_EXCITATION" in guard.block_reason

    def test_runaway_sell_excitation_blocks_buy(self):
        guard = Wave481HawkesCrossExcitationBranchingRatioGuard(
            max_spectral_radius=0.88,
            max_branching_ratio=0.85,
            asymmetry_threshold=0.25
        )
        # Sell runaway: eta_sell = 0.88, eta_buy = 0.10, rho = 0.805 < 0.88
        blocked = guard.update(g_bb=0.05, g_ba=0.08, g_ab=0.05, g_aa=0.80, timestamp=10.0)
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "BUY" # Heavy seller runaway cascade -> buying is toxic
        assert guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert "RUNAWAY_SELL_EXCITATION" in guard.block_reason

    def test_cooldown_and_reset(self):
        guard = Wave481HawkesCrossExcitationBranchingRatioGuard(cooldown_sec=2.0)
        guard.update(0.70, 0.35, 0.35, 0.70, timestamp=10.0) # Breach
        assert guard.is_blocked()

        # Cooldown active
        assert guard.update(0.10, 0.10, 0.10, 0.10, timestamp=11.0) is True

        # Cooldown expired and calm
        assert guard.update(0.10, 0.10, 0.10, 0.10, timestamp=13.0) is False

        guard.reset()
        assert guard.spectral_radius == 0.0
        assert guard.is_blocked() is False

    def test_monotonicity_validation(self):
        guard = Wave481HawkesCrossExcitationBranchingRatioGuard()
        guard.update(0.1, 0.1, 0.1, 0.1, timestamp=10.0)
        with pytest.raises(ValueError, match="strictly monotonic"):
            guard.update(0.1, 0.1, 0.1, 0.1, timestamp=9.5)


class TestWave482MicrostructureResilienceRecoveryTensorGuard:
    """Test suite for Wave 482: Microstructure Resilience Recovery Tensor Guard."""

    def test_init_validation(self):
        with pytest.raises(ValueError, match="critical_resilience_threshold must be in"):
            Wave482MicrostructureResilienceRecoveryTensorGuard(critical_resilience_threshold=0.30)
        with pytest.raises(ValueError, match="max_spread_expansion must be in"):
            Wave482MicrostructureResilienceRecoveryTensorGuard(max_spread_expansion=0.50)
        with pytest.raises(ValueError, match="paralysis_depth_floor must be in"):
            Wave482MicrostructureResilienceRecoveryTensorGuard(paralysis_depth_floor=0.05)
        with pytest.raises(ValueError, match="healthy_depth_floor must be in"):
            Wave482MicrostructureResilienceRecoveryTensorGuard(healthy_depth_floor=0.40)
        with pytest.raises(ValueError, match="cooldown_sec must be >= 0.1"):
            Wave482MicrostructureResilienceRecoveryTensorGuard(cooldown_sec=0.05)

    def test_calm_resilient_book_no_block(self):
        guard = Wave482MicrostructureResilienceRecoveryTensorGuard()
        # Normal spread and depth: spread 2.0 vs 2.0 baseline, depth 50 vs 50 baseline
        blocked = guard.update(
            current_spread=2.0,
            baseline_spread=2.0,
            current_bid_depth=50.0,
            baseline_bid_depth=50.0,
            current_ask_depth=50.0,
            baseline_ask_depth=50.0,
            timestamp=10.0
        )
        assert not blocked
        assert not guard.is_blocked()
        assert guard.spread_expansion_ratio == 0.0
        assert guard.composite_resilience_fragility == 0.0
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave482MicrostructureResilienceRecoveryTensorGuard"
        assert telem["is_blocked"] is False

    def test_spread_explosion_breach_blocks_all(self):
        guard = Wave482MicrostructureResilienceRecoveryTensorGuard(max_spread_expansion=2.50)
        # Current spread = 8.0, baseline = 2.0 -> expansion = (8 - 2)/2 = 3.0 > 2.50
        blocked = guard.update(
            current_spread=8.0,
            baseline_spread=2.0,
            current_bid_depth=40.0,
            baseline_bid_depth=50.0,
            current_ask_depth=40.0,
            baseline_ask_depth=50.0,
            timestamp=10.0
        )
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "ALL"
        assert guard.spread_expansion_ratio > 2.50
        assert "SPREAD_EXPLOSION_BREACH" in guard.block_reason

    def test_resilience_breakdown_composite_breach(self):
        guard = Wave482MicrostructureResilienceRecoveryTensorGuard(
            critical_resilience_threshold=0.70,
            max_spread_expansion=4.0 # High so composite fragility triggers
        )
        # Spread expanded 2.2x -> phi_spread = 2.2 / 2.5 = 0.88 -> 0.40 * 0.88 = 0.352
        # Bid depth collapsed to 10 vs 50 (R_bid = 0.20) -> phi_bid = 0.80 -> 0.30 * 0.80 = 0.24
        # Ask depth collapsed to 10 vs 50 (R_ask = 0.20) -> phi_ask = 0.80 -> 0.30 * 0.80 = 0.24
        # Psi = 0.352 + 0.24 + 0.24 = 0.832 > 0.70
        blocked = guard.update(
            current_spread=6.4,
            baseline_spread=2.0,
            current_bid_depth=10.0,
            baseline_bid_depth=50.0,
            current_ask_depth=10.0,
            baseline_ask_depth=50.0,
            timestamp=10.0
        )
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "ALL"
        assert guard.composite_resilience_fragility > 0.70

    def test_bid_resilience_paralysis_blocks_buy(self):
        guard = Wave482MicrostructureResilienceRecoveryTensorGuard(
            critical_resilience_threshold=0.85, # High so directional triggers first
            max_spread_expansion=4.0,
            paralysis_depth_floor=0.25,
            healthy_depth_floor=0.60
        )
        # Spread calm (2.0 vs 2.0). Bid collapsed to 10 vs 50 (R_bid = 0.20 < 0.25)
        # Ask remains healthy at 40 vs 50 (R_ask = 0.80 >= 0.60)
        blocked = guard.update(
            current_spread=2.0,
            baseline_spread=2.0,
            current_bid_depth=10.0,
            baseline_bid_depth=50.0,
            current_ask_depth=40.0,
            baseline_ask_depth=50.0,
            timestamp=10.0
        )
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "BUY" # Bid depth paralyzed -> buying is toxic
        assert guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert "BID_RESILIENCE_PARALYSIS" in guard.block_reason

    def test_ask_resilience_paralysis_blocks_sell(self):
        guard = Wave482MicrostructureResilienceRecoveryTensorGuard(
            critical_resilience_threshold=0.85,
            max_spread_expansion=4.0,
            paralysis_depth_floor=0.25,
            healthy_depth_floor=0.60
        )
        # Ask collapsed to 10 vs 50 (R_ask = 0.20 < 0.25), Bid healthy at 40 vs 50 (0.80)
        blocked = guard.update(
            current_spread=2.0,
            baseline_spread=2.0,
            current_bid_depth=40.0,
            baseline_bid_depth=50.0,
            current_ask_depth=10.0,
            baseline_ask_depth=50.0,
            timestamp=10.0
        )
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "SELL" # Ask depth paralyzed -> selling is toxic
        assert guard.is_entry_blocked("SELL")
        assert not guard.is_entry_blocked("BUY")
        assert "ASK_RESILIENCE_PARALYSIS" in guard.block_reason

    def test_cooldown_and_reset(self):
        guard = Wave482MicrostructureResilienceRecoveryTensorGuard(cooldown_sec=2.0)
        guard.update(8.0, 2.0, 10.0, 50.0, 10.0, 50.0, timestamp=10.0) # Breach
        assert guard.is_blocked()

        # In cooldown
        assert guard.update(2.0, 2.0, 50.0, 50.0, 50.0, 50.0, timestamp=11.0) is True

        # Cooldown expired and calm
        assert guard.update(2.0, 2.0, 50.0, 50.0, 50.0, 50.0, timestamp=13.0) is False

        guard.reset()
        assert guard.spread_expansion_ratio == 0.0
        assert guard.is_blocked() is False

    def test_monotonicity_validation(self):
        guard = Wave482MicrostructureResilienceRecoveryTensorGuard()
        guard.update(2.0, 2.0, 50.0, 50.0, 50.0, 50.0, timestamp=10.0)
        with pytest.raises(ValueError, match="strictly monotonic"):
            guard.update(2.0, 2.0, 50.0, 50.0, 50.0, 50.0, timestamp=9.5)
