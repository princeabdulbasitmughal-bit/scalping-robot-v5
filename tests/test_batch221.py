"""
tests/test_batch221.py
-----------------------
Unit test suite for Batch 221:
- Wave 208: Feed Staleness Age & Post-Staleness Gap Jump Guard
- Wave 209: Order Book Depth Imbalance Acceleration Guard

Verifies feed freeze gap jump kinematics, non-linear depth imbalance second derivatives,
fail-closed assertions, and monotonic cooldown timers.
"""

import math
import time
import pytest

import wave208_high_frequency_quote_staleness_jump_guard as wave208
import wave209_depth_imbalance_acceleration_guard as wave209


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave208.reset()
    wave209.reset()
    yield
    wave208.reset()
    wave209.reset()


# ---------------------------------------------------------------------------
# Wave 208: Feed Staleness Age & Post-Staleness Gap Jump Guard Tests
# ---------------------------------------------------------------------------

def test_wave208_normal_active_quotes_no_block():
    """Continuous quote updates without silent freezes do not block."""
    assert not wave208.is_entry_blocked()
    assert not wave208.is_blocked()

    # Steady quotes at 0.1s intervals
    wave208.record_quote(bid=2000.0, ask=2000.20, ts=100.0)
    wave208.record_quote(bid=2000.05, ask=2000.25, ts=100.1)

    assert not wave208.is_entry_blocked()
    metrics = wave208.get_staleness_metrics()
    assert metrics["dt_sec"] < wave208.MAX_STALENESS_SEC
    status = wave208.get_status()
    assert not status["is_blocked"]


def test_wave208_staleness_with_small_drift_no_block():
    """A feed stall (dt >= 2.5s) without a price jump (< 3.0 bps) does not trip block."""
    wave208.record_quote(bid=2000.0, ask=2000.20, ts=100.0)
    # Stalled for 3.0 seconds, but price changed by only 0.10 (0.5 bps)
    wave208.record_quote(bid=2000.10, ask=2000.30, ts=103.0)

    assert not wave208.is_entry_blocked()
    metrics = wave208.get_staleness_metrics()
    assert metrics["dt_sec"] >= wave208.MAX_STALENESS_SEC
    assert metrics["gap_bps"] < wave208.MIN_GAP_JUMP_BPS


def test_wave208_post_staleness_gap_jump_blocks():
    """Feed stall >= 2.5s followed by an abrupt jump (>= 3.0 bps) blocks entries for 45s."""
    wave208.record_quote(bid=2000.0, ask=2000.20, ts=100.0)
    # Feed freezes for 3.0 seconds, then resumes with mid jumping by 1.0 point (5.0 bps)
    wave208.update(bid=2001.0, ask=2001.20, ts=103.0)

    assert wave208.is_entry_blocked()
    assert wave208.is_blocked()
    metrics = wave208.get_staleness_metrics()
    assert metrics["dt_sec"] >= wave208.MAX_STALENESS_SEC
    assert metrics["gap_bps"] >= wave208.MIN_GAP_JUMP_BPS
    status = wave208.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave208_input_validation_and_fail_closed():
    """Inverted quotes, booleans, negatives, NaNs, and Infs are rejected safely."""
    wave208.record_quote(2000.20, 2000.00)  # inverted rejected
    wave208.record_quote(2000.00, 2000.00)  # zero spread rejected
    wave208.record_quote(True, 2000.20)  # bool rejected
    wave208.record_quote(2000.00, False)  # bool rejected
    wave208.record_quote(-2000.00, 2000.20)  # negative rejected
    wave208.record_quote(float("nan"), 2000.20)  # nan rejected
    wave208.record_quote(2000.00, float("inf"))  # inf rejected

    assert not wave208.is_entry_blocked()


def test_wave208_reset_and_status():
    """Reset clears quote history, metrics, and active blocks."""
    wave208.record_quote(2000.0, 2000.20, ts=100.0)
    wave208.record_quote(2002.0, 2002.20, ts=103.5)  # jump -> blocked
    assert wave208.is_entry_blocked()

    wave208.reset()
    assert not wave208.is_entry_blocked()
    metrics = wave208.get_staleness_metrics()
    assert metrics["dt_sec"] == 0.0
    assert metrics["gap_bps"] == 0.0
    status = wave208.get_status()
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 209: Depth Imbalance Acceleration Guard Tests
# ---------------------------------------------------------------------------

