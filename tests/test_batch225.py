"""
tests/test_batch225.py
-----------------------
Unit test suite for Batch 225:
- Wave 216: Microstructure Bipower Variation & Realized Jump Diffusion Guard
- Wave 217: Fleeting Liquidity & High-Frequency Quote Cancellation Velocity Guard

Verifies Bipower Variation jump ratio decomposition, rapid quote flashing / phantom
liquidity cancellation bursts, fail-closed handling, and monotonic cooldown timers.
"""

import math
import time
import pytest

import wave216_microstructure_bipower_jump_diffusion_guard as wave216
import wave217_fleeting_liquidity_quote_cancellation_guard as wave217


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave216.reset()
    wave217.reset()
    yield
    wave216.reset()
    wave217.reset()


# ---------------------------------------------------------------------------
# Wave 216: Microstructure Bipower Jump Diffusion Guard Tests
# ---------------------------------------------------------------------------

def test_wave216_continuous_gaussian_diffusion_no_block():
    """Gradual continuous price increments yield BV close to RV, low jump fraction, no block."""
    assert not wave216.is_entry_blocked()
    assert not wave216.is_blocked()

    # Smooth diffusion with small 0.02 - 0.04 price increments
    p = 2000.0
    wave216.record_price(p)
    increments = [0.02, -0.02, 0.03, -0.01, 0.02, 0.03, -0.02, 0.01,
                  0.02, -0.03, 0.02, 0.01, -0.02, 0.02, 0.01, -0.01, 0.02]
    for inc in increments:
        p += inc
        wave216.record_price(p)

    assert not wave216.is_entry_blocked()
    metrics = wave216.get_jump_metrics()
    assert metrics["jump_fraction"] < wave216.MAX_JUMP_FRACTION
    status = wave216.get_status()
    assert not status["is_blocked"]


def test_wave216_discrete_jump_shock_blocks():
    """A discrete jump shock elevates realized variance and jump fraction (J >= 0.55), blocking entries."""
    p = 2000.0
    wave216.record_price(p)
    # 15 tiny baseline increments of 0.01 (0.05 bps)
    for _ in range(15):
        p += 0.01
        wave216.record_price(p)

    # Now a discrete jump shock: +1.00 (5.0 bps)
    # r_jump^2 = 25.0 bps^2, dominant in RV, while adjacent BV cross product is small
    p += 1.00
    wave216.update(p)

    assert wave216.is_entry_blocked()
    assert wave216.is_blocked()
    metrics = wave216.get_jump_metrics()
    assert metrics["jump_fraction"] >= wave216.MAX_JUMP_FRACTION
    assert metrics["realized_variance"] >= wave216.MIN_RV_BPS2
    status = wave216.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave216_instantaneous_volatility_spike_blocks():
    """A massive single-tick price shock (>= 8.0 bps) immediately blocks entries."""
    p = 2000.0
    wave216.record_price(p)
    # Single jump of 2.00 on 2000.0 is 10.0 bps >= 8.0 bps
    wave216.record_price(2002.0)

    # Needs MIN_SAMPLES for full statistics, but if max return hits 10.0 bps on n >= MIN_SAMPLES
    for _ in range(14):
        p = 2002.0 + 0.01
        wave216.record_price(p)

    assert wave216.is_entry_blocked()
    metrics = wave216.get_jump_metrics()
    assert metrics["max_return_bps"] >= wave216.MAX_VOLATILITY_SPIKE_BPS


def test_wave216_input_validation_and_fail_closed():
    """Booleans, negative prices, NaNs, and Infs are safely rejected without throwing."""
    wave216.record_price(True)
    wave216.record_price(False)
    wave216.record_price(-2000.0)
    wave216.record_price(0.0)
    wave216.record_price(float("nan"))
    wave216.record_price(float("inf"))

    assert not wave216.is_entry_blocked()
    assert wave216.get_status()["sample_count"] == 0


def test_wave216_reset_and_status():
    """Reset clears returns deque, jump metrics, and active cooldown blocks."""
    p = 2000.0
    wave216.record_price(p)
    for _ in range(15):
        p += 0.01
        wave216.record_price(p)
    wave216.record_price(p + 1.00)
    assert wave216.is_entry_blocked()

    wave216.reset()
    assert not wave216.is_entry_blocked()
    metrics = wave216.get_jump_metrics()
    assert metrics["realized_variance"] == 0.0
    assert metrics["jump_fraction"] == 0.0
    status = wave216.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 217: Fleeting Liquidity Quote Cancellation Guard Tests
