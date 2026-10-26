"""
Batch 321 -- Tests for Wave 400 Grand Jubilee Sovereign Invariant Synthesizer Guard
==================================================================================
Wave 400: Grand Jubilee Sovereign Invariant Synthesizer Guard

Target: 14+ tests, 0 failures
"""

import time
import pytest

from wave400_grand_jubilee_sovereign_invariant_synthesizer_guard import (
    Wave400GrandJubileeSovereignInvariantSynthesizerGuard,
)


class TestWave400GrandJubileeSynthesizer:
    def test_init_invalid_weights(self):
        with pytest.raises(ValueError):
            # Sum != 1.0
            Wave400GrandJubileeSovereignInvariantSynthesizerGuard(weights=[0.2, 0.2, 0.2, 0.2, 0.1])
        with pytest.raises(ValueError):
            # Wrong length
            Wave400GrandJubileeSovereignInvariantSynthesizerGuard(weights=[0.5, 0.5])

    def test_init_invalid_thresholds(self):
        with pytest.raises(ValueError):
            Wave400GrandJubileeSovereignInvariantSynthesizerGuard(critical_composite_threshold=1.5)
        with pytest.raises(ValueError):
            Wave400GrandJubileeSovereignInvariantSynthesizerGuard(max_veto_signals=6)

    def test_low_risk_regime_no_block(self):
        guard = Wave400GrandJubileeSovereignInvariantSynthesizerGuard(
            critical_composite_threshold=0.70
        )
        t0 = time.monotonic()
        # All signals 0.10 -> composite = 0.10 < 0.70
        guard.update(
            spread_risk=0.10,
            vpin=0.10,
            price_impact=0.10,
            acceleration=0.10,
            entropy_loss=0.10,
            timestamp=t0,
        )
        assert not guard.is_blocked()
        assert abs(guard.composite_score - 0.10) < 1e-6

    def test_critical_composite_breach_triggers_block(self):
        guard = Wave400GrandJubileeSovereignInvariantSynthesizerGuard(
            critical_composite_threshold=0.60
        )
        t0 = time.monotonic()
        # Signals average to 0.75 >= 0.60
        guard.update(
            spread_risk=0.80,
            vpin=0.70,
            price_impact=0.80,
            acceleration=0.70,
            entropy_loss=0.75,
            timestamp=t0,
        )
        assert guard.is_blocked()
        assert guard.last_reason == "GRAND_JUBILEE_SOVEREIGN_RISK_BREACH"
        assert guard.composite_score >= 0.60

    def test_multi_invariant_consensus_veto_triggers_block(self):
        # 3 signals breach 0.85 even if composite threshold is high (0.90)
        guard = Wave400GrandJubileeSovereignInvariantSynthesizerGuard(
            critical_composite_threshold=0.90,
            individual_veto_threshold=0.85,
            max_veto_signals=3,
        )
        t0 = time.monotonic()
        guard.update(
            spread_risk=0.90,     # veto 1
            vpin=0.90,            # veto 2
            price_impact=0.90,    # veto 3
            acceleration=0.0,
            entropy_loss=0.0,
            timestamp=t0,
        )
        # Composite = 0.20*(0.9+0.9+0.9) = 0.54 < 0.90, but veto triggered!
        assert guard.is_blocked()
        assert guard.last_reason == "MULTI_INVARIANT_CONSENSUS_VETO"

    def test_signals_out_of_bounds_validation(self):
        guard = Wave400GrandJubileeSovereignInvariantSynthesizerGuard()
        # spread_risk > 1.0
        guard.update(1.2, 0.5, 0.5, 0.5, 0.5, 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        # negative signal
        guard.update(0.5, -0.1, 0.5, 0.5, 0.5, 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_non_numeric_validation(self):
        guard = Wave400GrandJubileeSovereignInvariantSynthesizerGuard()
        guard.update(0.5, 0.5, "bad", 0.5, 0.5, 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(True, 0.5, 0.5, 0.5, 0.5, 1.0)  # boolean
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_entry_blocked(self):
        guard = Wave400GrandJubileeSovereignInvariantSynthesizerGuard()
        guard.update(0.9, 0.9, 0.9, 0.9, 0.9, 1.0)
        assert guard.is_blocked()
        assert guard.is_entry_blocked(2000.0, 2000.5, 1.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""
        assert guard.composite_score == 0.0
