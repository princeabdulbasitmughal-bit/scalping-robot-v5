"""
Batch 336 -- Tests for Wave 425 Apex Imperial Invariant Synthesizer Guard
=========================================================================
Wave 425: Apex Imperial Invariant Synthesizer Guard

Target: 6+ tests, 100% pass rate
"""

import time
import pytest

from wave425_apex_imperial_invariant_synthesizer_guard import (
    Wave425ApexImperialInvariantSynthesizerGuard,
)


class TestWave425ImperialSynthesizerGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave425ApexImperialInvariantSynthesizerGuard(critical_imperial_threshold=1.5)
        with pytest.raises(ValueError):
            Wave425ApexImperialInvariantSynthesizerGuard(convergence_count_threshold=10)

    def test_calm_microstructure_no_block(self):
        guard = Wave425ApexImperialInvariantSynthesizerGuard(
            critical_imperial_threshold=0.60
        )
        t0 = time.monotonic()
        # All signals calm (around 0.10)
        guard.update(
            cancel_ratio_risk=0.10,
            burst_dispersion_risk=0.08,
            spread_asymmetry_risk=0.12,
            toxicity_duration_risk=0.05,
            run_length_risk=0.10,
            replenish_asym_risk=0.06,
            quarticity_risk=0.08,
            multifractal_risk=0.10,
            timestamp=t0,
        )

        assert not guard.is_blocked()
        assert guard.imperial_score < 0.15

    def test_composite_fragility_spike_triggers_block(self):
        guard = Wave425ApexImperialInvariantSynthesizerGuard(
            critical_imperial_threshold=0.65, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Elevated across all 8 dimensions (average 0.68 > 0.65)
        guard.update(
            cancel_ratio_risk=0.68,
            burst_dispersion_risk=0.68,
            spread_asymmetry_risk=0.68,
            toxicity_duration_risk=0.68,
            run_length_risk=0.68,
            replenish_asym_risk=0.68,
            quarticity_risk=0.68,
            multifractal_risk=0.68,
            timestamp=t0,
        )

        assert guard.is_blocked(t0)
        assert guard.last_reason == "IMPERIAL_INVARIANT_FRAGILITY_SPIKE"
        assert guard.imperial_score >= 0.65

    def test_multi_vector_convergence_triggers_lockout(self):
        guard = Wave425ApexImperialInvariantSynthesizerGuard(
            critical_imperial_threshold=0.85, convergence_count_threshold=4, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # 4 signals severely tripped (>= 0.70) while other 4 are calm (0.10)
        guard.update(
            cancel_ratio_risk=0.85,
            burst_dispersion_risk=0.90,
            spread_asymmetry_risk=0.80,
            toxicity_duration_risk=0.75,
            run_length_risk=0.10,
            replenish_asym_risk=0.10,
            quarticity_risk=0.10,
            multifractal_risk=0.10,
            timestamp=t0,
        )

        assert guard.is_blocked(t0)
        assert guard.last_reason == "SOVEREIGN_GLOBAL_LOCKOUT"

    def test_validation_and_reset(self):
        guard = Wave425ApexImperialInvariantSynthesizerGuard()
        t0 = time.monotonic()
        # Value > 1.0 invalid
        guard.update(1.5, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, t0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.imperial_score == 0.0
