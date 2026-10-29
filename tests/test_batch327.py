"""
Batch 327 -- Tests for Wave 410 Markov-Switching Volatility Regime Guard
========================================================================
Wave 410: Markov-Switching Volatility Regime Transition Guard

Target: 6+ tests, 100% pass rate
"""

import time
import pytest

from wave410_markov_switching_regime_transition_guard import (
    Wave410MarkovSwitchingRegimeTransitionGuard,
)


class TestWave410MarkovSwitchingGuard:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave410MarkovSwitchingRegimeTransitionGuard(sigma_low=-0.01)
        with pytest.raises(ValueError):
            Wave410MarkovSwitchingRegimeTransitionGuard(sigma_low=0.01, sigma_high=0.005)
        with pytest.raises(ValueError):
            Wave410MarkovSwitchingRegimeTransitionGuard(p00=1.5)

    def test_calm_regime_low_probability(self):
        guard = Wave410MarkovSwitchingRegimeTransitionGuard(
            sigma_low=0.001, sigma_high=0.010, turbulent_prob_threshold=0.70
        )
        t0 = time.monotonic()
        # Series of tiny calm returns
        p = 100.0
        for i in range(15):
            p += 0.005 if i % 2 == 0 else -0.005
            guard.update(bid=p, ask=p + 0.01, timestamp=t0 + i * 0.1)

        assert not guard.is_blocked()
        assert guard.turbulent_prob < 0.20

    def test_violent_volatility_triggers_turbulent_regime(self):
        guard = Wave410MarkovSwitchingRegimeTransitionGuard(
            sigma_low=0.0005, sigma_high=0.005, turbulent_prob_threshold=0.70, cooldown_seconds=60.0
        )
        t0 = time.monotonic()
        # Initialize with baseline
        guard.update(bid=100.0, ask=100.01, timestamp=t0)

        # Huge volatility swings (return ~ 2.0% >> sigma_low 0.05%)
        guard.update(bid=102.0, ask=102.01, timestamp=t0 + 0.1)
        guard.update(bid=98.0, ask=98.01, timestamp=t0 + 0.2)

        assert guard.is_blocked(t0 + 0.2)
        assert guard.last_reason in [
            "MARKOV_TURBULENT_REGIME_DETECTED",
            "REGIME_TRANSITION_INSTABILITY",
        ]
        assert guard.turbulent_prob >= 0.70

    def test_regime_transition_shock(self):
        guard = Wave410MarkovSwitchingRegimeTransitionGuard(
            sigma_low=0.0005, sigma_high=0.005, max_regime_shock=0.40, cooldown_seconds=45.0
        )
        t0 = time.monotonic()
        # Low calm baseline
        guard.update(bid=100.0, ask=100.01, timestamp=t0)
        guard.update(bid=100.01, ask=100.02, timestamp=t0 + 0.1)

        # Abrupt shock jump that shifts probability by > 0.40 in single tick
        guard.update(bid=102.5, ask=102.52, timestamp=t0 + 0.2)

        assert guard.is_blocked(t0 + 0.2)
        assert guard.last_reason in [
            "REGIME_TRANSITION_INSTABILITY",
            "MARKOV_TURBULENT_REGIME_DETECTED",
        ]

    def test_validation_and_reset(self):
        guard = Wave410MarkovSwitchingRegimeTransitionGuard()
        t0 = time.monotonic()
        guard.update(100.0, 99.0, t0)  # bid > ask
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        assert not guard.is_blocked()
        assert guard.turbulent_prob == 0.05
