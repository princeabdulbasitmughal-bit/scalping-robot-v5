"""
Batch 330 -- Tests for Wave 415 Omnipresent Sovereign Synthesis Guard
=====================================================================
Wave 415: Omnipresent Sovereign Synthesis & Invariant Governor Guard

Target: 6+ tests, 100% pass rate
"""

import time
import pytest

from wave415_omnipresent_sovereign_synthesis_guard import (
    Wave415OmnipresentSovereignSynthesisGuard,
)


class TestWave415SovereignSynthesisGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave415OmnipresentSovereignSynthesisGuard(critical_composite_threshold=1.5)
        with pytest.raises(ValueError):
            Wave415OmnipresentSovereignSynthesisGuard(convergence_count_threshold=10)

    def test_healthy_low_risk_no_block(self):
        guard = Wave415OmnipresentSovereignSynthesisGuard(
            critical_composite_threshold=0.60
        )
        t0 = time.monotonic()
        # All signals calm and low (around 0.10)
        guard.update(
            vpin_risk=0.10,
            markov_turbulent_prob=0.08,
            jump_ratio=0.05,
            microprice_skew=0.12,
            depth_slope_decay=0.05,
            autocorr_shock=0.06,
            noise_ratio=0.10,
            timestamp=t0,
        )

        assert not guard.is_blocked()
        assert guard.composite_score < 0.15

    def test_composite_fragility_spike_triggers_block(self):
        guard = Wave415OmnipresentSovereignSynthesisGuard(
            critical_composite_threshold=0.60, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Broad elevation across metrics (weighted average ~ 0.64 > 0.60)
        guard.update(
            vpin_risk=0.68,
            markov_turbulent_prob=0.68,
            jump_ratio=0.68,
            microprice_skew=0.60,
            depth_slope_decay=0.60,
            autocorr_shock=0.60,
            noise_ratio=0.60,
            timestamp=t0,
        )

        assert guard.is_blocked(t0)
        assert guard.last_reason == "SOVEREIGN_COMPOSITE_FRAGILITY_SPIKE"
        assert guard.composite_score >= 0.60

    def test_multi_canopy_convergence_triggers_lock(self):
        guard = Wave415OmnipresentSovereignSynthesisGuard(
            critical_composite_threshold=0.85, convergence_count_threshold=3, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # 3 metrics severely tripped (>= 0.70) while others low
        guard.update(
            vpin_risk=0.85,
            markov_turbulent_prob=0.90,
            jump_ratio=0.80,
            microprice_skew=0.10,
            depth_slope_decay=0.05,
            autocorr_shock=0.05,
            noise_ratio=0.05,
            timestamp=t0,
        )

        assert guard.is_blocked(t0)
        assert guard.last_reason == "MULTI_CANOPY_CONVERGENCE_LOCK"

    def test_validation_and_reset(self):
        guard = Wave415OmnipresentSovereignSynthesisGuard()
        t0 = time.monotonic()
        # Value > 1.0 invalid
        guard.update(1.5, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, t0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.composite_score == 0.0
