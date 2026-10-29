"""
Batch 347 -- Tests for Wave 443 & Wave 444
==========================================
Wave 443: High-Frequency Cross-Asset Lead-Lag Information Transfer Guard
Wave 444: Microstructure Price Impact Decay Asymmetry Guard

Target: 10+ tests, 100% pass rate
"""

import time
import pytest

from wave443_cross_asset_lead_lag_transfer_guard import (
    Wave443CrossAssetLeadLagTransferGuard,
)
from wave444_price_impact_decay_asymmetry_guard import (
    Wave444PriceImpactDecayAsymmetryGuard,
)


class TestWave443CrossAssetLeadLagGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave443CrossAssetLeadLagTransferGuard(lead_shock_threshold=-0.01)
        with pytest.raises(ValueError):
            Wave443CrossAssetLeadLagTransferGuard(max_propagation_window_sec=0.005)
        with pytest.raises(ValueError):
            Wave443CrossAssetLeadLagTransferGuard(lead_vol_ceiling=0.0001, lead_shock_threshold=0.001)

    def test_calm_lead_asset_no_block(self):
        guard = Wave443CrossAssetLeadLagTransferGuard(
            lead_shock_threshold=0.0010, max_propagation_window_sec=0.50
        )
        t0 = time.monotonic()
        # Lead asset (e.g. DXY) barely moves (103.50 + 0.001 each tick -> return 0.00001 < 0.0010)
        base = 103.50
        for i in range(10):
            lead_p = base + 0.001 * i
            guard.update(lead_price=lead_p, target_bid=2400.0, target_ask=2400.2, timestamp=t0 + i * 0.1)

        assert not guard.is_blocked()
        assert not guard.is_propagation_pending

    def test_lead_shock_triggers_pending_block(self):
        guard = Wave443CrossAssetLeadLagTransferGuard(
            lead_shock_threshold=0.0008, max_propagation_window_sec=0.40, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        guard.update(lead_price=103.50, target_bid=2400.0, target_ask=2400.2, timestamp=t0)
        # Sharp surge in lead asset: 103.50 -> 103.65 (ret = 0.00145 > 0.0008)
        guard.update(lead_price=103.65, target_bid=2400.0, target_ask=2400.2, timestamp=t0 + 0.05)

        assert guard.is_blocked(t0 + 0.05)
        assert guard.last_reason == "LATENT_CROSS_ASSET_IMPACT_PENDING"
        assert guard.is_propagation_pending

    def test_lead_asset_volatility_supernova_triggers_block(self):
        guard = Wave443CrossAssetLeadLagTransferGuard(
            lead_vol_ceiling=0.0030, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        guard.update(lead_price=100.0, target_bid=2400.0, target_ask=2400.2, timestamp=t0)
        # 1% macro gap in lead anchor asset
        guard.update(lead_price=101.0, target_bid=2400.0, target_ask=2400.2, timestamp=t0 + 0.1)

        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "LEAD_ASSET_VOLATILITY_SUPERNOVA"

    def test_validation_and_reset(self):
        guard = Wave443CrossAssetLeadLagTransferGuard()
        t0 = time.monotonic()
        guard.update(lead_price=-100.0, target_bid=2400.0, target_ask=2400.2, timestamp=t0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert not guard.is_propagation_pending


class TestWave444PriceImpactAsymmetryGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave444PriceImpactDecayAsymmetryGuard(max_decay_asymmetry=1.5)
        with pytest.raises(ValueError):
            Wave444PriceImpactDecayAsymmetryGuard(min_decay_ratio=-0.1)

    def test_symmetric_impact_decay_no_block(self):
        guard = Wave444PriceImpactDecayAsymmetryGuard(max_decay_asymmetry=0.60)
        t0 = time.monotonic()
        # Both buy impact and sell impact decay by 50% in 1.0s -> beta_buy = 0.5, beta_sell = 0.5 -> asym = 0
        guard.update(
            buy_initial=10.0, buy_current=5.0,
            sell_initial=10.0, sell_current=5.0,
            dt_sec=1.0, timestamp=t0
        )

        assert not guard.is_blocked()
        assert guard.decay_asymmetry < 0.10

    def test_asymmetric_decay_triggers_block(self):
        guard = Wave444PriceImpactDecayAsymmetryGuard(
            max_decay_asymmetry=0.50, min_decay_ratio=0.20, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Buy impact decays 80% (10 -> 2), but sell impact decays only 25% (10 -> 7.5) in 1.0s
        # beta_buy = 0.8, beta_sell = 0.25 -> asym = (0.8 - 0.25)/(0.8 + 0.25) = 0.55/1.05 = 0.523 > 0.50
        guard.update(
            buy_initial=10.0, buy_current=2.0,
            sell_initial=10.0, sell_current=7.5,
            dt_sec=1.0, timestamp=t0
        )

        assert guard.is_blocked(t0)
        assert guard.last_reason == "ASYMMETRIC_IMPACT_DECAY_DISTORTION"
        assert guard.decay_asymmetry >= 0.50

    def test_permanent_impact_residual_lock_triggers_block(self):
        guard = Wave444PriceImpactDecayAsymmetryGuard(
            min_decay_ratio=0.25, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Buy impact decays 60% (10 -> 4), but sell impact barely decays 5% (10 -> 9.5 < 25% min decay)
        guard.update(
            buy_initial=10.0, buy_current=4.0,
            sell_initial=10.0, sell_current=9.5,
            dt_sec=1.0, timestamp=t0
        )

        assert guard.is_blocked(t0)
        assert guard.last_reason == "PERMANENT_IMPACT_RESIDUAL_LOCK"

    def test_validation_and_reset(self):
        guard = Wave444PriceImpactDecayAsymmetryGuard()
        t0 = time.monotonic()
        guard.update(-1.0, 5.0, 10.0, 5.0, 1.0, t0)  # negative initial impact
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.decay_asymmetry == 0.0
