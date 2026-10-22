"""
tests/test_batch241.py
-----------------------
Unit test suite for Batch 241:
- Wave 248: Microstructure Effective Spread Volatility & Liquidity Friction Guard
- Wave 249: Order Cancellation Clustering & Poisson Burst Dispersion Guard

Verifies effective spread volatility explosions, acute single-trade friction spurts,
super-Poisson cancellation overdispersion (Fano factor), acute mass bursts, and cooldowns.
"""

import math
import time
import pytest

import wave248_effective_spread_volatility_guard as wave248
import wave249_cancellation_clustering_dispersion_guard as wave249


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave248.reset()
    wave249.reset()
    yield
    wave248.reset()
    wave249.reset()


# ---------------------------------------------------------------------------
# Wave 248: Effective Spread Volatility Guard Tests
# ---------------------------------------------------------------------------

def test_wave248_tight_spreads_no_block():
    """Tight, steady effective spreads (low dispersion sigma <= 1.0 bps) do not block."""
    assert not wave248.is_entry_blocked()
    assert not wave248.is_blocked()

    # Steady effective spreads alternating between 2.0 and 2.4 bps
    for i in range(15):
        s = 2.0 if i % 2 == 0 else 2.4
        wave248.record_effective_spread(spread_bps=s)

    assert not wave248.is_entry_blocked()
    metrics = wave248.get_spread_volatility_metrics()
    assert metrics["spread_volatility_bps"] < 1.00
    status = wave248.get_status()
    assert not status["is_blocked"]
    assert status["sample_count"] == 15


def test_wave248_spread_volatility_explosion_blocks():
    """Severe effective spread volatility (sigma >= 2.50 bps on N >= 12) blocks entries for 45s."""
    # Alternating between 1.0 bps and 5.8 bps -> sigma ~ 2.55 bps >= 2.50 bps
    for i in range(14):
        s = 1.0 if i % 2 == 0 else 5.8
        wave248.record_effective_spread(spread_bps=s)

    assert wave248.is_entry_blocked()
    assert wave248.is_blocked()
    metrics = wave248.get_spread_volatility_metrics()
    assert metrics["spread_volatility_bps"] >= wave248.MAX_SPREAD_VOLATILITY
    status = wave248.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave248_acute_single_spread_blocks():
    """Acute single trade effective spread spurt (S_eff >= 6.00 bps) immediately blocks entries for 45s."""
    # Midpoint = 2000.00, Trade at 2000.70 -> S_eff = 2 * 0.70 / 2000.00 * 10^4 = 7.0 bps >= 6.00 bps
    wave248.record_trade(trade_price=2000.70, bid_price=1999.80, ask_price=2000.20)

    assert wave248.is_entry_blocked()
    assert wave248.is_blocked()
    metrics = wave248.get_spread_volatility_metrics()
    assert metrics["latest_spread_bps"] >= wave248.MAX_SINGLE_SPREAD
    status = wave248.get_status()
    assert status["is_blocked"]


def test_wave248_insufficient_samples_no_block():
    """Fewer than MIN_SAMPLES=12 trades without acute spurt does not trigger volatility block."""
    for i in range(8):
        wave248.record_effective_spread(spread_bps=1.0 if i % 2 == 0 else 5.5)

    assert not wave248.is_entry_blocked()
    status = wave248.get_status()
    assert status["sample_count"] == 8
    assert not status["is_blocked"]


