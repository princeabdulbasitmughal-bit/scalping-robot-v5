"""
Test Batch 361: Wave 471 Replenishment Half-Life Guard & Wave 472 Cross-Asset Flow Dispersion Guard
====================================================================================================
Institutional unit test suite verifying exponential replenishment relaxation half-life,
cross-sectional order flow dispersion, coordinated macro flow shocks, and canopy synthesis.
"""

import pytest
import math
import numpy as np
from wave471_liquidity_replenishment_halflife_decay_guard import Wave471LiquidityReplenishmentHalflifeDecayGuard
from wave472_cross_asset_flow_dispersion_synthesizer_guard import Wave472CrossAssetFlowDispersionSynthesizerGuard


class TestWave471LiquidityReplenishmentHalflifeDecayGuard:
    """Test suite for Wave 471: LOB Liquidity Replenishment Half-Life Decay Guard."""

    def test_init_validation(self):
        with pytest.raises(ValueError, match="depletion_threshold_pct must be in"):
            Wave471LiquidityReplenishmentHalflifeDecayGuard(depletion_threshold_pct=0.05)
        with pytest.raises(ValueError, match="max_halflife_sec must be in"):
            Wave471LiquidityReplenishmentHalflifeDecayGuard(max_halflife_sec=0.20)
        with pytest.raises(ValueError, match="min_recovery_ratio must be in"):
            Wave471LiquidityReplenishmentHalflifeDecayGuard(min_recovery_ratio=0.05)
        with pytest.raises(ValueError, match="eval_window_sec must be >= 0.50"):
            Wave471LiquidityReplenishmentHalflifeDecayGuard(eval_window_sec=0.20)
        with pytest.raises(ValueError, match="asymmetry_threshold must be in"):
            Wave471LiquidityReplenishmentHalflifeDecayGuard(asymmetry_threshold=0.30)
        with pytest.raises(ValueError, match="cooldown_sec must be >= 0.1"):
            Wave471LiquidityReplenishmentHalflifeDecayGuard(cooldown_sec=0.05)

    def test_calm_steady_market_no_block(self):
        guard = Wave471LiquidityReplenishmentHalflifeDecayGuard()
        # Initialize and steady trading
        for i in range(10):
            blocked = guard.update(50.0, 50.0, timestamp=100.0 + i)
            assert not blocked
            assert not guard.is_blocked()

        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave471LiquidityReplenishmentHalflifeDecayGuard"
        assert telem["in_depletion_event"] is False
        assert telem["is_blocked"] is False

    def test_normal_quick_replenishment_no_block(self):
        guard = Wave471LiquidityReplenishmentHalflifeDecayGuard(eval_window_sec=2.0)
        # Establish baseline 100 lots
        guard.update(50.0, 50.0, timestamp=100.0)
        guard.update(50.0, 50.0, timestamp=101.0)

        # Depletion shock occurs at 102.0: drops from 100 to 50
        guard.update(25.0, 25.0, timestamp=102.0)
        assert guard._in_depletion_event is True

        # Quick replenishment within 0.8s: recovers back to 95 lots
        blocked = guard.update(48.0, 47.0, timestamp=102.8)
        assert not blocked
        assert not guard.is_blocked()
        assert guard._in_depletion_event is False # Recovered >= 90%

    def test_replenishment_halflife_blowout_blocks_all(self):
        guard = Wave471LiquidityReplenishmentHalflifeDecayGuard(
            depletion_threshold_pct=0.25,
            max_halflife_sec=3.0,
            eval_window_sec=2.0
        )
        # Baseline 100 lots
        guard.update(50.0, 50.0, timestamp=100.0)
        guard.update(50.0, 50.0, timestamp=101.0)

        # Severe depletion shock at 102.0: drops from 100 to 40 lots (60% drop)
        guard.update(20.0, 20.0, timestamp=102.0)

        # Depth remains stuck at 40 lots (no recovery at all) for 2.2 seconds (past eval_window 2.0s)
        blocked = guard.update(20.0, 20.0, timestamp=104.2)
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "ALL"
        assert "REPLENISHMENT_HALFLIFE_EXPLOSION" in guard.block_reason or "INCOMPLETE_REPLENISHMENT_STALL" in guard.block_reason

    def test_asymmetric_bid_replenishment_paralysis_blocks_buy(self):
        guard = Wave471LiquidityReplenishmentHalflifeDecayGuard(
            depletion_threshold_pct=0.25,
            asymmetry_threshold=0.75,
            eval_window_sec=3.0 # Allow asymmetry to trigger after 1.0s before overall window
        )
        guard.update(50.0, 50.0, timestamp=100.0)
        guard.update(50.0, 50.0, timestamp=101.0)

        # Depletion to 30 lots (15 bid, 15 ask)
        guard.update(15.0, 15.0, timestamp=102.0)

        # Ask recovers quickly to 48 lots, but bid remains dead at 15 lots at t=103.5s
        blocked = guard.update(15.0, 48.0, timestamp=103.5)
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "BUY" # Bid paralyzed -> buying is toxic
        assert guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert "BID_REPLENISHMENT_PARALYZED" in guard.block_reason

    def test_asymmetric_ask_replenishment_paralysis_blocks_sell(self):
        guard = Wave471LiquidityReplenishmentHalflifeDecayGuard(
            depletion_threshold_pct=0.25,
            asymmetry_threshold=0.75,
            eval_window_sec=3.0
        )
        guard.update(50.0, 50.0, timestamp=100.0)
        guard.update(50.0, 50.0, timestamp=101.0)

        # Depletion to 30 lots
        guard.update(15.0, 15.0, timestamp=102.0)

        # Bid recovers quickly to 48 lots, but ask remains dead at 15 lots at t=103.5s
        blocked = guard.update(48.0, 15.0, timestamp=103.5)
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "SELL" # Ask paralyzed -> selling is toxic
        assert guard.is_entry_blocked("SELL")
        assert not guard.is_entry_blocked("BUY")
        assert "ASK_REPLENISHMENT_PARALYZED" in guard.block_reason

    def test_cooldown_and_reset(self):
        guard = Wave471LiquidityReplenishmentHalflifeDecayGuard(cooldown_sec=2.0, eval_window_sec=1.0)
        guard.update(50.0, 50.0, timestamp=100.0)
        guard.update(20.0, 20.0, timestamp=101.0)
        guard.update(20.0, 20.0, timestamp=102.5) # Breach

        assert guard.is_blocked()
        # Cooldown active
        assert guard.update(50.0, 50.0, timestamp=103.0) is True

        guard.reset()
        assert guard.baseline_bid_depth == 0.0
        assert guard.is_blocked() is False


