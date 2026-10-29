"""
Batch 343 -- Tests for Wave 436 & Wave 437
==========================================
Wave 436: Orderbook Level-2 Skew Decay Elasticity Guard
Wave 437: Non-Stationary Realized Volatility Drift Curvature Guard

Target: 10+ tests, 100% pass rate
"""

import time
import pytest

from wave436_orderbook_skew_decay_elasticity_guard import (
    Wave436OrderbookSkewDecayElasticityGuard,
)
from wave437_volatility_drift_curvature_guard import (
    Wave437VolatilityDriftCurvatureGuard,
)


class TestWave436OrderbookSkewGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave436OrderbookSkewDecayElasticityGuard(window_size=3)
        with pytest.raises(ValueError):
            Wave436OrderbookSkewDecayElasticityGuard(critical_skew_threshold=1.2)
        with pytest.raises(ValueError):
            Wave436OrderbookSkewDecayElasticityGuard(inelastic_variance_floor=-0.01)

    def test_healthy_elastic_skew_no_block(self):
        guard = Wave436OrderbookSkewDecayElasticityGuard(
            window_size=10, critical_skew_threshold=0.70
        )
        t0 = time.monotonic()
        # Normal rebalancing skew fluctuating between -0.2 and +0.2
        for i in range(15):
            bid = 50.0 + (10.0 if i % 2 == 0 else -10.0)
            ask = 50.0 - (10.0 if i % 2 == 0 else -10.0)
            guard.update(bid_depth=bid, ask_depth=ask, midprice=2400.0, timestamp=t0 + i * 0.1)

        assert not guard.is_blocked()
        assert abs(guard.current_skew) < 0.30

    def test_inelastic_skew_lock_triggers_block(self):
        guard = Wave436OrderbookSkewDecayElasticityGuard(
            window_size=10, critical_skew_threshold=0.70, inelastic_variance_floor=0.01, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Constant frozen heavy buy wall (bid = 90, ask = 10 -> skew = 80/100 = 0.80 > 0.70)
        # Skew variance across 12 ticks is 0.0 < 0.01
        for i in range(12):
            guard.update(bid_depth=90.0, ask_depth=10.0, midprice=2400.0 + i * 0.1, timestamp=t0 + i * 0.1)

        assert guard.is_blocked(t0 + 1.2)
        assert guard.last_reason == "INELASTIC_ORDERBOOK_SKEW_LOCK"

    def test_erratic_skew_whipsaw_triggers_block(self):
        guard = Wave436OrderbookSkewDecayElasticityGuard(
            window_size=10, max_skew_whipsaw_std=0.50, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Violent whipsaw: skew oscillates between +0.90 and -0.90 every tick
        for i in range(12):
            if i % 2 == 0:
                guard.update(bid_depth=95.0, ask_depth=5.0, midprice=2400.0, timestamp=t0 + i * 0.1)
            else:
                guard.update(bid_depth=5.0, ask_depth=95.0, midprice=2400.0, timestamp=t0 + i * 0.1)

        assert guard.is_blocked(t0 + 1.2)
        assert guard.last_reason == "ERRATIC_SKEW_WHIPSAW"

    def test_validation_and_reset(self):
        guard = Wave436OrderbookSkewDecayElasticityGuard()
        t0 = time.monotonic()
        guard.update(-1.0, 50.0, 2400.0, t0)  # negative depth
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.current_skew == 0.0


class TestWave437VolatilityCurvatureGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave437VolatilityDriftCurvatureGuard(return_window=2)
        with pytest.raises(ValueError):
            Wave437VolatilityDriftCurvatureGuard(max_curvature_threshold=-5.0)
        with pytest.raises(ValueError):
            Wave437VolatilityDriftCurvatureGuard(extreme_vol_cutoff=0.0001, vol_activation_floor=0.001)

    def test_steady_linear_volatility_no_block(self):
        guard = Wave437VolatilityDriftCurvatureGuard(
            return_window=5, max_curvature_threshold=50.0
        )
        t0 = time.monotonic()
        # Small steady noise -> constant volatility -> curvature ~ 0
        base = 2400.0
        for i in range(15):
            noise = 0.05 if i % 2 == 0 else -0.05
            p = base + noise
            guard.update(bid=p, ask=p + 0.02, timestamp=t0 + i * 0.1)

        assert not guard.is_blocked()
        assert abs(guard.volatility_curvature) < 10.0

    def test_parabolic_volatility_curvature_triggers_block(self):
        guard = Wave437VolatilityDriftCurvatureGuard(
            return_window=4, max_curvature_threshold=1.50, vol_activation_floor=0.0002, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        base = 2400.0
        # Phase 1: ultra-quiet ticks (variance zero)
        for i in range(5):
            guard.update(bid=base, ask=base + 0.02, timestamp=t0 + i * 0.1)

        # Phase 2: modest price move
        guard.update(bid=base + 0.5, ask=base + 0.52, timestamp=t0 + 0.5)
        # Phase 3: explosive quadratically expanding price swing in very short dt (0.05s)
        guard.update(bid=base + 8.0, ask=base + 8.02, timestamp=t0 + 0.55)
        guard.update(bid=base - 8.0, ask=base - 7.98, timestamp=t0 + 0.58)

        assert guard.is_blocked(t0 + 0.58)
        assert guard.last_reason in [
            "PARABOLIC_VOLATILITY_CURVATURE_EXPLOSION",
            "EXTREME_VOLATILITY_REGIME_LOCKOUT",
        ]

    def test_extreme_volatility_regime_lockout_triggers_block(self):
        guard = Wave437VolatilityDriftCurvatureGuard(
            return_window=4, extreme_vol_cutoff=0.005, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Giant 2% swings -> vol > 0.005 immediately
        guard.update(bid=2400.0, ask=2400.02, timestamp=t0)
        guard.update(bid=2450.0, ask=2450.02, timestamp=t0 + 0.1)
        guard.update(bid=2350.0, ask=2350.02, timestamp=t0 + 0.2)
        guard.update(bid=2480.0, ask=2480.02, timestamp=t0 + 0.3)
        guard.update(bid=2320.0, ask=2320.02, timestamp=t0 + 0.4)

        assert guard.is_blocked(t0 + 0.4)
        assert guard.last_reason == "EXTREME_VOLATILITY_REGIME_LOCKOUT"

    def test_validation_and_reset(self):
        guard = Wave437VolatilityDriftCurvatureGuard()
        t0 = time.monotonic()
        guard.update(bid=2400.0, ask=2399.0, timestamp=t0)  # bid > ask
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.current_volatility == 0.0
