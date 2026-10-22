"""
tests/test_batch230.py
-----------------------
Unit test suite for Batch 230:
- Wave 226: Tick Flow Asymmetry Acceleration & Directional Volatility Skew Guard
- Wave 227: Limit Order Placement Cancellation Latency Gap Asynchrony Guard

Verifies tick flow acceleration bursts, directional flow skewness, cancellation vs fill
latency asynchrony divergence, single cancellation hangs, fail-closed handling, and cooldowns.
"""

import math
import time
import pytest

import wave226_tick_flow_acceleration_skew_guard as wave226
import wave227_cancellation_latency_asynchrony_guard as wave227


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave226.reset()
    wave227.reset()
    yield
    wave226.reset()
    wave227.reset()


# ---------------------------------------------------------------------------
# Wave 226: Tick Flow Asymmetry Acceleration Guard Tests
# ---------------------------------------------------------------------------

def test_wave226_balanced_alternating_tick_flow_no_block():
    """Symmetric alternating trade flow keeps acceleration and skew near zero, no block."""
    assert not wave226.is_entry_blocked()
    assert not wave226.is_blocked()

    # 20 alternating ticks
    for i in range(20):
        wave226.record_tick("buy" if i % 2 == 0 else "sell")

    assert not wave226.is_entry_blocked()
    metrics = wave226.get_flow_metrics()
    assert metrics["flow_acceleration"] <= 2.0
    status = wave226.get_status()
    assert not status["is_blocked"]


def test_wave226_flow_acceleration_jerk_blocks():
    """Violent shift in net 10-tick flow (|a_flow| >= 12.0 units) blocks entries for 45s."""
    # First 10 ticks: 8 sells (-1) and 2 buys (+1) -> sum = -6
    first_block = ["sell"] * 8 + ["buy"] * 2
    for s in first_block:
        wave226.record_tick(s)

    assert not wave226.is_entry_blocked()

    # Second 10 ticks: 9 buys (+1) and 1 sell (-1) -> sum = +8
    # Acceleration = |8 - (-6)| = 14.0 >= 12.0!
    second_block = ["buy"] * 9 + ["sell"] * 1
    for s in second_block:
        wave226.update(s)

    assert wave226.is_entry_blocked()
    assert wave226.is_blocked()
    metrics = wave226.get_flow_metrics()
    assert metrics["flow_acceleration"] >= wave226.MAX_FLOW_ACCELERATION
    status = wave226.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave226_directional_volatility_skew_blocks():
    """Extreme directional skewness (|S_skew| >= 2.20) on 20 ticks blocks entries."""
    # 19 buys and 1 sell across 20 ticks
    ticks = ["buy"] * 19 + ["sell"] * 1
    for s in ticks:
        wave226.record_tick(s)

    assert wave226.is_entry_blocked()
    metrics = wave226.get_flow_metrics()
    assert abs(metrics["flow_skewness"]) >= wave226.MAX_FLOW_SKEW


def test_wave226_input_validation_and_fail_closed():
    """Invalid sides, booleans, NaNs, and Infs are safely ignored without throwing."""
    wave226.record_tick("invalid_side")
    wave226.record_tick(True)
    wave226.record_tick(False)
    wave226.record_tick(float("nan"))
    wave226.record_tick(float("inf"))

    assert not wave226.is_entry_blocked()
    assert wave226.get_status()["sample_count"] == 0


def test_wave226_reset_and_status():
    """Reset clears tick deque, block trackers, metrics, and active cooldown blocks."""
    ticks = ["buy"] * 19 + ["sell"] * 1
    for s in ticks:
        wave226.record_tick(s)
    assert wave226.is_entry_blocked()

    wave226.reset()
    assert not wave226.is_entry_blocked()
    metrics = wave226.get_flow_metrics()
    assert metrics["flow_acceleration"] == 0.0
    assert metrics["flow_skewness"] == 0.0
    status = wave226.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 227: Cancellation Latency Asynchrony Guard Tests
# ---------------------------------------------------------------------------

def test_wave227_normal_symmetrical_latencies_no_block():
    """Balanced round-trip cancel and fill latencies (R_asynch < 4.0x) do not block."""
    assert not wave227.is_entry_blocked()
    assert not wave227.is_blocked()

    for _ in range(10):
        wave227.record_latencies(cancel_latency_ms=45.0, fill_latency_ms=40.0)

    assert not wave227.is_entry_blocked()
    metrics = wave227.get_asynchrony_metrics()
    assert metrics["mean_cancel_latency_ms"] < wave227.MAX_CANCEL_LATENCY_MS
    assert metrics["asynchrony_ratio"] < wave227.MAX_ASYNCH_RATIO
    status = wave227.get_status()
    assert not status["is_blocked"]


def test_wave227_severe_cancellation_latency_asynchrony_blocks():
    """Asymmetric latency blowout (mean cancel >= 200ms and ratio >= 4.0x) blocks entries for 45s."""
    # 10 updates where cancel latency is 250ms and fill latency is 30ms
    # Ratio = 250 / 30 = 8.33x >= 4.0x. Gap = 220ms >= 150ms.
    for _ in range(10):
        wave227.update(cancel_latency_ms=250.0, fill_latency_ms=30.0)

    assert wave227.is_entry_blocked()
    assert wave227.is_blocked()
    metrics = wave227.get_asynchrony_metrics()
    assert metrics["mean_cancel_latency_ms"] >= wave227.MAX_CANCEL_LATENCY_MS
    assert metrics["asynchrony_ratio"] >= wave227.MAX_ASYNCH_RATIO
    status = wave227.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave227_acute_single_cancellation_hang_blocks():
    """A single cancellation taking >= 500ms immediately triggers cooldown block."""
    wave227.record_cancellation_latency(cancel_latency_ms=550.0)

    assert wave227.is_entry_blocked()
    assert wave227.is_blocked()
    status = wave227.get_status()
    assert status["is_blocked"]


def test_wave227_insufficient_samples_no_block():
    """Fewer than MIN_SAMPLES=8 measurements does not trigger rolling ratio block."""
    for _ in range(4):
        wave227.record_latencies(cancel_latency_ms=220.0, fill_latency_ms=30.0)

    assert not wave227.is_entry_blocked()
    assert wave227.get_status()["sample_count"] == 4


def test_wave227_input_validation_and_reset():
    """Negative latencies, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave227.record_latencies(True, 30.0)
    wave227.record_latencies(50.0, False)
    wave227.record_latencies(-50.0, 30.0)
    wave227.record_latencies(50.0, -30.0)
    wave227.record_latencies(float("nan"), 30.0)
    wave227.record_latencies(50.0, float("inf"))

    assert not wave227.is_entry_blocked()

    # Trigger block then reset
    wave227.record_cancellation_latency(550.0)
    assert wave227.is_entry_blocked()

    wave227.reset()
    assert not wave227.is_entry_blocked()
    metrics = wave227.get_asynchrony_metrics()
    assert metrics["mean_cancel_latency_ms"] == 50.0
    status = wave227.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]
