"""
tests/test_batch236.py
-----------------------
Unit test suite for Batch 236:
- Wave 238: Effective vs Quoted Spread Wedge & Outside-Quote Trade Distortion Guard
- Wave 239: Order Cancellation Intensity & Second-Derivative Acceleration Guard

Verifies effective spread wedge expansion, outside-quote trade ratios, single trade
blowout dislocations, cancellation rate acceleration surges, acute blitz bursts, and cooldowns.
"""

import math
import time
import pytest

import wave238_effective_quoted_spread_wedge_guard as wave238
import wave239_cancellation_intensity_acceleration_guard as wave239


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave238.reset()
    wave239.reset()
    yield
    wave238.reset()
    wave239.reset()


# ---------------------------------------------------------------------------
# Wave 238: Effective vs Quoted Spread Wedge Guard Tests
# ---------------------------------------------------------------------------

def test_wave238_inside_quote_trades_no_block():
    """Normal executions at or inside the quoted touch (W_spread <= 0) do not block."""
    assert not wave238.is_entry_blocked()
    assert not wave238.is_blocked()

    # Midpoint = 2000.20, Quoted spread = 0.40 (~2.0 bps)
    # Trade executes exactly at mid: 2000.20 -> effective spread = 0, wedge = -2.0 bps
    for _ in range(15):
        wave238.record_trade_execution(trade_price=2000.20, bid_price=2000.00, ask_price=2000.40)

    assert not wave238.is_entry_blocked()
    metrics = wave238.get_spread_metrics()
    assert metrics["wedge_bps"] < 0.0
    assert metrics["outside_ratio"] == 0.0
    status = wave238.get_status()
    assert not status["is_blocked"]
    assert status["sample_count"] == 15


def test_wave238_sustained_outside_wedge_blocks():
    """Sustained outside-quote execution (mean wedge >= 1.50 bps and outside ratio >= 50%) blocks entries for 45s."""
    # Midpoint = 2000.20, Quoted spread = 0.40 (~2.0 bps)
    # Outside trades execute at 2000.60 (above ask 2000.40 by 0.20)
    # Effective spread = 2 * 0.40 / 2000.20 * 10^4 = 3.9996 bps (~4.0 bps)
    # Wedge = 3.9996 - 1.9998 = 1.9998 bps (>= 1.50 bps)
    for _ in range(12):
        wave238.update(trade_price=2000.60, bid_price=2000.00, ask_price=2000.40)

    assert wave238.is_entry_blocked()
    assert wave238.is_blocked()
    metrics = wave238.get_spread_metrics()
    assert metrics["mean_wedge_bps"] >= wave238.MAX_MEAN_WEDGE_BPS
    assert metrics["outside_ratio"] >= wave238.MAX_OUTSIDE_RATIO
    status = wave238.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave238_single_trade_blowout_blocks():
    """Single trade blowout (W_spread >= 4.0 bps) immediately triggers blowout block."""
    # Midpoint = 2000.20, Quoted spread = 0.40 (~2.0 bps)
    # Extreme dislocation trade at 2001.00 (above ask 2000.40 by 0.60)
    # |2001.00 - 2000.20| = 0.80 -> Effective spread = 2 * 0.80 / 2000.20 * 10^4 = 7.999 bps
    # Wedge = 7.999 - 2.0 = ~6.0 bps (>= 4.0 bps)
    wave238.record_trade_execution(trade_price=2001.00, bid_price=2000.00, ask_price=2000.40)

    assert wave238.is_entry_blocked()
    assert wave238.is_blocked()
    metrics = wave238.get_spread_metrics()
    assert metrics["wedge_bps"] >= wave238.MAX_SINGLE_WEDGE_BPS
    status = wave238.get_status()
    assert status["is_blocked"]


def test_wave238_insufficient_samples_no_block():
    """Fewer than MIN_SAMPLES=10 trades without single trade blowout do not trigger sustained block."""
    # Trade wedge ~ 2.0 bps (above ask by 0.20), but only 6 samples (< 10)
    for _ in range(6):
        wave238.record_trade_execution(trade_price=2000.60, bid_price=2000.00, ask_price=2000.40)

    assert not wave238.is_entry_blocked()
    status = wave238.get_status()
    assert status["sample_count"] == 6
    assert not status["is_blocked"]


