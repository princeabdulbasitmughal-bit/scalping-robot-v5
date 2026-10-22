"""
tests/test_batch217.py
-----------------------
Unit test suite for Batch 217:
- Wave 200: Order Book Quote Fading Velocity Guard
- Wave 201: Order Flow Imbalance (OFI) Higher-Order Curvature & Hydrodynamic Shock Guard

Verifies quote withdrawal dynamics, Cont-Kukanov-Stoikov OFI acceleration, fail-closed handling,
and monotonic cooldown timers.
"""

import math
import time
import pytest

import wave200_quote_fade_velocity_guard as wave200
import wave201_order_flow_imbalance_curvature_guard as wave201


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave200.reset()
    wave201.reset()
    yield
    wave200.reset()
    wave201.reset()


# ---------------------------------------------------------------------------
# Wave 200: Quote Fade Velocity Guard Tests
# ---------------------------------------------------------------------------

def test_wave200_normal_quote_updates_no_block():
    """Gradual, normal quote adjustments (< 10 bps/sec) do not block."""
    assert not wave200.is_entry_blocked()
    assert not wave200.is_blocked()

    # Anchor quote at t=100.0: Bid=2000.0, Ask=2000.20
    wave200.record_quote(bid=2000.0, ask=2000.20, ts=100.0)

    # Mild update at t=100.2 (dt=0.2s): Ask +0.05 (0.25 bps) -> 1.25 bps/s
    wave200.record_quote(bid=2000.02, ask=2000.25, ts=100.2)

    assert not wave200.is_entry_blocked()
    metrics = wave200.get_fade_metrics()
    assert metrics["ask_fade_velocity_bps_sec"] < wave200.MAX_FADE_VELOCITY
    assert metrics["bid_fade_velocity_bps_sec"] < wave200.MAX_FADE_VELOCITY
    status = wave200.get_status()
    assert not status["is_blocked"]


def test_wave200_ask_quote_fade_velocity_blocks():
    """Violent upward ask revision (>= 20 bps/sec) blocks entries for 45s."""
    # Anchor quote at t=100.0: Bid=2000.0, Ask=2000.20
    wave200.record_quote(bid=2000.0, ask=2000.20, ts=100.0)

    # Ask retreats rapidly: +0.60 (3.0 bps) in 0.05s -> 60.0 bps/sec >= 20.0
    wave200.update(bid=2000.0, ask=2000.80, ts=100.05)

    assert wave200.is_entry_blocked()
    assert wave200.is_blocked()
    metrics = wave200.get_fade_metrics()
    assert metrics["ask_fade_velocity_bps_sec"] >= wave200.MAX_FADE_VELOCITY
    status = wave200.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave200_bid_quote_fade_velocity_blocks():
    """Violent downward bid withdrawal (>= 20 bps/sec) blocks entries for 45s."""
    wave200.record_quote(bid=2000.0, ask=2000.20, ts=100.0)

    # Bid retreats downward: -0.60 (3.0 bps) in 0.05s -> 60.0 bps/sec >= 20.0
    wave200.record_quote(bid=1999.40, ask=2000.20, ts=100.05)

    assert wave200.is_entry_blocked()
    metrics = wave200.get_fade_metrics()
    assert metrics["bid_fade_velocity_bps_sec"] >= wave200.MAX_FADE_VELOCITY


def test_wave200_input_validation_and_fail_closed():
    """Inverted quotes, booleans, negatives, NaNs, and Infs are rejected safely."""
    wave200.record_quote(2000.20, 2000.00)  # inverted quote rejected
    wave200.record_quote(2000.00, 2000.00)  # zero spread rejected
    wave200.record_quote(True, 2000.20)  # bool bid rejected
    wave200.record_quote(2000.00, False)  # bool ask rejected
    wave200.record_quote(-2000.00, 2000.20)  # negative bid rejected
    wave200.record_quote(float("nan"), 2000.20)  # nan rejected
    wave200.record_quote(2000.00, float("inf"))  # inf rejected
    wave200.record_quote("2000.00", "2000.20")  # string rejected

    assert not wave200.is_entry_blocked()


def test_wave200_reset_and_status():
    """Reset clears quote history and fade metrics; get_status reports accurate diagnostic state."""
    wave200.record_quote(2000.0, 2000.20, ts=100.0)
    wave200.record_quote(2000.0, 2001.00, ts=100.02)  # violent fade -> blocked

    assert wave200.is_entry_blocked()

    wave200.reset()
    assert not wave200.is_entry_blocked()
    metrics = wave200.get_fade_metrics()
    assert metrics["bid_fade_velocity_bps_sec"] == 0.0
    assert metrics["ask_fade_velocity_bps_sec"] == 0.0
    status = wave200.get_status()
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 201: OFI Curvature Guard Tests
# ---------------------------------------------------------------------------

