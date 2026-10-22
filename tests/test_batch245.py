"""
tests/test_batch245.py
-----------------------
Unit test suite for Batch 245:
- Wave 256: Order Book Micro-Price Deviation & Fair Value Drift Guard
- Wave 257: Trade Intensity Autocorrelation & Clustering Memory Guard

Verifies Stoikov micro-price fair value displacement, acute deviation spikes,
ACD trade interarrival duration autocorrelation, rapid burst streaks, and cooldowns.
CELEBRATING 2,700+ VERIFIED TESTS MILESTONE!
"""

import math
import time
import pytest

import wave256_lob_micro_price_deviation_guard as wave256
import wave257_trade_intensity_autocorrelation_guard as wave257


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave256.reset()
    wave257.reset()
    yield
    wave256.reset()
    wave257.reset()


# ---------------------------------------------------------------------------
# Wave 256: LOB Micro-Price Deviation Guard Tests
# ---------------------------------------------------------------------------

def test_wave256_balanced_depths_no_block():
    """Balanced top-of-book depths (Q_bid == Q_ask) yield zero micro-price deviation and do not block."""
    assert not wave256.is_entry_blocked()
    assert not wave256.is_blocked()

    # Midpoint = 2000.00, equal depths of 5.0 lots -> micro-price = 2000.00
    wave256.record_quote_depths(bid_price=1999.80, ask_price=2000.20, bid_depth=5.0, ask_depth=5.0)

    assert not wave256.is_entry_blocked()
    metrics = wave256.get_micro_price_metrics()
    assert abs(metrics["deviation_bps"]) < 0.01
    status = wave256.get_status()
    assert not status["is_blocked"]


def test_wave256_micro_deviation_blocks():
    """Severe micro-price fair value displacement (|delta| >= 1.50 bps on depth >= 4.0 lots) blocks entries for 45s."""
    # Midpoint = 2000.00. Spread = 0.80 (4.0 bps, half-spread = 2.0 bps)
    # Bid price = 1999.60, Ask price = 2000.40.
    # Bid depth = 9.0 lots, Ask depth = 1.0 lot (total 10.0 lots >= 4.0 lots)
    # Micro-price = (9.0 * 2000.40 + 1.0 * 1999.60) / 10.0 = 2000.32
    # Deviation = (2000.32 - 2000.00) / 2000.00 * 10^4 = +1.60 bps >= 1.50 bps
    wave256.record_quote_depths(bid_price=1999.60, ask_price=2000.40, bid_depth=9.0, ask_depth=1.0)

    assert wave256.is_entry_blocked()
    assert wave256.is_blocked()
    metrics = wave256.get_micro_price_metrics()
    assert abs(metrics["deviation_bps"]) >= wave256.MAX_MICRO_DEVIATION_BPS
    status = wave256.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave256_acute_deviation_spike_blocks():
    """Acute micro-price displacement spike (|delta| >= 2.50 bps) immediately blocks entries for 45s."""
    # Direct deviation ingestion of +2.80 bps
    wave256.update(2.80)

    assert wave256.is_entry_blocked()
    assert wave256.is_blocked()
    metrics = wave256.get_micro_price_metrics()
    assert abs(metrics["deviation_bps"]) >= wave256.MAX_ACUTE_SPIKE_BPS
    status = wave256.get_status()
    assert status["is_blocked"]


def test_wave256_insufficient_depth_no_block():
    """Deviation >= 1.50 bps but combined depth < 4.0 lots without acute spike does not block."""
    # Deviation = 1.80 bps but total depth is only 2.0 lots (< 4.0 lots)
    wave256.record_micro_deviation(deviation_bps=1.80, total_depth=2.0)

    assert not wave256.is_entry_blocked()
    assert not wave256.get_status()["is_blocked"]


