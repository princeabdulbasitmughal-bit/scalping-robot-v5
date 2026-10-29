"""
Batch 322 -- Tests for Wave 401 and Wave 402
=============================================
Wave 401: Non-Stationary Drift Velocity Compensator Guard
Wave 402: Cross-Venue Latency Arbitrage Skew Guard

Target: 14+ tests, 0 failures
"""

import time
import pytest

from wave401_nonstationary_drift_velocity_compensator_guard import (
    Wave401NonstationaryDriftVelocityCompensatorGuard,
)
from wave402_cross_venue_latency_arbitrage_skew_guard import (
    Wave402CrossVenueLatencyArbitrageSkewGuard,
)


class TestWave401DriftVelocity:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave401NonstationaryDriftVelocityCompensatorGuard(window_size=2)
        with pytest.raises(ValueError):
            Wave401NonstationaryDriftVelocityCompensatorGuard(drift_velocity_threshold=-1.0)

    def test_low_drift_no_block(self):
        guard = Wave401NonstationaryDriftVelocityCompensatorGuard(
            window_size=5, drift_velocity_threshold=1.0
        )
        t0 = time.monotonic()
        # Flat/minor fluctuation (v ~ 0.0)
        for i in range(10):
            p = 100.0 + (0.01 if i % 2 == 0 else -0.01)
            guard.update(bid=p, ask=p + 0.1, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_supercritical_drift_triggers_block(self):
        guard = Wave401NonstationaryDriftVelocityCompensatorGuard(
            window_size=5, drift_velocity_threshold=2.0
        )
        t0 = time.monotonic()
        # Price increases by 3.0 every second -> velocity = 3.0 >= 2.0
        for i in range(7):
            guard.update(bid=100.0 + i * 3.0, ask=100.2 + i * 3.0, timestamp=t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "SUPERCRITICAL_DRIFT_VELOCITY"

    def test_invalid_input_validation(self):
        guard = Wave401NonstationaryDriftVelocityCompensatorGuard()
        guard.update(bid=-10.0, ask=10.0, timestamp=1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(bid=100.0, ask=100.1, timestamp=10.0)
        guard.update(bid=100.0, ask=100.1, timestamp=9.0)  # non-monotonic
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_entry_blocked(self):
        guard = Wave401NonstationaryDriftVelocityCompensatorGuard()
        guard.update(bid=100.0, ask=100.1, timestamp=1.0)
        guard.update(bid=100.0, ask=100.1, timestamp=1.0)  # dt = 0
        assert guard.is_blocked()
        assert guard.is_entry_blocked(100.0, 100.1, 2.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""


class TestWave402LatencyArbitrageSkew:
    def test_init_invalid_params(self):
        with pytest.raises(ValueError):
            Wave402CrossVenueLatencyArbitrageSkewGuard(window_size=2)
        with pytest.raises(ValueError):
            Wave402CrossVenueLatencyArbitrageSkewGuard(skew_threshold=0.0)

    def test_tight_basis_no_block(self):
        guard = Wave402CrossVenueLatencyArbitrageSkewGuard(
            window_size=5, skew_threshold=1.0
        )
        t0 = time.monotonic()
        for i in range(10):
            guard.update(primary_price=2000.1, reference_price=2000.2, timestamp=t0 + i)
        assert not guard.is_blocked()

    def test_persistent_skew_triggers_block(self):
        guard = Wave402CrossVenueLatencyArbitrageSkewGuard(
            window_size=5, skew_threshold=1.0
        )
        t0 = time.monotonic()
        # Basis discrepancy = 1.5 >= 1.0
        for i in range(5):
            guard.update(primary_price=2000.0, reference_price=2001.5, timestamp=t0 + i)
        assert guard.is_blocked()
        assert guard.last_reason == "CROSS_VENUE_LATENCY_SKEW"

    def test_instantaneous_spike_triggers_block(self):
        guard = Wave402CrossVenueLatencyArbitrageSkewGuard(
            window_size=10, skew_threshold=1.0
        )
        t0 = time.monotonic()
        # Normal
        guard.update(primary_price=2000.0, reference_price=2000.1, timestamp=t0)
        assert not guard.is_blocked()
        # Immediate spike Delta = 2.5 >= 2.0 * 1.0
        guard.update(primary_price=2000.0, reference_price=2002.5, timestamp=t0 + 1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "CROSS_VENUE_LATENCY_SKEW"

    def test_invalid_input_validation(self):
        guard = Wave402CrossVenueLatencyArbitrageSkewGuard()
        guard.update(primary_price=-100.0, reference_price=100.0, timestamp=1.0)
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

        guard.reset()
        guard.update(primary_price=100.0, reference_price=True, timestamp=1.0)  # bool check
        assert guard.is_blocked()
        assert guard.last_reason == "INPUT_VALIDATION_ERROR"

    def test_reset_and_entry_blocked(self):
        guard = Wave402CrossVenueLatencyArbitrageSkewGuard()
        guard.update(primary_price=100.0, reference_price="invalid", timestamp=1.0)
        assert guard.is_blocked()
        assert guard.is_entry_blocked(1.10, 1.11, 2.0)
        guard.reset()
        assert not guard.is_blocked()
        assert guard.last_reason == ""
