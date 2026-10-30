"""
Test Batch 359: Wave 467 Cross-Asset Spillover Guard & Wave 468 Apex Sovereign Canopy Synthesizer
===================================================================================================
Institutional unit test suite verifying cross-asset lead-lag spillover pressure,
7-dimensional microstructure fragility canopy synthesis, and dual-hazard circuit breakers.
"""

import pytest
import math
import numpy as np
from wave467_cross_asset_flow_spillover_guard import Wave467CrossAssetFlowSpilloverGuard
from wave468_orderbook_liquidity_fragility_canopy_synthesizer_guard import Wave468OrderbookLiquidityFragilityCanopySynthesizerGuard


class TestWave467CrossAssetFlowSpilloverGuard:
    """Test suite for Wave 467: Cross-Asset Order Flow Spillover Guard."""

    def test_init_validation(self):
        with pytest.raises(ValueError, match="window_size must be >= 15"):
            Wave467CrossAssetFlowSpilloverGuard(window_size=10)

        with pytest.raises(ValueError, match="max_spillover_pressure must be > 0.50"):
            Wave467CrossAssetFlowSpilloverGuard(max_spillover_pressure=0.30)

        with pytest.raises(ValueError, match="min_correlation_significance must be in"):
            Wave467CrossAssetFlowSpilloverGuard(min_correlation_significance=0.02)
        with pytest.raises(ValueError, match="min_correlation_significance must be in"):
            Wave467CrossAssetFlowSpilloverGuard(min_correlation_significance=0.95)

        with pytest.raises(ValueError, match="min_samples must be >= 8"):
            Wave467CrossAssetFlowSpilloverGuard(min_samples=5)

        with pytest.raises(ValueError, match="cooldown_sec must be >= 0.1"):
            Wave467CrossAssetFlowSpilloverGuard(cooldown_sec=0.05)

    def test_insufficient_samples(self):
        guard = Wave467CrossAssetFlowSpilloverGuard(min_samples=10)
        for i in range(6):
            blocked = guard.update(0.01, 1.0, timestamp=10.0 + i)
            assert not blocked
            assert not guard.is_blocked()
            assert guard.block_reason == "INSUFFICIENT_SAMPLES"

    def test_calm_independent_flow_no_block(self):
        guard = Wave467CrossAssetFlowSpilloverGuard(min_samples=10, max_spillover_pressure=2.00)

        # Feed calm, low-impact correlated flows
        for i in range(20):
            f = float(i % 4 + 1)
            r = 0.005 * f
            guard.update(r, f, timestamp=100.0 + i)

        assert not guard.is_blocked()
        assert not guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert abs(guard.spillover_pressure) < 1.80
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave467CrossAssetFlowSpilloverGuard"

    def test_foreign_buy_surge_blocks_sell(self):
        guard = Wave467CrossAssetFlowSpilloverGuard(
            min_samples=10,
            max_spillover_pressure=2.00,
            min_correlation_significance=0.20
        )

        # Baseline positive correlation coupling: r = 0.005 * f
        for i in range(12):
            f = float(i % 4 + 1)
            r = 0.005 * f
            guard.update(r, f, timestamp=100.0 + i)

        # Massive foreign positive flow surge in lead asset (Z_f > 3.0 sigma)
        blocked = guard.update(0.05, 50.0, timestamp=115.0)
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "SELL" # Heavy buying pressure incoming -> shorting is toxic
        assert guard.is_entry_blocked("SELL")
        assert not guard.is_entry_blocked("BUY")
        assert "CROSS_ASSET_SPILLOVER_SURGE" in guard.block_reason

    def test_foreign_sell_surge_blocks_buy(self):
        guard = Wave467CrossAssetFlowSpilloverGuard(
            min_samples=10,
            max_spillover_pressure=2.00,
            min_correlation_significance=0.20
        )

        for i in range(12):
            f = float(i % 4 + 1)
            r = 0.005 * f
            guard.update(r, f, timestamp=100.0 + i)

        # Massive negative foreign flow surge (Lead asset dump, Z_f < -3.0 sigma)
        blocked = guard.update(-0.05, -50.0, timestamp=115.0)
        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "BUY" # Heavy selling pressure incoming -> longs are toxic
        assert guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")

    def test_cooldown_and_reset(self):
        guard = Wave467CrossAssetFlowSpilloverGuard(min_samples=10, max_spillover_pressure=1.5, cooldown_sec=2.0)
        for i in range(12):
            f = float(i % 4 + 1)
            guard.update(0.005 * f, f, timestamp=10.0 + i)

        guard.update(0.1, 60.0, timestamp=30.0)
        assert guard.is_blocked()

        # Update within cooldown
        blocked = guard.update(0.001, 2.0, timestamp=31.0)
        assert blocked
        assert guard.is_blocked()

        # Reset
        guard.reset()
        assert not guard.is_blocked()
        assert guard.spillover_pressure == 0.0
        assert guard.blocked_side is None

    def test_input_validation(self):
        guard = Wave467CrossAssetFlowSpilloverGuard()
        with pytest.raises(ValueError, match="target_return must be finite"):
            guard.update(float("nan"), 1.0, timestamp=10.0)

        with pytest.raises(ValueError, match="timestamp must be strictly monotonic"):
            guard.update(0.01, 1.0, timestamp=10.0)
            guard.update(0.01, 1.0, timestamp=10.0)