def test_wave209_normal_smooth_imbalance_shifts_no_block():
    """Gradual changes in depth imbalance produce low acceleration, no block."""
    assert not wave209.is_entry_blocked()
    assert not wave209.is_blocked()

    # Step 1: Balanced (10 vs 10 -> rho = 0.0) at t=100.0
    wave209.record_depth(bid_depth=10.0, ask_depth=10.0, ts=100.0)

    # Step 2: Mild shift (11 vs 10 -> rho = 0.048, v = +0.48) at t=100.1
    wave209.record_depth(bid_depth=11.0, ask_depth=10.0, ts=100.1)

    # Step 3: Continued steady shift (12 vs 10 -> rho = 0.091, v = +0.43, a ~ -0.5) at t=100.2
    wave209.record_depth(bid_depth=12.0, ask_depth=10.0, ts=100.2)

    assert not wave209.is_entry_blocked()
    metrics = wave209.get_imbalance_metrics()
    assert abs(metrics["acceleration"]) < wave209.MAX_IMBALANCE_ACCELERATION
    status = wave209.get_status()
    assert not status["is_blocked"]


def test_wave209_violent_positive_imbalance_acceleration_blocks():
    """Violent non-linear depth surge (|a_rho| >= 10.0 s^-2 with shift >= 0.40) blocks entries."""
    # Step 1: Balanced at t=100.0 (rho = 0.0)
    wave209.record_depth(bid_depth=10.0, ask_depth=10.0, ts=100.0)

    # Step 2: Steady (rho = 0.0, v = 0.0) at t=100.1
    wave209.record_depth(bid_depth=10.0, ask_depth=10.0, ts=100.1)

    # Step 3: Massive bid reinforcement / ask cancellation (18.0 vs 2.0 -> rho = +0.80, shift = +0.80) at t=100.2
    # v = 0.80 / 0.1 = 8.0 s^-1. Acceleration = (8.0 - 0.0) / 0.1 = 80.0 s^-2 >> 10.0
    wave209.update(bid_depth=18.0, ask_depth=2.0, ts=100.2)

    assert wave209.is_entry_blocked()
    assert wave209.is_blocked()
    metrics = wave209.get_imbalance_metrics()
    assert abs(metrics["acceleration"]) >= wave209.MAX_IMBALANCE_ACCELERATION
    status = wave209.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave209_violent_negative_imbalance_acceleration_blocks():
    """Violent non-linear bid collapse and ask loading blocks entries."""
    wave209.record_depth(bid_depth=10.0, ask_depth=10.0, ts=100.0)
    wave209.record_depth(bid_depth=10.0, ask_depth=10.0, ts=100.1)

    # Collapse: 2.0 bid vs 18.0 ask (rho = -0.80, shift = -0.80, a = -80.0)
    wave209.record_depth(bid_depth=2.0, ask_depth=18.0, ts=100.2)

    assert wave209.is_entry_blocked()
    metrics = wave209.get_imbalance_metrics()
    assert abs(metrics["acceleration"]) >= wave209.MAX_IMBALANCE_ACCELERATION


def test_wave209_input_validation_and_fail_closed():
    """Negative depths, booleans, NaNs, and Infs are rejected safely."""
    wave209.record_depth(-10.0, 10.0)  # negative depth rejected
    wave209.record_depth(10.0, -10.0)  # negative depth rejected
    wave209.record_depth(True, 10.0)  # bool rejected
    wave209.record_depth(10.0, False)  # bool rejected
    wave209.record_depth(float("nan"), 10.0)  # nan rejected
    wave209.record_depth(10.0, float("inf"))  # inf rejected

    assert not wave209.is_entry_blocked()


def test_wave209_reset_and_status():
    """Reset clears depth history, metrics, and active cooldown blocks."""
    wave209.record_depth(10.0, 10.0, ts=100.0)
    wave209.record_depth(10.0, 10.0, ts=100.1)
    wave209.record_depth(18.0, 2.0, ts=100.2)
    assert wave209.is_entry_blocked()

    wave209.reset()
    assert not wave209.is_entry_blocked()
    metrics = wave209.get_imbalance_metrics()
    assert metrics["imbalance"] == 0.0
    assert metrics["velocity"] == 0.0
    assert metrics["acceleration"] == 0.0
    status = wave209.get_status()
    assert not status["is_blocked"]