def test_wave248_input_validation_and_reset():
    """Crossed quotes (bid >= ask), non-positive prices, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave248.record_trade(2000.0, 2000.5, 2000.0)  # crossed
    wave248.record_trade(-2000.0, 1999.0, 2001.0)
    wave248.record_trade(True, 1999.0, 2001.0)
    wave248.record_effective_spread(float("nan"))
    wave248.record_effective_spread(float("inf"))

    assert not wave248.is_entry_blocked()
    assert wave248.get_status()["sample_count"] == 0

    # Trigger block then reset
    wave248.record_effective_spread(7.5)
    assert wave248.is_entry_blocked()

    wave248.reset()
    assert not wave248.is_entry_blocked()
    status = wave248.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 249: Order Cancellation Clustering & Dispersion Guard Tests
# ---------------------------------------------------------------------------

def test_wave249_poisson_cancellations_no_block():
    """Homogeneous cancellation arrival stream across bins (Fano index D ~ 1.0) does not block."""
    assert not wave249.is_entry_blocked()
    assert not wave249.is_blocked()

    t0 = 5000.0
    # Evenly spaced cancellations: 2 cancellations every 0.25s (4 per 0.5s bin)
    for i in range(20):
        wave249.record_cancellation(count=2, ts=t0 + 0.25 * i)

    assert not wave249.is_entry_blocked()
    metrics = wave249.get_dispersion_metrics()
    assert metrics["dispersion_index"] < wave249.MAX_DISPERSION_INDEX
    status = wave249.get_status()
    assert not status["is_blocked"]


def test_wave249_super_poisson_clustering_blocks():
    """Super-Poisson cancellation clustering (D >= 3.00 on mean >= 4.0 cancels/bin) blocks entries for 45s."""
    t0 = 6000.0
    # Extreme clustering: 8 bins have 0 cancels, but 2 bins have 25 cancels each!
    # Total = 50 cancels across 10 bins -> mean = 5.0 cancels/bin >= 4.0
    # Bin 0 (age <= 0.5s): 25 cancels (spread over 0.2s so acute 1s burst is 25 < 30)
    wave249.record_cancellation(count=25, ts=t0)
    # Bin 5 (age ~ 2.6s): 25 cancels
    wave249.record_cancellation(count=25, ts=t0 - 2.6)

    # Small trigger event at t0
    wave249.update(count=1, ts=t0 + 0.05)

    assert wave249.is_entry_blocked()
    assert wave249.is_blocked()
    metrics = wave249.get_dispersion_metrics()
    assert metrics["dispersion_index"] >= wave249.MAX_DISPERSION_INDEX
    status = wave249.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave249_acute_mass_burst_blocks():
    """Acute mass cancellation burst (>= 30 cancels in <= 1.0s) immediately blocks entries for 45s."""
    t0 = 7000.0
    # 32 cancellations in 0.5s
    for i in range(32):
        wave249.record_cancellation(count=1, ts=t0 + 0.01 * i)

    assert wave249.is_entry_blocked()
    assert wave249.is_blocked()
    metrics = wave249.get_dispersion_metrics()
    assert metrics["acute_burst"] >= wave249.MAX_ACUTE_BURST
    status = wave249.get_status()
    assert status["is_blocked"]


def test_wave249_record_bin_counts_blocks():
    """Direct bin counts ingestion triggers super-Poisson clustering block."""
    # 10 bins: eight 0s, two 25s -> mean = 5.0, var ~ 97.2 -> D = 97.2 / 5.0 = 19.4 >= 3.00
    counts = [25.0, 0.0, 0.0, 0.0, 0.0, 25.0, 0.0, 0.0, 0.0, 0.0]
    wave249.record_bin_counts(counts)

    assert wave249.is_entry_blocked()
    metrics = wave249.get_dispersion_metrics()
    assert metrics["dispersion_index"] >= wave249.MAX_DISPERSION_INDEX
    status = wave249.get_status()
    assert status["is_blocked"]


def test_wave249_input_validation_and_reset():
    """Negative counts, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave249.record_cancellation(count=-5)
    wave249.record_cancellation(count=True)
    wave249.record_cancellation(count=False)
    wave249.record_cancellation(count=float("nan"))
    wave249.record_bin_counts([-1, 5, 5])

    assert not wave249.is_entry_blocked()
    assert wave249.get_status()["event_count"] == 0

    # Trigger block then reset
    wave249.record_cancellation(count=35)
    assert wave249.is_entry_blocked()

    wave249.reset()
    assert not wave249.is_entry_blocked()
    status = wave249.get_status()
    assert status["event_count"] == 0
    assert not status["is_blocked"]