def test_wave201_normal_smooth_book_updates_no_block():
    """Gradual changes in order book depth produce low OFI curvature, no block."""
    assert not wave201.is_entry_blocked()
    assert not wave201.is_blocked()

    # Step 1: Baseline at t=100.0
    wave201.record_book(bid_price=2000.0, bid_depth=10.0, ask_price=2000.20, ask_depth=10.0, ts=100.0)

    # Step 2: Mild depth increase at t=100.1 (OFI = +0.5, v_OFI = +5.0)
    wave201.record_book(bid_price=2000.0, bid_depth=10.5, ask_price=2000.20, ask_depth=10.0, ts=100.1)

    # Step 3: Continued steady depth increase at t=100.2 (OFI = +0.5, v_OFI = +5.0, curvature = 0.0)
    wave201.record_book(bid_price=2000.0, bid_depth=11.0, ask_price=2000.20, ask_depth=10.0, ts=100.2)

    assert not wave201.is_entry_blocked()
    metrics = wave201.get_ofi_metrics()
    assert abs(metrics["ofi_curvature"]) < wave201.MAX_OFI_CURVATURE
    status = wave201.get_status()
    assert not status["is_blocked"]


def test_wave201_positive_ofi_curvature_surge_blocks():
    """A sudden non-linear surge in OFI acceleration (|kappa| >= 12 lots/sec^2) blocks entries."""
    # Step 1 at t=100.0: baseline
    wave201.record_book(bid_price=2000.0, bid_depth=10.0, ask_price=2000.20, ask_depth=10.0, ts=100.0)

    # Step 2 at t=100.1: small OFI (+0.2 lots, v = +2.0 lots/s)
    wave201.record_book(bid_price=2000.0, bid_depth=10.2, ask_price=2000.20, ask_depth=10.0, ts=100.1)

    # Step 3 at t=100.2: massive bid reinforcement / ask pull (+5.0 lots OFI, v = +50.0 lots/s)
    # Curvature = (50.0 - 2.0) / 0.1 = 480.0 lots/s^2 >> 12.0
    wave201.update(bid_price=2000.0, bid_depth=15.2, ask_price=2000.20, ask_depth=10.0, ts=100.2)

    assert wave201.is_entry_blocked()
    assert wave201.is_blocked()
    metrics = wave201.get_ofi_metrics()
    assert abs(metrics["ofi_curvature"]) >= wave201.MAX_OFI_CURVATURE
    status = wave201.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave201_negative_ofi_curvature_surge_blocks():
    """A sudden negative shock in OFI acceleration (bid collapse) blocks entries."""
    wave201.record_book(bid_price=2000.0, bid_depth=15.0, ask_price=2000.20, ask_depth=10.0, ts=100.0)
    # v = 0
    wave201.record_book(bid_price=2000.0, bid_depth=15.0, ask_price=2000.20, ask_depth=10.0, ts=100.1)

    # Sudden bid depth wipeout: bid depth drops from 15.0 to 5.0 (OFI = -10.0 lots, v = -100.0 lots/s)
    # Curvature = (-100.0 - 0.0) / 0.1 = -1000.0 lots/s^2
    wave201.record_book(bid_price=2000.0, bid_depth=5.0, ask_price=2000.20, ask_depth=10.0, ts=100.2)

    assert wave201.is_entry_blocked()
    metrics = wave201.get_ofi_metrics()
    assert abs(metrics["ofi_curvature"]) >= wave201.MAX_OFI_CURVATURE


def test_wave201_depth_and_price_invariance():
    """Cont-Kukanov-Stoikov rules handle higher price shifts properly."""
    # Step 1
    wave201.record_book(bid_price=2000.0, bid_depth=10.0, ask_price=2000.20, ask_depth=10.0, ts=100.0)
    # Step 2: Bid price jumps up to 2000.05 with depth 8.0 (Cont rule: new price level contributes all 8.0)
    wave201.record_book(bid_price=2000.05, bid_depth=8.0, ask_price=2000.20, ask_depth=10.0, ts=100.1)

    metrics = wave201.get_ofi_metrics()
    assert metrics["ofi"] == 8.0


def test_wave201_fail_closed_and_reset():
    """Invalid types, crossed prices, and negative depths are rejected; reset clears state."""
    wave201.record_book(bid_price=2000.20, bid_depth=10.0, ask_price=2000.00, ask_depth=10.0)  # crossed rejected
    wave201.record_book(bid_price=2000.00, bid_depth=-10.0, ask_price=2000.20, ask_depth=10.0)  # negative depth rejected
    wave201.record_book(bid_price=True, bid_depth=10.0, ask_price=2000.20, ask_depth=10.0)  # bool rejected
    wave201.record_book(bid_price=2000.00, bid_depth=10.0, ask_price=float("nan"), ask_depth=10.0)  # nan rejected

    assert not wave201.is_entry_blocked()

    # Trip block
    wave201.record_book(2000.0, 10.0, 2000.20, 10.0, ts=100.0)
    wave201.record_book(2000.0, 10.0, 2000.20, 10.0, ts=100.1)
    wave201.record_book(2000.0, 20.0, 2000.20, 10.0, ts=100.2)
    assert wave201.is_entry_blocked()

    # Reset
    wave201.reset()
    assert not wave201.is_entry_blocked()
    metrics = wave201.get_ofi_metrics()
    assert metrics["ofi"] == 0.0
    assert metrics["ofi_curvature"] == 0.0
    status = wave201.get_status()
    assert not status["is_blocked"]
