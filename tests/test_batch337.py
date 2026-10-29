"""
Batch 337 -- Tests for Wave 426 & Wave 427
==========================================
Wave 426: Flow-Induced Market Impact Decay Guard
Wave 427: Cross-Tier Depth Co-Movement Beta Guard

Target: 10+ tests, 100% pass rate
"""

import time
import pytest

from wave426_flow_induced_impact_decay_guard import (
    Wave426FlowInducedImpactDecayGuard,
)
from wave427_cross_tier_depth_beta_guard import (
    Wave427CrossTierDepthBetaGuard,
)


class TestWave426ImpactDecayGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave426FlowInducedImpactDecayGuard(min_decay_threshold=1.5)
        with pytest.raises(ValueError):
            Wave426FlowInducedImpactDecayGuard(min_decay_velocity=-0.1)

    def test_healthy_transient_decay_no_block(self):
        guard = Wave426FlowInducedImpactDecayGuard(
            min_decay_threshold=0.30, min_decay_velocity=0.10, min_observation_sec=1.0
        )
        t0 = time.monotonic()
        # Initial impact 10 pips decays to 2 pips in 1.5s -> decay = 8/10 = 80% > 30%
        guard.update(impact_initial=10.0, impact_current=2.0, elapsed_sec=1.5, timestamp=t0 + 1.5)

        assert not guard.is_blocked()
        assert guard.decay_ratio >= 0.75

    def test_permanent_impact_triggers_block(self):
        guard = Wave426FlowInducedImpactDecayGuard(
            min_decay_threshold=0.40, min_observation_sec=1.0, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Impact was 10 pips, and after 2.0s is still 9 pips (decay = 10% < 40%)
        guard.update(impact_initial=10.0, impact_current=9.0, elapsed_sec=2.0, timestamp=t0 + 2.0)

        assert guard.is_blocked(t0 + 2.0)
        assert guard.last_reason == "PERMANENT_IMPACT_DISLOCATION"

    def test_validation_and_reset(self):
        guard = Wave426FlowInducedImpactDecayGuard()
        t0 = time.monotonic()
        guard.update(-5.0, 1.0, 1.0, t0)  # negative initial impact
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.decay_ratio == 1.0


class TestWave427CrossTierBetaGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave427CrossTierDepthBetaGuard(window_size=3)
        with pytest.raises(ValueError):
            Wave427CrossTierDepthBetaGuard(min_depth_beta=-2.0)
        with pytest.raises(ValueError):
            Wave427CrossTierDepthBetaGuard(max_depth_beta=0.1, min_depth_beta=0.5)

    def test_healthy_cross_tier_beta_no_block(self):
        guard = Wave427CrossTierDepthBetaGuard(
            window_size=8, min_depth_beta=0.30, max_depth_beta=2.50
        )
        t0 = time.monotonic()
        # Depth co-moves with beta ~ 1.0: deep depth delta = top depth delta
        for i in range(12):
            val = 100.0 + (10.0 if i % 2 == 0 else -10.0)
            guard.update(q_top=val, q_deep=val * 1.0, timestamp=t0 + i * 0.1)

        assert not guard.is_blocked()
        assert 0.80 <= guard.depth_beta <= 1.20

    def test_decoupled_depth_triggers_block(self):
        guard = Wave427CrossTierDepthBetaGuard(
            window_size=8, min_depth_beta=0.30, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Top-of-book fluctuates widely, but deep depth remains completely static (beta = 0.0 < 0.30)
        for i in range(12):
            val_top = 100.0 + (20.0 if i % 2 == 0 else -20.0)
            guard.update(q_top=val_top, q_deep=200.0, timestamp=t0 + i * 0.1)

        assert guard.is_blocked(t0 + 1.2)
        assert guard.last_reason == "CROSS_TIER_DEPTH_DECOUPLING"
        assert guard.depth_beta < 0.10

    def test_validation_and_reset(self):
        guard = Wave427CrossTierDepthBetaGuard()
        t0 = time.monotonic()
        guard.update(-10.0, 50.0, t0)  # negative depth
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.depth_beta == 1.0
