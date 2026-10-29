"""
Batch 345 -- Tests for Wave 440 Grand Jubilee Apex Canopy Synthesizer Guard
===========================================================================
Wave 440: Grand Jubilee Apex Canopy Synthesizer Guard

Target: 6+ tests, 100% pass rate
"""

import time
import pytest

from wave440_grand_jubilee_apex_canopy_synthesizer_guard import (
    Wave440GrandJubileeApexCanopySynthesizerGuard,
)


class TestWave440ApexCanopySynthesizerGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave440GrandJubileeApexCanopySynthesizerGuard(critical_apex_threshold=1.5)
        with pytest.raises(ValueError):
            Wave440GrandJubileeApexCanopySynthesizerGuard(convergence_count_threshold=9)
        with pytest.raises(ValueError):
            Wave440GrandJubileeApexCanopySynthesizerGuard(cooldown_seconds=-1.0)

    def test_calm_apex_canopy_no_block(self):
        guard = Wave440GrandJubileeApexCanopySynthesizerGuard(
            critical_apex_threshold=0.60
        )
        t0 = time.monotonic()
        guard.update(
            orderbook_skew_risk=0.10,
            volatility_curvature_risk=0.08,
            depth_recovery_failure_risk=0.12,
            cross_venue_divergence_risk=0.05,
            zenith_canopy_risk=0.10,
            hawkes_jump_risk=0.06,
            trade_flow_asymmetry_risk=0.08,
            vrp_explosive_risk=0.10,
            timestamp=t0,
        )

        assert not guard.is_blocked()
        assert guard.apex_score < 0.15

    def test_composite_fragility_spike_triggers_block(self):
        guard = Wave440GrandJubileeApexCanopySynthesizerGuard(
            critical_apex_threshold=0.65, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Elevated across all 8 dimensions (average 0.68 > 0.65)
        guard.update(
            orderbook_skew_risk=0.68,
            volatility_curvature_risk=0.68,
            depth_recovery_failure_risk=0.68,
            cross_venue_divergence_risk=0.68,
            zenith_canopy_risk=0.68,
            hawkes_jump_risk=0.68,
            trade_flow_asymmetry_risk=0.68,
            vrp_explosive_risk=0.68,
            timestamp=t0,
        )

        assert guard.is_blocked(t0)
        assert guard.last_reason == "GRAND_JUBILEE_APEX_CANOPY_FRAGILITY_SPIKE"
        assert guard.apex_score >= 0.65

    def test_multi_vector_convergence_triggers_lockout(self):
        guard = Wave440GrandJubileeApexCanopySynthesizerGuard(
            critical_apex_threshold=0.85, convergence_count_threshold=4, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # 4 signals tripped (>= 0.70) while 4 are calm (0.10)
        guard.update(
            orderbook_skew_risk=0.85,
            volatility_curvature_risk=0.90,
            depth_recovery_failure_risk=0.80,
            cross_venue_divergence_risk=0.75,
            zenith_canopy_risk=0.10,
            hawkes_jump_risk=0.10,
            trade_flow_asymmetry_risk=0.10,
            vrp_explosive_risk=0.10,
            timestamp=t0,
        )

        assert guard.is_blocked(t0)
        assert guard.last_reason == "APEX_CANOPY_MULTI_VECTOR_LOCKOUT"

    def test_validation_and_reset(self):
        guard = Wave440GrandJubileeApexCanopySynthesizerGuard()
        t0 = time.monotonic()
        # Value > 1.0 invalid
        guard.update(1.5, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, t0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.apex_score == 0.0

    def test_monotonic_timestamp_enforcement(self):
        guard = Wave440GrandJubileeApexCanopySynthesizerGuard()
        t0 = time.monotonic()
        guard.update(0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, t0 + 10.0)
        assert not guard.is_blocked(t0 + 10.0)

        # Regressive timestamp
        guard.update(0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, t0 + 5.0)
        assert guard.is_blocked(t0 + 5.0)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_is_entry_blocked_forwarding(self):
        guard = Wave440GrandJubileeApexCanopySynthesizerGuard(cooldown_seconds=30.0)
        t0 = time.monotonic()
        assert not guard.is_entry_blocked(bid=2400.0, ask=2400.2, ts=t0)

        guard.update(0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, t0)
        assert guard.is_entry_blocked(bid=2400.0, ask=2400.2, ts=t0)
