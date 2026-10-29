"""
Batch 348 -- Tests for Wave 445 Apex Sovereign Canopy Synthesizer Guard
========================================================================
Wave 445: Apex Sovereign Canopy Synthesizer Guard

Target: 6+ tests, 100% pass rate
"""

import time
import pytest

from wave445_apex_sovereign_canopy_synthesizer_guard import (
    Wave445ApexSovereignCanopySynthesizerGuard,
)


class TestWave445SovereignCanopySynthesizerGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave445ApexSovereignCanopySynthesizerGuard(critical_sovereign_threshold=1.5)
        with pytest.raises(ValueError):
            Wave445ApexSovereignCanopySynthesizerGuard(convergence_count_threshold=9)
        with pytest.raises(ValueError):
            Wave445ApexSovereignCanopySynthesizerGuard(cooldown_seconds=-1.0)

    def test_calm_sovereign_canopy_no_block(self):
        guard = Wave445ApexSovereignCanopySynthesizerGuard(
            critical_sovereign_threshold=0.60
        )
        t0 = time.monotonic()
        guard.update(
            realized_kernel_noise_risk=0.10,
            depth_half_life_risk=0.08,
            lead_lag_propagation_risk=0.12,
            impact_decay_asymmetry_risk=0.05,
            apex_canopy_risk=0.10,
            orderbook_skew_risk=0.06,
            volatility_curvature_risk=0.08,
            cross_venue_divergence_risk=0.10,
            timestamp=t0,
        )

        assert not guard.is_blocked()
        assert guard.sovereign_score < 0.15

    def test_composite_fragility_spike_triggers_block(self):
        guard = Wave445ApexSovereignCanopySynthesizerGuard(
            critical_sovereign_threshold=0.65, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Elevated across all 8 dimensions (average 0.68 > 0.65)
        guard.update(
            realized_kernel_noise_risk=0.68,
            depth_half_life_risk=0.68,
            lead_lag_propagation_risk=0.68,
            impact_decay_asymmetry_risk=0.68,
            apex_canopy_risk=0.68,
            orderbook_skew_risk=0.68,
            volatility_curvature_risk=0.68,
            cross_venue_divergence_risk=0.68,
            timestamp=t0,
        )

        assert guard.is_blocked(t0)
        assert guard.last_reason == "APEX_SOVEREIGN_CANOPY_FRAGILITY_SPIKE"
        assert guard.sovereign_score >= 0.65

    def test_multi_vector_convergence_triggers_lockout(self):
        guard = Wave445ApexSovereignCanopySynthesizerGuard(
            critical_sovereign_threshold=0.85, convergence_count_threshold=4, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # 4 signals tripped (>= 0.70) while 4 are calm (0.10)
        guard.update(
            realized_kernel_noise_risk=0.85,
            depth_half_life_risk=0.90,
            lead_lag_propagation_risk=0.80,
            impact_decay_asymmetry_risk=0.75,
            apex_canopy_risk=0.10,
            orderbook_skew_risk=0.10,
            volatility_curvature_risk=0.10,
            cross_venue_divergence_risk=0.10,
            timestamp=t0,
        )

        assert guard.is_blocked(t0)
        assert guard.last_reason == "SOVEREIGN_CANOPY_MULTI_VECTOR_LOCKOUT"

    def test_validation_and_reset(self):
        guard = Wave445ApexSovereignCanopySynthesizerGuard()
        t0 = time.monotonic()
        # Value > 1.0 invalid
        guard.update(1.5, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, t0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.sovereign_score == 0.0

    def test_monotonic_timestamp_enforcement(self):
        guard = Wave445ApexSovereignCanopySynthesizerGuard()
        t0 = time.monotonic()
        guard.update(0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, t0 + 10.0)
        assert not guard.is_blocked(t0 + 10.0)

        # Regressive timestamp
        guard.update(0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, t0 + 5.0)
        assert guard.is_blocked(t0 + 5.0)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_is_entry_blocked_forwarding(self):
        guard = Wave445ApexSovereignCanopySynthesizerGuard(cooldown_seconds=30.0)
        t0 = time.monotonic()
        assert not guard.is_entry_blocked(bid=2400.0, ask=2400.2, ts=t0)

        guard.update(0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, t0)
        assert guard.is_entry_blocked(bid=2400.0, ask=2400.2, ts=t0)