def test_wave238_input_validation_and_reset():
    """Invalid prices, crossed quotes (bid >= ask), booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    # Inverted quote
    wave238.record_trade_execution(2000.0, 2001.0, 1999.0)
    # Equal quote
    wave238.record_trade_execution(2000.0, 2000.0, 2000.0)
    # Non-positive
    wave238.record_trade_execution(-10.0, 2000.0, 2001.0)
    # Boolean
    wave238.record_trade_execution(True, 2000.0, 2001.0)
    # NaN and Inf
    wave238.record_trade_execution(float("nan"), 2000.0, 2001.0)
    wave238.record_trade_execution(2000.5, float("inf"), 2001.0)

    assert not wave238.is_entry_blocked()
    assert wave238.get_status()["sample_count"] == 0

    # Trigger block then reset
    wave238.record_trade_execution(trade_price=2001.00, bid_price=2000.00, ask_price=2000.40)
    assert wave238.is_entry_blocked()

    wave238.reset()
    assert not wave238.is_entry_blocked()
    status = wave238.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 239: Order Cancellation Intensity & Acceleration Guard Tests
# ---------------------------------------------------------------------------

def test_wave239_steady_cancellations_no_block():
    """Steady, moderate cancellation rates (C_curr ~ 5, acceleration < 15) do not block."""
    assert not wave239.is_entry_blocked()
    assert not wave239.is_blocked()

    # Steady rate of 5 cancels in previous second, 5 cancels in current second
    t0 = 1000.0
    for i in range(5):
        wave239.record_cancellation(count=1, ts=t0 + 0.1 * i)  # t in [1000.0, 1000.4] -> C_prev when evaluated at t0 + 1.5
    for i in range(5):
        wave239.record_cancellation(count=1, ts=t0 + 1.1 + 0.05 * i)  # t in [1001.1, 1001.3]

    assert not wave239.is_entry_blocked()
    metrics = wave239.get_cancellation_metrics()
    assert metrics["c_curr"] < wave239.MIN_CURRENT_CANCELS
    assert not wave239.get_status()["is_blocked"]


def test_wave239_acceleration_surge_blocks():
    """Acceleration surge (a >= 15.0 cancels/sec^2 with C_curr >= 20.0) blocks entries for 45s."""
    t0 = 2000.0
    # 2 cancels in previous second [t0 - 1.5]
    wave239.record_cancellation(count=2, ts=t0 - 1.5)

    # 22 cancels in current second [t0 - 0.8 to t0 - 0.6], spread out so acute burst (<0.5s) is not tripped
    # (e.g. at age 0.7s: 22 cancels)
    wave239.record_cancellation(count=22, ts=t0 - 0.7)

    # Now evaluate at t0 by sending a small update at t0
    wave239.update(count=1, ts=t0)

    assert wave239.is_entry_blocked()
    assert wave239.is_blocked()
    metrics = wave239.get_cancellation_metrics()
    assert metrics["cancellation_acceleration"] >= wave239.MAX_ACCELERATION
    assert metrics["c_curr"] >= wave239.MIN_CURRENT_CANCELS
    status = wave239.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave239_acute_blitz_burst_blocks():
    """Acute cancellation burst (>= 25 cancels in <= 0.5s) immediately triggers blitz block."""
    t0 = 3000.0
    # 26 cancellations within 0.2s of t0
    for i in range(26):
        wave239.record_cancellation(count=1, ts=t0 + 0.005 * i)

    assert wave239.is_entry_blocked()
    assert wave239.is_blocked()
    metrics = wave239.get_cancellation_metrics()
    assert metrics["acute_burst"] >= wave239.MAX_ACUTE_BURST
    status = wave239.get_status()
    assert status["is_blocked"]


def test_wave239_record_cancellation_rate_blocks():
    """Direct rate ingestion triggers instantaneous ceiling or acceleration surge."""
    # Test instant ceiling: 36.0 cancels/sec >= 35.0
    wave239.record_cancellation_rate(cancels_per_sec=36.0, prev_cancels_per_sec=5.0)
    assert wave239.is_entry_blocked()
    assert wave239.get_cancellation_metrics()["c_curr"] == 36.0

    wave239.reset()
    assert not wave239.is_entry_blocked()

    # Test acceleration surge: curr=22.0, prev=4.0 -> a = 18.0 >= 15.0
    wave239.record_cancellation_rate(cancels_per_sec=22.0, prev_cancels_per_sec=4.0)
    assert wave239.is_entry_blocked()
    assert wave239.get_cancellation_metrics()["cancellation_acceleration"] == 18.0


def test_wave239_input_validation_and_reset():
    """Negative counts, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave239.record_cancellation(count=-5)
    wave239.record_cancellation(count=True)
    wave239.record_cancellation(count=False)
    wave239.record_cancellation(count=float("nan"))
    wave239.record_cancellation(count=float("inf"))
    wave239.record_cancellation_rate(cancels_per_sec=-10.0)

    assert not wave239.is_entry_blocked()
    assert wave239.get_status()["event_count"] == 0

    # Trigger block then reset
    wave239.record_cancellation_rate(cancels_per_sec=40.0)
    assert wave239.is_entry_blocked()

    wave239.reset()
    assert not wave239.is_entry_blocked()
    status = wave239.get_status()
    assert status["event_count"] == 0
    assert not status["is_blocked"]