class TestWave468OrderbookLiquidityFragilityCanopySynthesizerGuard:
    """Test suite for Wave 468: Grand Jubilee Apex Sovereign Canopy Master Synthesizer Guard."""

    def test_init_validation(self):
        with pytest.raises(ValueError, match="critical_canopy_threshold must be in"):
            Wave468OrderbookLiquidityFragilityCanopySynthesizerGuard(critical_canopy_threshold=0.20)
        with pytest.raises(ValueError, match="critical_canopy_threshold must be in"):
            Wave468OrderbookLiquidityFragilityCanopySynthesizerGuard(critical_canopy_threshold=0.95)

        with pytest.raises(ValueError, match="dual_spike_threshold must be in"):
            Wave468OrderbookLiquidityFragilityCanopySynthesizerGuard(dual_spike_threshold=0.50)
        with pytest.raises(ValueError, match="dual_spike_threshold must be in"):
            Wave468OrderbookLiquidityFragilityCanopySynthesizerGuard(dual_spike_threshold=0.99)

        with pytest.raises(ValueError, match="cooldown_sec must be >= 0.1"):
            Wave468OrderbookLiquidityFragilityCanopySynthesizerGuard(cooldown_sec=0.05)

    def test_calm_canopy_no_block(self):
        guard = Wave468OrderbookLiquidityFragilityCanopySynthesizerGuard(critical_canopy_threshold=0.65)

        # All 7 microstructure risks are low (~0.10)
        blocked = guard.update(
            entropy_loss=0.10,
            latency_jitter_risk=0.10,
            spectral_pulse_risk=0.10,
            drain_velocity_risk=0.10,
            queue_imbalance_risk=0.10,
            spread_expansion_risk=0.10,
            cross_asset_spillover_risk=0.10,
            timestamp=100.0
        )

        assert not blocked
        assert not guard.is_blocked()
        assert not guard.is_entry_blocked("BUY")
        assert not guard.is_entry_blocked("SELL")
        assert guard.composite_canopy_index < 0.15
        telem = guard.get_telemetry()
        assert telem["guard"] == "Wave468OrderbookLiquidityFragilityCanopySynthesizerGuard"

    def test_apex_canopy_breach_blocks_all(self):
        guard = Wave468OrderbookLiquidityFragilityCanopySynthesizerGuard(critical_canopy_threshold=0.65)

        # High across majority of dimensions (average ~ 0.75 > 0.65)
        blocked = guard.update(
            entropy_loss=0.75,
            latency_jitter_risk=0.80,
            spectral_pulse_risk=0.70,
            drain_velocity_risk=0.75,
            queue_imbalance_risk=0.80,
            spread_expansion_risk=0.70,
            cross_asset_spillover_risk=0.65,
            timestamp=150.0
        )

        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "ALL"
        assert guard.is_entry_blocked("BUY")
        assert guard.is_entry_blocked("SELL")
        assert "APEX_SOVEREIGN_CANOPY_BREACH" in guard.block_reason

    def test_dual_hazard_spike_blocks_all(self):
        guard = Wave468OrderbookLiquidityFragilityCanopySynthesizerGuard(
            critical_canopy_threshold=0.75, # High canopy threshold
            dual_spike_threshold=0.85
        )

        # Only 2 indicators spike >= 0.85, other 5 are zero
        # Overall average = 0.15*0.90 + 0.15*0.90 = 0.27 < 0.75
        # But dual hazard triggers immediate protection
        blocked = guard.update(
            entropy_loss=0.90,
            latency_jitter_risk=0.90,
            spectral_pulse_risk=0.0,
            drain_velocity_risk=0.0,
            queue_imbalance_risk=0.0,
            spread_expansion_risk=0.0,
            cross_asset_spillover_risk=0.0,
            timestamp=200.0
        )

        assert blocked
        assert guard.is_blocked()
        assert guard.blocked_side == "ALL"
        assert "DUAL_MICROSTRUCTURE_HAZARD_SPIKE" in guard.block_reason

    def test_cooldown_and_reset(self):
        guard = Wave468OrderbookLiquidityFragilityCanopySynthesizerGuard(cooldown_sec=2.0)
        guard.update(0.9, 0.9, 0.0, 0.0, 0.0, 0.0, 0.0, timestamp=10.0)
        assert guard.is_blocked()

        # Update within cooldown
        blocked = guard.update(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, timestamp=11.0)
        assert blocked
        assert guard.is_blocked()

        # Reset
        guard.reset()
        assert not guard.is_blocked()
        assert guard.composite_canopy_index == 0.0
        assert guard.blocked_side is None

    def test_input_validation(self):
        guard = Wave468OrderbookLiquidityFragilityCanopySynthesizerGuard()
        with pytest.raises(ValueError, match="non-negative and finite"):
            guard.update(-0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, timestamp=10.0)

        with pytest.raises(ValueError, match="timestamp must be strictly monotonic"):
            guard.update(0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, timestamp=10.0)
            guard.update(0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, timestamp=10.0)
