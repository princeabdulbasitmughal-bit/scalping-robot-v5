"""
tests/test_batch226.py
-----------------------
Unit test suite for Batch 226:
- Wave 218: Quote Run Length & Microstructure Directional Inertia Guard
- Wave 219: Depth Cushion & Asymmetric LOB Cushion Depletion Guard

Verifies unidirectional quote streaks, high-velocity sweeps, asymmetric limit order book
cushion exhaustion, fail-closed handling, and monotonic cooldown timers.
"""

import math
import time
import pytest

import wave218_quote_run_length_directional_inertia_guard as wave218
import wave219_depth_cushion_asymmetric_exhaustion_guard as wave219


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave218.reset()
    wave219.reset()
    yield
    wave218.reset()
    wave219.reset()


# ---------------------------------------------------------------------------
# Wave 218: Quote Run Length & Directional Inertia Guard Tests
# ---------------------------------------------------------------------------

def test_wave218_normal_alternating_quotes_no_block():
    """Stochastically oscillating midquotes keep run length short, no block."""
    assert not wave218.is_entry_blocked()
    assert not wave218.is_blocked()

    p = 2000.0
    for i in range(12):
        p += (0.10 if i % 2 == 0 else -0.10)
        wave218.record_midquote(p)

    assert not wave218.is_entry_blocked()
    metrics = wave218.get_run_metrics()
    assert metrics["run_length"] <= 2
    status = wave218.get_status()
    assert not status["is_blocked"]


def test_wave218_persistent_unidirectional_run_blocks():
    """Persistent unidirectional quote ticks (L_run >= 8 with D_run >= 3.5 bps) block entries for 45s."""
    p = 2000.0
    wave218.record_midquote(p)
    # 9 consecutive ticks moving upward by 0.50 each
    # Displacement = 4.5 on 2000.0 = 22.5 bps >= 3.5 bps
    for _ in range(9):
        p += 0.50
        wave218.update(p)

    assert wave218.is_entry_blocked()
    assert wave218.is_blocked()
    metrics = wave218.get_run_metrics()
    assert metrics["run_length"] >= wave218.MAX_RUN_LENGTH
    assert metrics["displacement_bps"] >= wave218.MIN_RUN_DISPLACEMENT_BPS
    status = wave218.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave218_high_velocity_sweep_blocks():
    """Rapid quote sweep (L_run >= 5 with velocity >= 10.0 bps/sec) triggers cooldown block."""
    t = 1000.0
    p = 2000.0
    wave218.record_midquote(p, ts=t)

    # 5 fast ticks down by 0.40 each within 0.10 seconds total
    # Displacement = 2.0 on 2000.0 = 10.0 bps in 0.10s -> 100.0 bps/sec >= 10.0 bps/sec
    for _ in range(5):
        t += 0.02
        p -= 0.40
        wave218.record_midquote(p, ts=t)

    assert wave218.is_entry_blocked()
    metrics = wave218.get_run_metrics()
    assert metrics["run_length"] >= wave218.MIN_VELOCITY_RUN_LENGTH
    assert metrics["velocity_bps_sec"] >= wave218.MAX_RUN_VELOCITY_BPS


def test_wave218_input_validation_and_fail_closed():
    """Booleans, negative prices, NaNs, and Infs are safely rejected without throwing."""
    wave218.record_midquote(True)
    wave218.record_midquote(False)
    wave218.record_midquote(-2000.0)
    wave218.record_midquote(0.0)
    wave218.record_midquote(float("nan"))
    wave218.record_midquote(float("inf"))

    assert not wave218.is_entry_blocked()
    assert wave218.get_status()["run_length"] == 0


def test_wave218_reset_and_status():
    """Reset clears quote trackers, displacement metrics, and active cooldown blocks."""
    p = 2000.0
    wave218.record_midquote(p)
    for _ in range(9):
        p += 0.50
        wave218.record_midquote(p)
    assert wave218.is_entry_blocked()

    wave218.reset()
    assert not wave218.is_entry_blocked()
    metrics = wave218.get_run_metrics()
    assert metrics["run_length"] == 0
    assert metrics["displacement_bps"] == 0.0
    status = wave218.get_status()
    assert status["run_length"] == 0
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 219: Depth Cushion & Asymmetric LOB Cushion Depletion Guard Tests
# ---------------------------------------------------------------------------

