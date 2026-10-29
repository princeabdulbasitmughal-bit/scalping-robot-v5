"""
Batch 339 -- Tests for Wave 430 Grand Sovereign Zenith Synthesizer Guard
========================================================================
Wave 430: Grand Sovereign Zenith Synthesizer Guard

Target: 6+ tests, 100% pass rate
"""

import time
import pytest

from wave430_grand_sovereign_zenith_synthesizer_guard import (
    Wave430GrandSovereignZenithSynthesizerGuard,
)


class TestWave430GrandSovereignZenithSynthesizerGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave430GrandSovereignZenithSynthesizerGuard(critical_zenith_threshold=1.5)
        with pytest.raises(ValueError):
            Wave430GrandSovereignZenithSynthesizerGuard(convergence_count_threshold=9)
        with pytest.raises(ValueError):
            Wave430GrandSovereignZenithSynthesizerGuard(cooldown_seconds=-1.0)

    def test_calm_microstructure_no_block(self):
        guard = Wave430GrandSovereignZenithSynthesizerGuard(
            critical_zenith_threshold=0.60
        )
        t0 = time.monotonic()
        guard.update(
            impact_decay_risk=0.10,
            cross_tier_decoupling_risk=0.12,
            drift_exhaustion_risk=0.08,
            queue_depletion_risk=0.05,
            imperial_fragility_risk=0.10,
            quarticity_jump_risk=0.15,
            spread_asymmetry_risk=0.07,
            trade_burst_risk=0.09,
            timestamp=t0,
        )

        assert not guard.is_blocked()
        assert guard.zenith_score < 0.15

    def test_composite_zenith_spike_triggers_block(self):
        guard = Wave430GrandSovereignZenithSynthesizerGuard(
            critical_zenith_threshold=0.65, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Elevated across all 8 dimensions (average 0.68 > 0.65)
        guard.update(
            impact_decay_risk=0.68,
            cross_tier_decoupling_risk=0.68,
            drift_exhaustion_risk=0.68,
            queue_depletion_risk=0.68,
            imperial_fragility_risk=0.68,
            quarticity_jump_risk=0.68,
            spread_asymmetry_risk=0.68,
            trade_burst_risk=0.68,
            timestamp=t0,
        )

        assert guard.is_blocked(t0)
        assert guard.last_reason == "ZENITH_SOVEREIGN_RISK_SPIKE"
        assert guard.zenith_score >= 0.65

    def test_multi_vector_convergence_triggers_lockout(self):
        guard = Wave430GrandSovereignZenithSynthesizerGuard(
            critical_zenith_threshold=0.85, convergence_count_threshold=4, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # 4 signals tripped (>= 0.70) while 4 are low (0.10)
        guard.update(
            impact_decay_risk=0.85,
            cross_tier_decoupling_risk=0.90,
            drift_exhaustion_risk=0.78,
            queue_depletion_risk=0.72,
            imperial_fragility_risk=0.10,
            quarticity_jump_risk=0.10,
            spread_asymmetry_risk=0.10,
            trade_burst_risk=0.10,
            timestamp=t0,
        )

        assert guard.is_blocked(t0)
        assert guard.last_reason == "ZENITH_MULTI_VECTOR_CONVERGENCE_LOCKOUT"

    def test_validation_and_reset(self):
        guard = Wave430GrandSovereignZenithSynthesizerGuard()
        t0 = time.monotonic()
        # Value > 1.0 invalid
        guard.update(1.2, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, t0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.zenith_score == 0.0

    def test_monotonic_timestamp_enforcement(self):
        guard = Wave430GrandSovereignZenithSynthesizerGuard()
        t0 = time.monotonic()
        guard.update(0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, t0 + 10.0)
        assert not guard.is_blocked(t0 + 10.0)

        # Regressive timestamp
        guard.update(0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, t0 + 5.0)
        assert guard.is_blocked(t0 + 5.0)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_is_entry_blocked_forwarding(self):
        guard = Wave430GrandSovereignZenithSynthesizerGuard(cooldown_seconds=30.0)
        t0 = time.monotonic()
        assert not guard.is_entry_blocked(bid=2400.0, ask=2400.2, ts=t0)

        guard.update(0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, t0)
        assert guard.is_entry_blocked(bid=2400.0, ask=2400.2, ts=t0)
