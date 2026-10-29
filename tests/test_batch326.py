"""
Batch 326 -- Tests for Wave 408 & Wave 409
==========================================
Wave 408: Jump Diffusion & Realized Bipower Variation (BV) Guard
Wave 409: Orderbook Micro-Price Skew & Drift Guard

Target: 10+ tests, 100% pass rate
"""

import time
import pytest

from wave408_jump_diffusion_bipower_variation_guard import (
    Wave408JumpDiffusionBipowerVariationGuard,
)
from wave409_orderbook_microprice_skew_drift_guard import (
    Wave409OrderbookMicropriceSkewDriftGuard,
)


class TestWave408JumpDiffusionGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave408JumpDiffusionBipowerVariationGuard(window_size=3)
        with pytest.raises(ValueError):
            Wave408JumpDiffusionBipowerVariationGuard(max_jump_ratio=1.5)
        with pytest.raises(ValueError):
            Wave408JumpDiffusionBipowerVariationGuard(jump_sigma_mult=0.5)

    def test_continuous_brownian_motion_no_block(self):
        guard = Wave408JumpDiffusionBipowerVariationGuard(
            window_size=10, max_jump_ratio=0.50, jump_sigma_mult=5.0
        )
        t0 = time.monotonic()
        # Smooth continuous oscillating price path (RV ~ BV, S_jump ~ 0)
        p = 100.0
        for i in range(20):
            p += 0.05 if i % 2 == 0 else -0.05
            guard.update(bid=p, ask=p + 0.1, timestamp=t0 + i * 0.1)

        assert not guard.is_blocked()
        assert guard.jump_ratio < 0.20

    def test_jump_ratio_spike_triggers_block(self):
        guard = Wave408JumpDiffusionBipowerVariationGuard(
            window_size=8, max_jump_ratio=0.35, jump_sigma_mult=10.0, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Flat baseline
        for i in range(8):
            guard.update(bid=100.0, ask=100.02, timestamp=t0 + i * 0.1)

        # Discrete massive jump break
        guard.update(bid=108.0, ask=108.02, timestamp=t0 + 1.0)
        # Another jump to establish window
        guard.update(bid=108.01, ask=108.03, timestamp=t0 + 1.1)

        assert guard.is_blocked(t0 + 1.1)
        assert guard.last_reason in ["JUMP_DIFFUSION_INTENSITY_SPIKE", "DISCONTINUOUS_PRICE_JUMP"]

    def test_single_discontinuous_jump_triggers_block(self):
        guard = Wave408JumpDiffusionBipowerVariationGuard(
            window_size=10, max_jump_ratio=0.80, jump_sigma_mult=3.0, cooldown_seconds=30.0
        )
        t0 = time.monotonic()
        # Stable low variance
        p = 100.0
        for i in range(12):
            p += 0.01 if i % 2 == 0 else -0.01
            guard.update(bid=p, ask=p + 0.02, timestamp=t0 + i * 0.1)

        # Sudden 4-sigma jump
        guard.update(bid=105.0, ask=105.02, timestamp=t0 + 2.0)

        assert guard.is_blocked(t0 + 2.0)
        assert guard.last_reason == "DISCONTINUOUS_PRICE_JUMP"

    def test_validation_and_reset(self):
        guard = Wave408JumpDiffusionBipowerVariationGuard(window_size=5)
        t0 = time.monotonic()
        guard.update(bid=-10.0, ask=10.0, timestamp=t0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""


class TestWave409MicropriceSkewGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave409OrderbookMicropriceSkewDriftGuard(window_size=2)
        with pytest.raises(ValueError):
            Wave409OrderbookMicropriceSkewDriftGuard(max_skew_ratio=1.2)
        with pytest.raises(ValueError):
            Wave409OrderbookMicropriceSkewDriftGuard(max_skew_drift=0.1)

    def test_balanced_book_no_block(self):
        guard = Wave409OrderbookMicropriceSkewDriftGuard(
            window_size=5, max_skew_ratio=0.75, max_skew_drift=0.50
        )
        t0 = time.monotonic()
        # Balanced queues (skew ~ 0.0)
        for i in range(10):
            guard.update(
                bid=100.0,
                ask=100.02,
                bid_queue=50.0,
                ask_queue=50.0,
                timestamp=t0 + i * 0.1,
            )

        assert not guard.is_blocked()
        assert abs(guard.current_skew) < 0.05
        assert abs(guard.current_microprice - 100.01) < 0.001

    def test_extreme_skew_triggers_block(self):
        guard = Wave409OrderbookMicropriceSkewDriftGuard(
            window_size=5, max_skew_ratio=0.75, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Bid heavily dominant (95 vs 5 -> skew = 90 / 100 = 0.90 > 0.75)
        guard.update(
            bid=100.0,
            ask=100.02,
            bid_queue=95.0,
            ask_queue=5.0,
            timestamp=t0,
        )

        assert guard.is_blocked(t0)
        assert guard.last_reason == "MICROPRICE_ASYMMETRY_SKEW"
        assert guard.current_skew >= 0.85

    def test_skew_drift_velocity_spike(self):
        guard = Wave409OrderbookMicropriceSkewDriftGuard(
            window_size=5, max_skew_ratio=0.95, max_skew_drift=0.60, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Initially ask dominant (skew = -0.50)
        for i in range(5):
            guard.update(
                bid=100.0,
                ask=100.02,
                bid_queue=25.0,
                ask_queue=75.0,
                timestamp=t0 + i * 0.1,
            )

        assert not guard.is_blocked()

        # Rapid drift to bid dominant (skew = +0.50), drift = 1.0 > 0.60
        guard.update(
            bid=100.0,
            ask=100.02,
            bid_queue=75.0,
            ask_queue=25.0,
            timestamp=t0 + 1.0,
        )

        assert guard.is_blocked(t0 + 1.0)
        assert guard.last_reason == "SKEW_DRIFT_VELOCITY_SPIKE"

    def test_validation_and_reset(self):
        guard = Wave409OrderbookMicropriceSkewDriftGuard(window_size=5)
        t0 = time.monotonic()
        guard.update(100.0, 99.0, 10.0, 10.0, t0)  # bid > ask
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""
