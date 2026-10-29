"""
Batch 333 -- Tests for Wave 420 Apex Sovereign Resiliency Guard
==============================================================
Wave 420: Apex Sovereign Resiliency & Multi-Horizon Guard

Target: 6+ tests, 100% pass rate
"""

import time
import pytest

from wave420_apex_sovereign_resiliency_guard import (
    Wave420ApexSovereignResiliencyGuard,
)


class TestWave420ApexResiliencyGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave420ApexSovereignResiliencyGuard(min_resiliency_threshold=1.5)
        with pytest.raises(ValueError):
            Wave420ApexSovereignResiliencyGuard(base_spread=-0.05)
        with pytest.raises(ValueError):
            Wave420ApexSovereignResiliencyGuard(max_mid_velocity=0.0)

    def test_robust_healthy_market_no_block(self):
        guard = Wave420ApexSovereignResiliencyGuard(
            min_resiliency_threshold=0.35, base_spread=0.05, base_depth=100.0
        )
        t0 = time.monotonic()
        # Tight spread (0.01), thick depth (100+100=200), balanced volume (50 buy, 50 sell)
        guard.update(
            bid=100.0,
            ask=100.01,
            bid_queue=100.0,
            ask_queue=100.0,
            recent_buy_vol=50.0,
            recent_sell_vol=50.0,
            timestamp=t0,
        )

        assert not guard.is_blocked()
        assert guard.resiliency_score >= 0.70

    def test_low_resiliency_triggers_collapse_block(self):
        guard = Wave420ApexSovereignResiliencyGuard(
            min_resiliency_threshold=0.45, base_spread=0.05, base_depth=100.0, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Moderate spread (0.10), thin depth (10+10=20), totally imbalanced flow (100 buy, 0 sell)
        # r_spread = exp(-2.0) = 0.135, r_depth = 0.20, r_flow = 0.0 -> composite < 0.45
        guard.update(
            bid=100.0,
            ask=100.10,
            bid_queue=10.0,
            ask_queue=10.0,
            recent_buy_vol=100.0,
            recent_sell_vol=0.0,
            timestamp=t0,
        )

        assert guard.is_blocked(t0)
        assert guard.last_reason in [
            "SOVEREIGN_RESILIENCY_COLLAPSE",
            "MULTI_HORIZON_MICROSTRUCTURE_FRACTURE",
        ]

    def test_multi_horizon_fracture_triggers_block(self):
        guard = Wave420ApexSovereignResiliencyGuard(
            min_resiliency_threshold=0.20, base_spread=0.05, base_depth=100.0, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Severe spread blowout (spread = 0.15 -> r_spread = exp(-3.0) = 0.05 < 0.20)
        # and severely hollowed depth (5+5=10 -> r_depth = 0.10 < 0.20)
        guard.update(
            bid=100.0,
            ask=100.15,
            bid_queue=5.0,
            ask_queue=5.0,
            recent_buy_vol=10.0,
            recent_sell_vol=10.0,
            timestamp=t0,
        )

        assert guard.is_blocked(t0)
        assert guard.last_reason == "MULTI_HORIZON_MICROSTRUCTURE_FRACTURE"

    def test_validation_and_reset(self):
        guard = Wave420ApexSovereignResiliencyGuard()
        t0 = time.monotonic()
        guard.update(100.0, 99.0, 10.0, 10.0, 10.0, 10.0, t0)  # bid > ask
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.resiliency_score == 1.0
