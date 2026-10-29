"""
Batch 341 -- Tests for Wave 433 & Wave 434
==========================================
Wave 433: Asymmetric Trade Flow Poisson Arrival Intensity Guard
Wave 434: Mid-Price Hawkes Excitation Jump Guard

Target: 10+ tests, 100% pass rate
"""

import time
import pytest

from wave433_asymmetric_trade_flow_arrival_intensity_guard import (
    Wave433AsymmetricTradeFlowArrivalIntensityGuard,
)
from wave434_midprice_hawkes_excitation_jump_guard import (
    Wave434MidpriceHawkesExcitationJumpGuard,
)


class TestWave433ArrivalIntensityGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave433AsymmetricTradeFlowArrivalIntensityGuard(window_seconds=0.05)
        with pytest.raises(ValueError):
            Wave433AsymmetricTradeFlowArrivalIntensityGuard(max_asymmetry_ratio=1.5)
        with pytest.raises(ValueError):
            Wave433AsymmetricTradeFlowArrivalIntensityGuard(min_burst_intensity=-1.0)

    def test_balanced_trade_flow_no_block(self):
        guard = Wave433AsymmetricTradeFlowArrivalIntensityGuard(
            window_seconds=2.0, max_asymmetry_ratio=0.70, min_burst_intensity=5.0
        )
        t0 = time.monotonic()
        # Alternating buys and sells (asymmetry ~ 0.0)
        for i in range(20):
            guard.update(volume=1.0, is_buy=(i % 2 == 0), timestamp=t0 + i * 0.05)

        assert not guard.is_blocked()
        assert guard.arrival_asymmetry < 0.20
        assert guard.total_arrival_intensity > 15.0

    def test_asymmetric_arrival_burst_triggers_block(self):
        guard = Wave433AsymmetricTradeFlowArrivalIntensityGuard(
            window_seconds=1.0, max_asymmetry_ratio=0.75, min_burst_intensity=8.0, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # 15 consecutive buy trades in 0.5s with zero sell trades (asymmetry = 1.0)
        for i in range(15):
            guard.update(volume=2.0, is_buy=True, timestamp=t0 + i * 0.03)

        assert guard.is_blocked(t0 + 0.45)
        assert guard.last_reason == "ASYMMETRIC_TRADE_FLOW_IMBALANCE"
        assert guard.arrival_asymmetry >= 0.90

    def test_extreme_arrival_ceiling_triggers_block(self):
        guard = Wave433AsymmetricTradeFlowArrivalIntensityGuard(
            window_seconds=1.0, extreme_arrival_ceiling=50.0, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # 40 trades packed in 0.2 seconds -> arrival intensity = 200 trades/sec > 50.0 ceiling
        for i in range(40):
            guard.update(volume=1.0, is_buy=(i % 2 == 0), timestamp=t0 + i * 0.005)

        assert guard.is_blocked(t0 + 0.2)
        assert guard.last_reason == "EXTREME_FLOW_ARRIVAL_SUPERNOVA"

    def test_validation_and_reset(self):
        guard = Wave433AsymmetricTradeFlowArrivalIntensityGuard()
        t0 = time.monotonic()
        guard.update(volume=-5.0, is_buy=True, timestamp=t0)  # negative volume
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.arrival_asymmetry == 0.0


class TestWave434HawkesJumpGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave434MidpriceHawkesExcitationJumpGuard(jump_threshold=-0.01)
        with pytest.raises(ValueError):
            Wave434MidpriceHawkesExcitationJumpGuard(max_hawkes_intensity=0.01, baseline_mu=0.05)
        with pytest.raises(ValueError):
            Wave434MidpriceHawkesExcitationJumpGuard(catastrophic_jump_threshold=0.0001, jump_threshold=0.001)

    def test_calm_midprice_no_block(self):
        guard = Wave434MidpriceHawkesExcitationJumpGuard(
            jump_threshold=0.0005, max_hawkes_intensity=2.0
        )
        t0 = time.monotonic()
        # Tiny steady drift without jumps (< 0.0005)
        base = 2400.0
        for i in range(15):
            p = base + 0.05 * i
            guard.update(bid=p, ask=p + 0.02, timestamp=t0 + i * 0.1)

        assert not guard.is_blocked()
        assert guard.hawkes_intensity < 0.50

    def test_hawkes_jump_clustering_triggers_block(self):
        guard = Wave434MidpriceHawkesExcitationJumpGuard(
            jump_threshold=0.0003, alpha_excitation=1.0, beta_decay=0.5, max_hawkes_intensity=2.50, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Baseline
        guard.update(bid=2400.0, ask=2400.02, timestamp=t0)
        # 4 consecutive discrete jumps: each jumping by $2.0 (ret ~ 0.00083 > 0.0003) within 0.2s
        for i in range(1, 5):
            p = 2400.0 + 2.0 * i
            guard.update(bid=p, ask=p + 0.02, timestamp=t0 + i * 0.05)

        assert guard.is_blocked(t0 + 0.2)
        assert guard.last_reason == "SELF_EXCITING_HAWKES_JUMP_AVALANCHE"
        assert guard.hawkes_intensity >= 2.50

    def test_catastrophic_price_dislocation_triggers_block(self):
        guard = Wave434MidpriceHawkesExcitationJumpGuard(
            catastrophic_jump_threshold=0.010, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        guard.update(bid=2400.0, ask=2400.02, timestamp=t0)
        # Single-tick 1.5% jump ($36 gap)
        guard.update(bid=2436.0, ask=2436.02, timestamp=t0 + 0.1)

        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "CATASTROPHIC_PRICE_DISLOCATION"

    def test_validation_and_reset(self):
        guard = Wave434MidpriceHawkesExcitationJumpGuard()
        t0 = time.monotonic()
        guard.update(bid=2400.0, ask=2399.0, timestamp=t0)  # bid > ask
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.hawkes_intensity == guard._mu
