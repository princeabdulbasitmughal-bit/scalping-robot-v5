"""
tests/test_batch238.py
-----------------------
Unit test suite for Batch 238:
- Wave 242: Microstructure Quote Volatility Shock & Flash Midpoint Jump Guard
- Wave 243: Limit Order Queue Lifespan Asymmetry & Predatory Churn Guard

Verifies high-frequency quote return volatility explosions, acute flash jumps,
cancellation lifespan asymmetry, bilateral flash churn, and cooldowns.
"""

import math
import time
import pytest

import wave242_quote_volatility_shock_guard as wave242
import wave243_lob_queue_lifespan_asymmetry_guard as wave243


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave242.reset()
    wave243.reset()
    yield
    wave242.reset()
    wave243.reset()


# ---------------------------------------------------------------------------
# Wave 242: Quote Volatility Shock & Flash Jump Guard Tests
# ---------------------------------------------------------------------------

def test_wave242_low_volatility_no_block():
    """Orderly quote stream with low return volatility (sigma_r < 1.0 bps) does not block."""
    assert not wave242.is_entry_blocked()
    assert not wave242.is_blocked()

    # Quote midpoints oscillating gently around 2000.00
    p = 2000.00
    for i in range(20):
        delta = 0.05 if i % 2 == 0 else -0.05
        p += delta
        wave242.record_quote(bid_price=p - 0.20, ask_price=p + 0.20)

    assert not wave242.is_entry_blocked()
    metrics = wave242.get_volatility_metrics()
    assert metrics["quote_volatility_bps"] < 1.50
    status = wave242.get_status()
    assert not status["is_blocked"]
    assert status["sample_count"] >= 15


def test_wave242_quote_volatility_explosion_blocks():
    """Severe quote return volatility explosion (sigma_r >= 3.50 bps on N >= 15) blocks entries for 45s."""
    # Alternating returns of +4.0 bps and -4.0 bps -> sigma_r ~ 4.1 bps >= 3.50 bps
    for i in range(18):
        r = 4.0 if i % 2 == 0 else -4.0
        wave242.record_quote_return(return_bps=r)

    assert wave242.is_entry_blocked()
    assert wave242.is_blocked()
    metrics = wave242.get_volatility_metrics()
    assert metrics["quote_volatility_bps"] >= wave242.MAX_QUOTE_VOLATILITY
    status = wave242.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave242_acute_flash_jump_blocks():
    """Acute single quote flash jump (|r_t| >= 6.00 bps) immediately blocks entries for 45s."""
    # Single flash jump of +7.5 bps
    wave242.update(bid_price=7.50)  # alias for record_quote_return when single arg passed

    assert wave242.is_entry_blocked()
    assert wave242.is_blocked()
    metrics = wave242.get_volatility_metrics()
    assert abs(metrics["latest_return_bps"]) >= wave242.MAX_ACUTE_JUMP_BPS
    status = wave242.get_status()
    assert status["is_blocked"]


def test_wave242_insufficient_samples_no_block():
    """Fewer than MIN_SAMPLES=15 returns without acute jump do not trigger volatility block."""
    for i in range(8):
        wave242.record_quote_return(return_bps=3.80 if i % 2 == 0 else -3.80)

    assert not wave242.is_entry_blocked()
    assert wave242.get_status()["sample_count"] == 8


def test_wave242_input_validation_and_reset():
    """Crossed quotes (bid >= ask), non-positive prices, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave242.record_quote(2000.5, 2000.0)  # crossed
    wave242.record_quote(-2000.0, 2000.5)  # negative
    wave242.record_quote(True, 2000.5)     # boolean
    wave242.record_quote_return(float("nan"))
    wave242.record_quote_return(float("inf"))

    assert not wave242.is_entry_blocked()
    assert wave242.get_status()["sample_count"] == 0

    # Trigger block then reset
    wave242.record_quote_return(8.0)
    assert wave242.is_entry_blocked()

    wave242.reset()
    assert not wave242.is_entry_blocked()
    status = wave242.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 243: LOB Queue Lifespan Asymmetry Guard Tests
# ---------------------------------------------------------------------------

def test_wave243_symmetric_lifespans_no_block():
    """Symmetric, healthy order lifespans (R_tau ~ 1.0, lifespans >= 500ms) do not block."""
    assert not wave243.is_entry_blocked()
    assert not wave243.is_blocked()

    # Both sides average 600ms
    for _ in range(12):
        wave243.record_quote_lifespans(bid_lifespan_ms=600.0, ask_lifespan_ms=600.0)

    assert not wave243.is_entry_blocked()
    metrics = wave243.get_lifespan_metrics()
    assert metrics["asymmetry_ratio"] == 1.0
    status = wave243.get_status()
    assert not status["is_blocked"]
    assert status["bid_sample_count"] == 12


def test_wave243_lifespan_asymmetry_blocks():
    """Severe queue lifespan asymmetry (R_tau >= 8.0x with fleeting <= 120ms on N >= 10) blocks entries for 45s."""
    # Bid orders rest 900ms, Ask orders canceled rapidly in 90ms -> ratio = 10.0x >= 8.0x
    for _ in range(12):
        wave243.update(bid_lifespan_ms=900.0, ask_lifespan_ms=90.0)

    assert wave243.is_entry_blocked()
    assert wave243.is_blocked()
    metrics = wave243.get_lifespan_metrics()
    assert metrics["asymmetry_ratio"] >= wave243.MAX_LIFESPAN_ASYMMETRY
    status = wave243.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave243_bilateral_flash_churn_blocks():
    """Bilateral flash churn (both sides <= 60ms on N >= 10) blocks entries for 45s."""
    # Intense HFT quote war: bid lifespan 45ms, ask lifespan 50ms
    for _ in range(11):
        wave243.record_order_cancellation(side="bid", lifespan_ms=45.0)
        wave243.record_order_cancellation(side="ask", lifespan_ms=50.0)

    assert wave243.is_entry_blocked()
    assert wave243.is_blocked()
    metrics = wave243.get_lifespan_metrics()
    assert metrics["mean_bid_lifespan_ms"] <= wave243.BILATERAL_FLASH_CHURN_MS
    assert metrics["mean_ask_lifespan_ms"] <= wave243.BILATERAL_FLASH_CHURN_MS
    status = wave243.get_status()
    assert status["is_blocked"]


def test_wave243_insufficient_samples_no_block():
    """Fewer than MIN_SAMPLES=10 on either side does not trigger asymmetry block."""
    for _ in range(6):
        wave243.record_quote_lifespans(bid_lifespan_ms=1000.0, ask_lifespan_ms=50.0)

    assert not wave243.is_entry_blocked()
    assert wave243.get_status()["bid_sample_count"] == 6


def test_wave243_input_validation_and_reset():
    """Invalid sides, non-positive lifespans, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave243.record_order_cancellation("invalid", 500.0)
    wave243.record_order_cancellation("bid", -10.0)
    wave243.record_order_cancellation("bid", 0.0)
    wave243.record_order_cancellation(True, 500.0)
    wave243.record_order_cancellation("bid", float("nan"))
    wave243.record_order_cancellation("bid", float("inf"))

    assert not wave243.is_entry_blocked()
    assert wave243.get_status()["bid_sample_count"] == 0

    # Trigger block then reset
    for _ in range(11):
        wave243.record_quote_lifespans(bid_lifespan_ms=40.0, ask_lifespan_ms=40.0)
    assert wave243.is_entry_blocked()

    wave243.reset()
    assert not wave243.is_entry_blocked()
    status = wave243.get_status()
    assert status["bid_sample_count"] == 0
    assert not status["is_blocked"]