# ---------------------------------------------------------------------------

def test_wave217_normal_stable_quotes_no_block():
    """Stable quotes with long resting life and no fleeting cancellations do not block."""
    assert not wave217.is_entry_blocked()
    assert not wave217.is_blocked()

    # Record normal cancellations with healthy resting lifespans (> 1.0s)
    t = 1000.0
    for _ in range(10):
        t += 1.0
        wave217.record_cancellation(volume=1.0, lifespan_sec=2.5, ts=t)

    assert not wave217.is_entry_blocked()
    metrics = wave217.get_cancellation_metrics()
    assert metrics["fleeting_count"] == 0
    assert metrics["fleeting_ratio"] == 0.0
    status = wave217.get_status()
    assert not status["is_blocked"]


def test_wave217_fleeting_cancellation_ratio_and_volume_blocks():
    """Elevated fleeting cancellations (>=6, ratio >= 0.50, vol >= 10.0 lots) block entries for 45s."""
    t = 2000.0
    # 8 fleeting cancellations with 40ms lifespan and 2.0 lots each (total 16.0 lots)
    for _ in range(8):
        t += 0.20
        wave217.record_cancellation(volume=2.0, lifespan_sec=0.040, ts=t)

    assert wave217.is_entry_blocked()
    assert wave217.is_blocked()
    metrics = wave217.get_cancellation_metrics()
    assert metrics["fleeting_count"] >= wave217.MIN_FLEETING_COUNT
    assert metrics["fleeting_ratio"] >= wave217.MAX_FLEETING_RATIO
    assert metrics["fleeting_volume"] >= wave217.MIN_FLEETING_VOLUME
    status = wave217.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave217_burst_spoofing_blocks():
    """Rapid burst of >= 6 fleeting cancellations within 1.0s immediately triggers cooldown block."""
    t = 3000.0
    # 6 cancellations arriving within 0.3s
    for _ in range(6):
        t += 0.05
        wave217.record_cancellation(volume=1.0, lifespan_sec=0.080, ts=t)

    assert wave217.is_entry_blocked()
    assert wave217.is_blocked()
    status = wave217.get_status()
    assert status["is_blocked"]


def test_wave217_inferred_quote_flicker_cancellation_blocks():
    """Inferred cancellations from rapid top-of-book depth evaporation (dt <= 150ms) block entries."""
    t = 4000.0
    wave217.record_quote(bid_price=2000.0, bid_depth=20.0, ask_price=2000.20, ask_depth=20.0, ts=t)

    # 7 rapid depth drops of 2.0 lots within 50ms intervals
    for _ in range(7):
        t += 0.05
        # Bid depth drops rapidly from previous value
        cur_depth = wave217._prev_bid_depth - 2.0
        wave217.update(bid_price=2000.0, bid_depth=cur_depth, ask_price=2000.20, ask_depth=20.0, ts=t)

    assert wave217.is_entry_blocked()
    metrics = wave217.get_cancellation_metrics()
    assert metrics["fleeting_count"] >= wave217.MIN_FLEETING_COUNT
    assert metrics["fleeting_volume"] >= 10.0


def test_wave217_reset_and_fail_closed():
    """Booleans, NaNs, Infs, and negative values are rejected, and reset restores clean state."""
    # Invalid cancellation inputs
    wave217.record_cancellation(True, 0.05)
    wave217.record_cancellation(1.0, True)
    wave217.record_cancellation(-1.0, 0.05)
    wave217.record_cancellation(1.0, -0.05)
    wave217.record_cancellation(float("nan"), 0.05)
    wave217.record_cancellation(1.0, float("inf"))

    # Invalid quote inputs
    wave217.record_quote(True, 10.0, 2000.20, 10.0)
    wave217.record_quote(2000.0, True, 2000.20, 10.0)
    wave217.record_quote(2000.50, 10.0, 2000.10, 10.0)  # Inverted

    assert not wave217.is_entry_blocked()

    # Trigger block then reset
    t = 5000.0
    for _ in range(6):
        t += 0.05
        wave217.record_cancellation(volume=2.0, lifespan_sec=0.05, ts=t)
    assert wave217.is_entry_blocked()

    wave217.reset()
    assert not wave217.is_entry_blocked()
    metrics = wave217.get_cancellation_metrics()
    assert metrics["fleeting_count"] == 0
    assert metrics["fleeting_volume"] == 0.0
    status = wave217.get_status()
    assert status["event_count"] == 0
    assert not status["is_blocked"]