def test_wave256_input_validation_and_reset():
    """Crossed quotes (bid >= ask), non-positive prices/depths, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave256.record_quote_depths(2000.5, 2000.0, 5.0, 5.0)  # crossed
    wave256.record_quote_depths(-2000.0, 2001.0, 5.0, 5.0)
    wave256.record_quote_depths(2000.0, 2001.0, -5.0, 5.0)
    wave256.record_quote_depths(True, 2001.0, 5.0, 5.0)
    wave256.record_micro_deviation(float("nan"))
    wave256.record_micro_deviation(float("inf"))

    assert not wave256.is_entry_blocked()

    # Trigger block then reset
    wave256.record_micro_deviation(3.0)
    assert wave256.is_entry_blocked()

    wave256.reset()
    assert not wave256.is_entry_blocked()
    status = wave256.get_status()
    assert status["deviation_bps"] == 0.0
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 257: Trade Intensity Autocorrelation & Memory Guard Tests
# ---------------------------------------------------------------------------

def test_wave257_poisson_durations_no_block():
    """Uncorrelated trade durations (rho_1 ~ 0.0) do not block."""
    assert not wave257.is_entry_blocked()
    assert not wave257.is_blocked()

    # Uncorrelated series: 100, 300, 150, 350, 200, 400 ms
    uncorr = [100.0, 300.0, 150.0, 350.0, 200.0, 400.0] * 4  # 24 trades
    for d in uncorr:
        wave257.record_duration(duration_ms=d)

    assert not wave257.is_entry_blocked()
    metrics = wave257.get_intensity_metrics()
    assert metrics["autocorrelation"] < wave257.MAX_DURATION_AUTOCORRELATION
    status = wave257.get_status()
    assert not status["is_blocked"]
    assert status["sample_count"] == 24


def test_wave257_autocorrelation_clustering_blocks():
    """Persistent duration clustering memory (rho_1 >= 0.70 with mean <= 250ms on N >= 20) blocks entries for 45s."""
    # Strongly autocorrelated smooth sequence (rho_1 ~ 0.95, mean ~ 150ms)
    ar_seq = [round(150.0 + 80.0 * math.sin(i * 0.3), 1) for i in range(22)]
    for d in ar_seq:
        wave257.update(duration_ms=d)

    assert wave257.is_entry_blocked()
    assert wave257.is_blocked()
    metrics = wave257.get_intensity_metrics()
    assert metrics["autocorrelation"] >= wave257.MAX_DURATION_AUTOCORRELATION
    assert metrics["mean_duration_ms"] <= wave257.MAX_MEAN_DURATION_MS
    status = wave257.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave257_rapid_burst_streak_blocks():
    """Rapid interarrival burst streak (>= 8 consecutive trades with delta t <= 100ms) blocks entries for 45s."""
    # 8 consecutive rapid trades of 40ms
    for _ in range(8):
        wave257.record_duration(duration_ms=40.0)

    assert wave257.is_entry_blocked()
    assert wave257.is_blocked()
    metrics = wave257.get_intensity_metrics()
    assert metrics["rapid_streak"] >= wave257.MAX_RAPID_STREAK
    status = wave257.get_status()
    assert status["is_blocked"]


def test_wave257_insufficient_samples_no_block():
    """Fewer than MIN_SAMPLES=20 durations without 8-trade streak does not trigger autocorrelation block."""
    ar_seq = [round(150.0 + 80.0 * math.sin(i * 0.3), 1) for i in range(10)]  # 10 samples (< 20)
    for d in ar_seq:
        wave257.record_duration(d)

    assert not wave257.is_entry_blocked()
    status = wave257.get_status()
    assert status["sample_count"] == 10
    assert not status["is_blocked"]


def test_wave257_input_validation_and_reset():
    """Non-positive durations, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave257.record_duration(-10.0)
    wave257.record_duration(0.0)
    wave257.record_duration(True)
    wave257.record_duration(float("nan"))
    wave257.record_duration(float("inf"))

    assert not wave257.is_entry_blocked()
    assert wave257.get_status()["sample_count"] == 0

    # Trigger block then reset
    for _ in range(8):
        wave257.record_duration(50.0)
    assert wave257.is_entry_blocked()

    wave257.reset()
    assert not wave257.is_entry_blocked()
    status = wave257.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]