def test_wave219_healthy_symmetric_depth_no_block():
    """Symmetric depth near baseline keeps cushions near 1.0, no block."""
    assert not wave219.is_entry_blocked()
    assert not wave219.is_blocked()

    for _ in range(20):
        wave219.record_book(bid_price=2000.0, bid_depth=15.0, ask_price=2000.20, ask_depth=15.0)

    assert not wave219.is_entry_blocked()
    metrics = wave219.get_cushion_metrics()
    assert metrics["bid_cushion"] > 0.90
    assert metrics["ask_cushion"] > 0.90
    status = wave219.get_status()
    assert not status["is_blocked"]


def test_wave219_asymmetric_bid_exhaustion_blocks():
    """Bid depth collapse (C_bid <= 0.15 while C_ask >= 0.80) blocks entries for 45s."""
    # Establish baseline of 20.0 lots on both sides across 20 updates
    for _ in range(20):
        wave219.record_book(bid_price=2000.0, bid_depth=20.0, ask_price=2000.20, ask_depth=20.0)

    # Sudden bid cushion evaporation: bid drops to 1.0 lot while ask stays 20.0 lots
    # Mean bid ~ 19.0 lots >= 5.0. C_bid = 1.0 / 19.0 = 0.052 <= 0.15. C_ask = 1.0 >= 0.80
    wave219.update(bid_price=2000.0, bid_depth=1.0, ask_price=2000.20, ask_depth=20.0)

    assert wave219.is_entry_blocked()
    assert wave219.is_blocked()
    metrics = wave219.get_cushion_metrics()
    assert metrics["bid_cushion"] <= wave219.MIN_CUSHION_RATIO
    assert metrics["ask_cushion"] >= wave219.OPPOSITE_HEALTHY_RATIO
    status = wave219.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave219_asymmetric_ask_exhaustion_blocks():
    """Ask depth collapse (C_ask <= 0.15 while C_bid >= 0.80) blocks entries."""
    for _ in range(20):
        wave219.record_book(bid_price=2000.0, bid_depth=25.0, ask_price=2000.20, ask_depth=25.0)

    # Ask drops to 1.5 lots
    wave219.record_book(bid_price=2000.0, bid_depth=25.0, ask_price=2000.20, ask_depth=1.5)

    assert wave219.is_entry_blocked()
    metrics = wave219.get_cushion_metrics()
    assert metrics["ask_cushion"] <= wave219.MIN_CUSHION_RATIO
    assert metrics["bid_cushion"] >= wave219.OPPOSITE_HEALTHY_RATIO


def test_wave219_insufficient_samples_no_block():
    """Fewer than MIN_SAMPLES=15 snapshots does not trigger block regardless of cushion."""
    for _ in range(5):
        wave219.record_book(bid_price=2000.0, bid_depth=0.5, ask_price=2000.20, ask_depth=20.0)

    assert not wave219.is_entry_blocked()
    assert wave219.get_status()["sample_count"] == 5


def test_wave219_input_validation_and_reset():
    """Corrupted inputs are safely rejected, and reset restores clean state."""
    # Invalid prices
    wave219.record_book(True, 10.0, 2000.20, 10.0)
    wave219.record_book(2000.0, 10.0, False, 10.0)
    wave219.record_book(-2000.0, 10.0, 2000.20, 10.0)
    wave219.record_book(2000.50, 10.0, 2000.10, 10.0)  # Inverted

    # Invalid depths
    wave219.record_book(2000.0, -5.0, 2000.20, 10.0)
    wave219.record_book(2000.0, float("nan"), 2000.20, 10.0)
    wave219.record_book(2000.0, 10.0, 2000.20, float("inf"))

    assert not wave219.is_entry_blocked()

    # Trigger block then reset
    for _ in range(20):
        wave219.record_book(2000.0, 20.0, 2000.20, 20.0)
    wave219.record_book(2000.0, 1.0, 2000.20, 20.0)
    assert wave219.is_entry_blocked()

    wave219.reset()
    assert not wave219.is_entry_blocked()
    metrics = wave219.get_cushion_metrics()
    assert metrics["bid_cushion"] == 1.0
    status = wave219.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]
