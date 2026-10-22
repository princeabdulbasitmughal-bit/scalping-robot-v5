"""
tests/test_batch222.py
-----------------------
Unit test suite for Batch 222:
- Wave 210: Order Flow Toxicity Variance Ratio & Autocorrelation Guard
- Wave 211: Quote Cancellation-to-Depth Ratio (CDR) & Phantom Liquidity Guard

Verifies Lo-MacKinlay Variance Ratio serial correlation, cancellation-to-depth surge kinetics,
fail-closed assertions, and monotonic cooldown timers.
"""

import math
import time
import pytest

import wave210_order_flow_toxicity_variance_ratio_guard as wave210
import wave211_cancellation_depth_ratio_surge_guard as wave211


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave210.reset()
    wave211.reset()
    yield
    wave210.reset()
    wave211.reset()


# ---------------------------------------------------------------------------
# Wave 210: Order Flow Toxicity Variance Ratio Guard Tests
# ---------------------------------------------------------------------------

def test_wave210_normal_random_walk_no_block():
    """Independent price increments maintain VR(2) near 1.0 and do not block."""
    assert not wave210.is_entry_blocked()
    assert not wave210.is_blocked()

    price = 2000.0
    wave210.record_price(price)
    # Balanced uncorrelated steps
    steps = [0.20, 0.10, 0.15, -0.10, -0.20, 0.15, 0.10, -0.15, -0.10, 0.20,
             0.10, 0.15, -0.20, -0.10, 0.15, 0.20, -0.15, -0.10, 0.10, 0.20,
             -0.20, 0.15, -0.10, 0.10, -0.15]
    for s in steps:
        price += s
        wave210.record_price(price)

    assert not wave210.is_entry_blocked()
    vr = wave210.get_variance_ratio()
    assert wave210.MIN_VARIANCE_RATIO < vr < wave210.MAX_VARIANCE_RATIO
    status = wave210.get_status()
    assert not status["is_blocked"]


def test_wave210_trending_momentum_sweep_blocks():
    """Positively autocorrelated trending increments push VR(2) >= 1.50, blocking entries."""
    price = 2000.0
    wave210.record_price(price)
    # Autocorrelated persistence: runs of 6 identical steps produce VR ~ 1.74 >= 1.50
    steps = [0.30] * 6 + [-0.30] * 6 + [0.30] * 6 + [-0.30] * 6 + [0.30] * 6
    for s in steps:
        price += s
        wave210.update(price)

    assert wave210.is_entry_blocked()
    assert wave210.is_blocked()
    assert wave210.get_variance_ratio() >= wave210.MAX_VARIANCE_RATIO
    status = wave210.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave210_bid_ask_bounce_chop_blocks():
    """Severe alternating bounce (+0.20, -0.20) collapses 2-step variance (VR <= 0.50), blocking entries."""
    price = 2000.0
    wave210.record_price(price)
    for i in range(26):
        price += 0.20 if i % 2 == 0 else -0.20
        wave210.record_price(price)

    assert wave210.is_entry_blocked()
    assert wave210.get_variance_ratio() <= wave210.MIN_VARIANCE_RATIO


def test_wave210_input_validation_and_fail_closed():
    """Booleans, negative prices, NaNs, and Infs are safely rejected."""
    wave210.record_price(True)
    wave210.record_price(False)
    wave210.record_price(-2000.0)
    wave210.record_price(0.0)
    wave210.record_price(float("nan"))
    wave210.record_price(float("inf"))

    assert not wave210.is_entry_blocked()


def test_wave210_reset_and_status():
    """Reset clears return buffers, metrics, and active cooldown blocks."""
    price = 2000.0
    wave210.record_price(price)
    steps = [0.30] * 6 + [-0.30] * 6 + [0.30] * 6 + [-0.30] * 6 + [0.30] * 6
    for s in steps:
        price += s
        wave210.record_price(price)

    assert wave210.is_entry_blocked()

    wave210.reset()
    assert not wave210.is_entry_blocked()
    assert wave210.get_variance_ratio() == 1.0
    status = wave210.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 211: Cancellation-to-Depth Ratio (CDR) Guard Tests
# ---------------------------------------------------------------------------

def test_wave211_normal_cancellations_no_block():
    """Normal modest cancellations (CDR <= 1.0) do not trigger block."""
    assert not wave211.is_entry_blocked()
    assert not wave211.is_blocked()

    # 5.0 lots cancelled against 10.0 lots depth (CDR = 0.5)
    wave211.record_cancellation(cancel_volume=5.0, standing_depth=10.0, ts=100.0)

    assert not wave211.is_entry_blocked()
    metrics = wave211.get_cdr_metrics()
    assert metrics["cdr"] < wave211.MAX_CDR
    status = wave211.get_status()
    assert not status["is_blocked"]


def test_wave211_cancellation_depth_ratio_surge_blocks():
    """Massive cancellation flurry (>= 3.0x depth with >= 15 lots) blocks entries for 45s."""
    # 25.0 lots cancelled against 5.0 lots standing depth (CDR = 5.0 >= 3.0)
    wave211.update(cancel_volume=25.0, standing_depth=5.0, ts=100.0)

    assert wave211.is_entry_blocked()
    assert wave211.is_blocked()
    metrics = wave211.get_cdr_metrics()
    assert metrics["cdr"] >= wave211.MAX_CDR
    assert metrics["window_cancellations"] >= wave211.MIN_CANCEL_VOLUME
    status = wave211.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave211_book_depth_inferred_cancellations():
    """Depth drops at identical price levels are correctly inferred as cancellations."""
    # Step 1: Bid price 2000.0 with 25.0 lots, Ask 2000.20 with 5.0 lots
    wave211.record_depth(bid_price=2000.0, bid_depth=25.0, ask_price=2000.20, ask_depth=5.0, ts=100.0)

    # Step 2: Bid depth abruptly cancelled from 25.0 down to 2.0 (23.0 lots cancelled) at identical price
    # Standing depth = (2.0 + 4.0) / 2 = 3.0. CDR = 23.0 / 3.0 = 7.66 >= 3.0
    wave211.record_depth(bid_price=2000.0, bid_depth=2.0, ask_price=2000.20, ask_depth=4.0, ts=100.5)

    assert wave211.is_entry_blocked()
    metrics = wave211.get_cdr_metrics()
    assert metrics["window_cancellations"] >= 20.0
    assert metrics["cdr"] >= wave211.MAX_CDR


def test_wave211_input_validation_and_fail_closed():
    """Negative volumes, booleans, NaNs, and Infs are safely rejected."""
    wave211.record_cancellation(cancel_volume=-10.0, standing_depth=10.0)
    wave211.record_cancellation(cancel_volume=True, standing_depth=10.0)
    wave211.record_cancellation(cancel_volume=10.0, standing_depth=False)
    wave211.record_cancellation(cancel_volume=float("nan"), standing_depth=10.0)
    wave211.record_cancellation(cancel_volume=10.0, standing_depth=float("inf"))

    assert not wave211.is_entry_blocked()


def test_wave211_reset_and_status():
    """Reset clears cancellation deque, metrics, and active cooldown blocks."""
    wave211.record_cancellation(30.0, 5.0, ts=100.0)
    assert wave211.is_entry_blocked()

    wave211.reset()
    assert not wave211.is_entry_blocked()
    metrics = wave211.get_cdr_metrics()
    assert metrics["cdr"] == 0.0
    assert metrics["window_cancellations"] == 0.0
    status = wave211.get_status()
    assert not status["is_blocked"]
