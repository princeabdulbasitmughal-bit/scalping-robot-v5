"""
Test Suite Batch 293 -- Wave 347: Trade Arrival Self-Exciting Hawkes Intensity Guard
"""

import time
import pytest
from wave347_trade_arrival_self_exciting_hawkes_intensity_guard import Wave347TradeArrivalSelfExcitingHawkesIntensityGuard


class TestWave347HawkesIntensityGuard:
    """Comprehensive test suite for Wave 347: Hawkes Intensity Guard."""

    def _make_guard(self, **kwargs):
        defaults = dict(
            mu=1.0,
            alpha=3.0,
            beta=4.0,
            intensity_threshold=12.0,
            cooldown_seconds=45.0,
        )
        defaults.update(kwargs)
        return Wave347TradeArrivalSelfExcitingHawkesIntensityGuard(**defaults)

    def test_wave347_init_validation(self):
        """Invalid initialization parameters must raise ValueError."""
        with pytest.raises(ValueError):
            Wave347TradeArrivalSelfExcitingHawkesIntensityGuard(mu=0.0)
        with pytest.raises(ValueError):
            Wave347TradeArrivalSelfExcitingHawkesIntensityGuard(alpha=-1.0)
        with pytest.raises(ValueError):
            Wave347TradeArrivalSelfExcitingHawkesIntensityGuard(intensity_threshold=0.5)  # threshold <= mu

    def test_wave347_single_arrival_no_block(self):
        """A single arrival increases intensity by alpha, well below threshold."""
        guard = self._make_guard(mu=1.0, alpha=3.0, intensity_threshold=12.0)
        t0 = time.monotonic()
        guard.update(t0)
        assert guard.current_intensity == 4.0  # 1.0 + 3.0
        assert not guard.is_blocked(t0 + 0.1)

    def test_wave347_slow_spaced_arrivals_decay_no_block(self):
        """Arrivals spaced far apart allow Hawkes intensity to decay back near mu and never block."""
        guard = self._make_guard(mu=1.0, alpha=3.0, beta=5.0, intensity_threshold=12.0)
        t0 = time.monotonic()
        ts = t0
        for i in range(15):
            ts += 2.0  # 2.0s gap with beta=5 -> decay = exp(-10) ~ 0
            guard.update(ts)
            assert guard.current_intensity < 6.0
        assert not guard.is_blocked(ts + 0.1)

    def test_wave347_rapid_cluster_triggers_hawkes_block(self):
        """Rapid bursts of trade arrivals with negligible decay trigger HAWKES_SUPERCRITICAL_INTENSITY."""
        guard = self._make_guard(mu=1.0, alpha=3.0, beta=2.0, intensity_threshold=12.0)
        t0 = time.monotonic()
        # 5 rapid arrivals separated by 1ms (exp(-2*0.001) ~ 0.998, almost pure accumulation)
        ts = t0
        for i in range(5):
            ts += 0.001
            guard.update(ts)

        assert guard.is_blocked(ts + 0.01)
        assert guard.last_reason == "HAWKES_SUPERCRITICAL_INTENSITY"

    def test_wave347_negative_timestamp_delta_blocks(self):
        """Timestamps moving backward in time must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(t0)
        guard.update(t0 - 1.0)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave347_bool_timestamp_blocks(self):
        """Boolean timestamp input must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(True)
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave347_string_timestamp_blocks(self):
        """Non-numeric timestamp string must trigger INPUT_VALIDATION_ERROR."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update("invalid_ts")
        assert guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_wave347_reset_clears_state(self):
        """Reset must restore intensity to mu, clear timestamps and unblock."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(True)  # error block
        assert guard.is_blocked(t0 + 0.1)

        guard.reset()
        assert not guard.is_blocked(t0 + 0.1)
        assert guard.last_reason == ""
        assert guard.current_intensity == guard._mu

    def test_wave347_is_entry_blocked_delegation(self):
        """is_entry_blocked delegates to is_blocked with timestamp."""
        guard = self._make_guard()
        t0 = time.monotonic()
        guard.update(True)
        assert guard.is_entry_blocked(2400.0, 2400.20, t0 + 0.1)

    def test_wave347_current_intensity_property(self):
        """current_intensity property returns the float intensity value."""
        guard = self._make_guard(mu=2.5)
        assert guard.current_intensity == 2.5