class TestWave472CrossAssetFlowDispersionSynthesizerGuard:
    """Test suite for Wave 472: Cross-Asset Order Flow Shock Dispersion Synthesizer Guard."""

    def test_init_validation(self):
        with pytest.raises(ValueError, match="max_dispersion_threshold must be > 1.0"):
            Wave472CrossAssetFlowDispersionSynthesizerGuard(max_dispersion_threshold=0.80)
        with pytest.raises(ValueError, match="max_macro_shock_z must be > 1.0"):
            Wave472CrossAssetFlowDispersionSynthesizerGuard(max_macro_shock_z=0.50)
        with pytest.raises(ValueError, match="critical_canopy_threshold must be in"):
            Wave472CrossAssetFlowDispersionSynthesizerGuard(critical_canopy_threshold=0.30)
        with pytest.raises(ValueError, match="lead_flow_z_threshold must be > 0.50"):
            Wave472CrossAssetFlowDispersionSynthesizerGuard(lead_flow_z_threshold=0.30)
        with pytest.raises(ValueError, match="cooldown_sec must be >= 0.1"):
            Wave472CrossAssetFlowDispersionSynthesizerGuard(cooldown_sec=0.05)

    def test_input_vector_validation(self):
        guard = Wave472CrossAssetFlowDispersionSynthesizerGuard()
        with pytest.raises(ValueError, match="must contain at least 2 assets"):
            guard.update([1.0], timestamp=10.0)

    def test_calm_coupled_flows_no_block(self):
        guard = Wave472CrossAssetFlowDispersionSynthesizerGuard()
        # Mild correlated flows across 3 assets
        blocked = guard.update([0.2, 0.3, 0.1], replenishment_halflife=0.50, depth_curvature=1.0, timestamp=10.0)
        assert not blocked
        assert not guard.is_blocked()
        assert guard.flow_dispersion < 0.50
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave472CrossAssetFlowDispersionSynthesizerGuard"
        assert telem["is_blocked"] is False

    def test_cross_asset_flow_dispersion_breach(self):
        guard = Wave472CrossAssetFlowDispersionSynthesizerGuard(max_dispersion_threshold=2.80)
        # Severe multi-asset flow decoupling: [-3.5, 3.5, 0.0] -> std = sqrt(24.5) = 4.95 > 2.80
        blocked = guard.update([-3.5, 3.5, 0.0], replenishment_halflife=0.50, depth_curvature=1.0, timestamp=10.0)
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "ALL"
        assert "CROSS_ASSET_FLOW_DISPERSION_SHOCK" in guard.block_reason

    def test_macro_flow_shock_blocks_all(self):
        guard = Wave472CrossAssetFlowDispersionSynthesizerGuard(
            max_dispersion_threshold=5.0, # Broad so macro shock triggers first
            max_macro_shock_z=2.50
        )
        # Coordinated surge across all 3 assets: [2.8, 2.7, 2.9] -> Z_macro = 2.8 > 2.5, dispersion low
        blocked = guard.update([2.8, 2.7, 2.9], replenishment_halflife=0.50, depth_curvature=1.0, timestamp=10.0)
        assert blocked
        assert guard.is_blocked()
        assert guard.macro_shock_z >= 2.50
        assert "COORDINATED_MACRO_FLOW_SURGE" in guard.block_reason

    def test_lead_asset_buy_surge_blocks_sell(self):
        guard = Wave472CrossAssetFlowDispersionSynthesizerGuard(
            max_dispersion_threshold=5.0,
            max_macro_shock_z=3.5,
            lead_flow_z_threshold=2.0
        )
        # Lead asset surges to +2.5 sigma, other assets calm
        blocked = guard.update([2.5, 0.3, 0.2], replenishment_halflife=3.0, depth_curvature=-2.0, timestamp=10.0)
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "SELL" # Heavy foreign buying wave incoming -> selling is toxic
        assert guard.is_entry_blocked("SELL")
        assert not guard.is_entry_blocked("BUY")
        assert "LEAD_ASSET_BUY_SURGE" in guard.block_reason

    def test_lead_asset_dump_surge_blocks_buy(self):
        guard = Wave472CrossAssetFlowDispersionSynthesizerGuard(
            max_dispersion_threshold=5.0,
            max_macro_shock_z=3.5,
            lead_flow_z_threshold=2.0
        )
        # Lead asset dumps to -2.5 sigma
        blocked = guard.update([-2.5, -0.2, -0.1], replenishment_halflife=3.0, depth_curvature=-2.0, timestamp=10.0)
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "BUY" # Heavy foreign dumping incoming -> buying is toxic
        assert guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert "LEAD_ASSET_DUMP_SURGE" in guard.block_reason

    def test_sovereign_canopy_dispersion_breach(self):
        guard = Wave472CrossAssetFlowDispersionSynthesizerGuard(critical_canopy_threshold=0.68)
        # Moderate dispersion and high macro shock combined with severe replenishment blowout (4.0s) and concave curvature (-2.5)
        blocked = guard.update([2.8, 2.4, 2.0], replenishment_halflife=4.0, depth_curvature=-2.5, timestamp=10.0)
        assert blocked
        assert guard.is_blocked()
        assert guard.composite_canopy_index > 0.68

    def test_reset_and_monotonicity(self):
        guard = Wave472CrossAssetFlowDispersionSynthesizerGuard()
        guard.update([1.0, 1.0], timestamp=10.0)

        with pytest.raises(ValueError, match="strictly monotonic"):
            guard.update([1.0, 1.0], timestamp=9.5)

        guard.reset()
        assert guard.flow_dispersion == 0.0
        assert guard.is_blocked() is False
