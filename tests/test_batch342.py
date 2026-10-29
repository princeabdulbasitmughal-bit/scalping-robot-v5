"""
Batch 342 -- Tests for Wave 435 Zenith Imperial Canopy Synthesizer Guard
========================================================================
Wave 435: Zenith Imperial Canopy Synthesizer Guard

Target: 6+ tests, 100% pass rate
"""

import time
import pytest

from wave435_zenith_imperial_canopy_synthesizer_guard import (
    Wave435ZenithImperialCanopySynthesizerGuard,
)


class TestWave435CanopySynthesizerGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave435ZenithImperialCanopySynthesizerGuard(critical_canopy_threshold=1.5)
        with pytest.raises(ValueError):
            Wave435ZenithImperialCanopySynthesizerGuard(convergence_count_threshold=9)
        with pytest.raises(ValueError):
            Wave435ZenithImperialCanopySynthesizerGuard(cooldown_seconds=-1.0)

    def test_calm_canopy_no_block(self):
        guard = Wave435ZenithImperialCanopySynthesizerGuard(
            critical_canopy_threshold=0.60
        )
        t0 = time.monotonic()
        guard.update(
            replenishment_accel_risk=0.10,
            vrp_jump_risk=0.08,
            arrival_asymmetry_risk=0.12,
            hawkes_jump_risk=0.05,
            zenith_fragility_risk=0.10,
            queue_depletion_risk=0.06,
            drift_exhaustion_risk=0.08,
            cross_tier_beta_risk=0.10,
            timestamp=t0,
        )

        assert not guard.is_blocked()
        assert guard.canopy_score < 0.15

    def test_composite_fragility_spike_triggers_block(self):
        guard = Wave435ZenithImperialCanopySynthesizerGuard(
            critical_canopy_threshold=0.65, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Elevated across all 8 dimensions (average 0.68 > 0.65)
        guard.update(
            replenishment_accel_risk=0.68,
            vrp_jump_risk=0.68,
            arrival_asymmetry_risk=0.68,
            hawkes_jump_risk=0.68,
            zenith_fragility_risk=0.68,
            queue_depletion_risk=0.68,
            drift_exhaustion_risk=0.68,
            cross_tier_beta_risk=0.68,
            timestamp=t0,
        )

        assert guard.is_blocked(t0)
        assert guard.last_reason == "ZENITH_IMPERIAL_CANOPY_FRAGILITY_SPIKE"
        assert guard.canopy_score >= 0.65

    def test_multi_vector_convergence_triggers_lockout(self):
        guard = Wave435ZenithImperialCanopySynthesizerGuard(
            critical_canopy_threshold=0.85, convergence_count_threshold=4, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # 4 signals tripped (>= 0.70) while 4 are calm (0.10)
        guard.update(
            replenishment_accel_risk=0.85,
            vrp_jump_risk=0.90,
            arrival_asymmetry_risk=0.80,
            hawkes_jump_risk=0.75,
            zenith_fragility_risk=0.10,
            queue_depletion_risk=0.10,
            drift_exhaustion_risk=0.10,
            cross_tier_beta_risk=0.10,
            timestamp=t0,
        )

        assert guard.is_blocked(t0)
        assert guard.last_reason == "CANOPY_MULTI_VECTOR_CONVERGENCE_LOCKOUT"

    def test_validation_and_reset(self):
        guard = Wave435ZenithImperialCanopySynthesizerGuard()
        t0 = time.monotonic()
        # Value > 1.0 invalid
        guard.update(1.5, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, t0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.canopy_score == 0.0

    def test_monotonic_timestamp_enforcement(self):
        guard = Wave435ZenithImperialCanopySynthesizerGuard()
        t0 = time.monotonic()
        guard.update(0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, t0 + 10.0)
        assert not guard.is_blocked(t0 + 10.0)

        # Regressive timestamp
        guard.update(0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, t0 + 5.0)
        assert guard.is_blocked(t0 + 5.0)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_is_entry_blocked_forwarding(self):
        guard = Wave435ZenithImperialCanopySynthesizerGuard(cooldown_seconds=30.0)
        t0 = time.monotonic()
        assert not guard.is_entry_blocked(bid=2400.0, ask=2400.2, ts=t0)

        guard.update(0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, t0)
        assert guard.is_entry_blocked(bid=2400.0, ask=2400.2, ts=t0)
