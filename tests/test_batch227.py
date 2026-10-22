"""
tests/test_batch227.py
-----------------------
Unit test suite for Batch 227:
- Wave 220: Realized Semivariance & Downside Jump Asymmetry Guard
- Wave 221: Fill Latency Sniping & High-Frequency Latency Compression Guard

Verifies signed semivariance decomposition, downside variance cascades, execution latency
compression, ultra-fast snipe bursts, fail-closed handling, and monotonic cooldown timers.
"""

import math
import time
import pytest

import wave220_realized_semivariance_downside_asymmetry_guard as wave220
import wave221_fill_latency_sniping_compression_guard as wave221


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave220.reset()
    wave221.reset()
    yield
    wave220.reset()
    wave221.reset()


# ---------------------------------------------------------------------------
# Wave 220: Realized Semivariance Asymmetry Guard Tests
# ---------------------------------------------------------------------------

def test_wave220_balanced_symmetric_semivariance_no_block():
    """Symmetric positive and negative returns maintain balanced semivariance (Q_- ~ 0.50), no block."""
    assert not wave220.is_entry_blocked()
    assert not wave220.is_blocked()

    p = 2000.0
    wave220.record_price(p)
    # 18 alternating ticks (+0.30, -0.30)
    for i in range(18):
        p += (0.30 if i % 2 == 0 else -0.30)
        wave220.record_price(p)

    assert not wave220.is_entry_blocked()
    metrics = wave220.get_semivariance_metrics()
    assert 0.35 <= metrics["downside_ratio"] <= 0.65
    status = wave220.get_status()
    assert not status["is_blocked"]


def test_wave220_downside_liquidation_cascade_blocks():
    """Downside variance dominance (Q_- >= 0.85 with RV >= 2.50 bps^2) blocks entries for 45s."""
    p = 2000.0
    wave220.record_price(p)
    # 15 consecutive down ticks of -0.40 (2.0 bps each)
    for _ in range(15):
        p -= 0.40
        wave220.update(p)

    assert wave220.is_entry_blocked()
    assert wave220.is_blocked()
    metrics = wave220.get_semivariance_metrics()
    assert metrics["downside_ratio"] >= wave220.MAX_DOWNSIDE_RATIO
    assert metrics["realized_variance"] >= wave220.MIN_RV_BPS2
    status = wave220.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave220_upside_parabolic_squeeze_blocks():
    """Upside variance dominance (Q_- <= 0.15 with RV >= 2.50 bps^2) blocks entries."""
    p = 2000.0
    wave220.record_price(p)
    # 15 consecutive up ticks of +0.50 (2.5 bps each)
    for _ in range(15):
        p += 0.50
        wave220.record_price(p)

    assert wave220.is_entry_blocked()
    metrics = wave220.get_semivariance_metrics()
    assert metrics["downside_ratio"] <= wave220.MIN_DOWNSIDE_RATIO
    assert metrics["realized_variance"] >= wave220.MIN_RV_BPS2


def test_wave220_insufficient_variance_floor_no_block():
    """Asymmetric returns below MIN_RV_BPS2 (2.50 bps^2) do not block during dead flat markets."""
    p = 2000.0
    wave220.record_price(p)
    # 16 tiny down ticks of 0.001 (0.005 bps each -> r^2 = 0.000025)
    for _ in range(16):
        p -= 0.001
        wave220.record_price(p)

    assert not wave220.is_entry_blocked()
    metrics = wave220.get_semivariance_metrics()
    assert metrics["realized_variance"] < wave220.MIN_RV_BPS2


def test_wave220_input_validation_and_reset():
    """Non-numeric, boolean, negative, NaN, Inf values are rejected, and reset clears state."""
    wave220.record_price(True)
    wave220.record_price(False)
    wave220.record_price(-2000.0)
    wave220.record_price(0.0)
    wave220.record_price(float("nan"))
    wave220.record_price(float("inf"))

    assert not wave220.is_entry_blocked()

    # Trigger block then reset
    p = 2000.0
    wave220.record_price(p)
    for _ in range(15):
        p -= 0.50
        wave220.record_price(p)
    assert wave220.is_entry_blocked()

    wave220.reset()
    assert not wave220.is_entry_blocked()
    metrics = wave220.get_semivariance_metrics()
    assert metrics["realized_variance"] == 0.0
    status = wave220.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 221: Fill Latency Sniping Guard Tests
# ---------------------------------------------------------------------------

def test_wave221_normal_execution_latency_no_block():
    """Normal execution latency (mean >= 80ms, sniped ratio < 0.60) does not block."""
    assert not wave221.is_entry_blocked()
    assert not wave221.is_blocked()

    t = 1000.0
    for _ in range(15):
        t += 1.0
        wave221.record_execution_latency(latency_ms=120.0, ts=t)

    assert not wave221.is_entry_blocked()
    metrics = wave221.get_latency_metrics()
    assert metrics["sniped_fill_ratio"] == 0.0
    assert metrics["mean_latency_ms"] == 120.0
    status = wave221.get_status()
    assert not status["is_blocked"]


def test_wave221_latency_compression_sniping_blocks():
    """Compressed fill latencies (R_sniped >= 0.60 with mean <= 50ms) block entries for 45s."""
    t = 2000.0
    for _ in range(12):
        t += 1.0  # Spaced out to avoid burst trigger
        wave221.update(latency_ms=25.0, ts=t)

    assert wave221.is_entry_blocked()
    assert wave221.is_blocked()
    metrics = wave221.get_latency_metrics()
    assert metrics["sniped_fill_ratio"] >= wave221.MAX_SNIPED_FILL_RATIO
    assert metrics["mean_latency_ms"] <= wave221.MAX_MEAN_LATENCY_MS
    status = wave221.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave221_rapid_ultra_fast_snipe_burst_blocks():
    """A rapid burst of >= 4 ultra-fast fills (<= 15ms) in <= 2.0s immediately triggers cooldown block."""
    t = 3000.0
    for _ in range(4):
        t += 0.20
        wave221.record_fill(order_id="ord_1", latency_ms=10.0, ts=t)

    assert wave221.is_entry_blocked()
    assert wave221.is_blocked()
    status = wave221.get_status()
    assert status["is_blocked"]
    assert status["burst_snipes"] >= wave221.BURST_SNIPE_COUNT


def test_wave221_insufficient_samples_no_block():
    """Fewer than MIN_SAMPLES=10 fills does not trigger ratio block."""
    t = 4000.0
    for _ in range(6):
        t += 1.0
        wave221.record_execution_latency(latency_ms=20.0, ts=t)

    assert not wave221.is_entry_blocked()
    assert wave221.get_status()["sample_count"] == 6


def test_wave221_input_validation_and_reset():
    """Negative latencies, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave221.record_execution_latency(True)
    wave221.record_execution_latency(False)
    wave221.record_execution_latency(-10.0)
    wave221.record_execution_latency(float("nan"))
    wave221.record_execution_latency(float("inf"))

    assert not wave221.is_entry_blocked()

    # Trigger block then reset
    t = 5000.0
    for _ in range(4):
        t += 0.10
        wave221.record_execution_latency(latency_ms=8.0, ts=t)
    assert wave221.is_entry_blocked()

    wave221.reset()
    assert not wave221.is_entry_blocked()
    metrics = wave221.get_latency_metrics()
    assert metrics["sniped_fill_ratio"] == 0.0
    status = wave221.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]
