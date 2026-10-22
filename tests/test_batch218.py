"""
tests/test_batch218.py
-----------------------
Unit test suite for Batch 218:
- Wave 202: Limit Order Book Queue Depth Replenishment Latency Guard
- Wave 203: Cross-Venue Asynchronous Price Drift & Latency Lag Guard

Verifies queue replenishment duration kinetics, inter-venue lead-lag convergence, fail-closed assertions,
and monotonic cooldown timers.
"""

import math
import time
import pytest

import wave202_limit_order_book_depth_replenishment_latency_guard as wave202
import wave203_cross_venue_quote_drift_asynchrony_guard as wave203


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave202.reset()
    wave203.reset()
    yield
    wave202.reset()
    wave203.reset()


# ---------------------------------------------------------------------------
# Wave 202: LOB Queue Depth Replenishment Latency Guard Tests
# ---------------------------------------------------------------------------

def test_wave202_normal_rapid_replenishment_no_block():
    """Depth swept by 50% but rapidly reconstituted within 0.2s does not block."""
    assert not wave202.is_entry_blocked()
    assert not wave202.is_blocked()

    # Pre-shock at t=100.0: Bid depth 20.0 lots
    wave202.record_depth(bid_depth=20.0, ask_depth=20.0, ts=100.0)

    # Shock at t=100.1: Bid depth swept down to 8.0 lots (60% drop)
    wave202.record_depth(bid_depth=8.0, ask_depth=20.0, ts=100.1)

    status = wave202.get_status()
    assert status["has_active_depletion"]

    # Rapid recovery at t=100.3 (elapsed = 0.2s < 1.5s): Bid depth restocked to 18.0 lots (90%)
    wave202.record_depth(bid_depth=18.0, ask_depth=20.0, ts=100.3)

    assert not wave202.is_entry_blocked()
    assert wave202.get_replenish_latency() < wave202.MAX_REPLENISH_LATENCY
    status = wave202.get_status()
    assert not status["has_active_depletion"]
    assert not status["is_blocked"]


def test_wave202_delayed_replenishment_latency_blocks():
    """Replenishment that takes >= 1.5s blocks entries for 45s."""
    wave202.record_depth(bid_depth=20.0, ask_depth=20.0, ts=100.0)
    # Sweep at t=100.1
    wave202.record_depth(bid_depth=8.0, ask_depth=20.0, ts=100.1)

    # Partial at t=101.0
    wave202.record_depth(bid_depth=10.0, ask_depth=20.0, ts=101.0)

    # Belated replenishment at t=101.8 (elapsed = 1.7s >= 1.5s)
    wave202.update(bid_depth=17.0, ask_depth=20.0, ts=101.8)

    assert wave202.is_entry_blocked()
    assert wave202.is_blocked()
    status = wave202.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave202_unreplenished_window_expiry_blocks():
    """Depth that fails to recover before the 2.0s deadline blocks entries."""
    wave202.record_depth(bid_depth=20.0, ask_depth=20.0, ts=100.0)
    # Sweep at t=100.1
    wave202.record_depth(bid_depth=6.0, ask_depth=20.0, ts=100.1)

    # Window expires at t=102.2s with depth still flat at 7.0 lots
    wave202.record_depth(bid_depth=7.0, ask_depth=20.0, ts=102.2)

    assert wave202.is_entry_blocked()
    assert not wave202.get_status()["has_active_depletion"]
    assert wave202.get_status()["is_blocked"]


def test_wave202_input_validation_and_fail_closed():
    """Booleans, negative depths, NaNs, and Infs are rejected safely."""
    wave202.record_depth(-10.0, 20.0)  # negative depth rejected
    wave202.record_depth(True, 20.0)  # bool rejected
    wave202.record_depth(20.0, False)  # bool rejected
    wave202.record_depth(float("nan"), 20.0)  # nan rejected
    wave202.record_depth(20.0, float("inf"))  # inf rejected
    wave202.record_depth("20.0", 20.0)  # string rejected

    assert not wave202.is_entry_blocked()


def test_wave202_reset_and_status():
    """Reset clears depth history, depletion state, and cooldown blocks."""
    wave202.record_depth(20.0, 20.0, ts=100.0)
    wave202.record_depth(5.0, 20.0, ts=100.1)
    wave202.record_depth(5.0, 20.0, ts=103.0)  # expired -> blocked

    assert wave202.is_entry_blocked()

    wave202.reset()
    assert not wave202.is_entry_blocked()
    assert wave202.get_replenish_latency() == 0.0
    status = wave202.get_status()
    assert not status["is_blocked"]
    assert not status["has_active_depletion"]


# ---------------------------------------------------------------------------
# Wave 203: Cross-Venue Quote Drift Asynchrony Guard Tests
# ---------------------------------------------------------------------------

def test_wave203_normal_synchronized_quotes_no_block():
    """Tightly synchronized cross-venue prices (< 1.0 bp dislocation) do not block."""
    assert not wave203.is_entry_blocked()
    assert not wave203.is_blocked()

    # Ref=2000.0, Local=2000.05 (0.25 bps dislocation)
    wave203.record_quotes(ref_price=2000.0, local_price=2000.05, ts=100.0)
    wave203.record_quotes(ref_price=2000.10, local_price=2000.15, ts=100.5)

    assert not wave203.is_entry_blocked()
    assert wave203.get_dislocation_bps() < wave203.MAX_DISLOCATION_BPS
    status = wave203.get_status()
    assert not status["is_blocked"]
    assert not status["has_active_dislocation"]


def test_wave203_transient_dislocation_converges_no_block():
    """A transient dislocation that converges back below 1.0 bp within 0.3s does not block."""
    # Dislocation begins at t=100.0: Ref=2000.0, Local=2000.80 (4.0 bps >= 2.5)
    wave203.record_quotes(ref_price=2000.0, local_price=2000.80, ts=100.0)
    assert wave203.get_status()["has_active_dislocation"]

    # Local quote catches up at t=100.3 (elapsed = 0.3s < 1.0s): Ref=2000.80, Local=2000.75 (0.25 bps)
    wave203.record_quotes(ref_price=2000.80, local_price=2000.75, ts=100.3)

    assert not wave203.is_entry_blocked()
    assert not wave203.get_status()["has_active_dislocation"]


def test_wave203_persistent_dislocation_lag_blocks():
    """Dislocation >= 2.5 bps persisting for >= 1.0s blocks entries for 45s."""
    # Dislocation begins at t=100.0: Ref=2000.0, Local=2000.70 (3.5 bps)
    wave203.record_quotes(ref_price=2000.0, local_price=2000.70, ts=100.0)

    # Dislocation continues at t=100.5 (elapsed = 0.5s)
    wave203.record_quotes(ref_price=2000.0, local_price=2000.65, ts=100.5)

    # Dislocation persists at t=101.1 (elapsed = 1.1s >= 1.0s)
    wave203.update(ref_price=2000.0, local_price=2000.65, ts=101.1)

    assert wave203.is_entry_blocked()
    assert wave203.is_blocked()
    status = wave203.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave203_input_validation_and_fail_closed():
    """Booleans, negatives, NaNs, and Infs are safely rejected."""
    wave203.record_quotes(True, 2000.0)  # bool rejected
    wave203.record_quotes(2000.0, False)  # bool rejected
    wave203.record_quotes(-2000.0, 2000.0)  # negative rejected
    wave203.record_quotes(2000.0, 0.0)  # zero rejected
    wave203.record_quotes(float("nan"), 2000.0)  # nan rejected
    wave203.record_quotes(2000.0, float("inf"))  # inf rejected

    assert not wave203.is_entry_blocked()


def test_wave203_reset_and_status():
    """Reset clears active dislocation timer, metrics, and cooldown blocks."""
    wave203.record_quotes(2000.0, 2001.0, ts=100.0)
    wave203.record_quotes(2000.0, 2001.0, ts=101.5)  # lag >= 1.0s -> blocked

    assert wave203.is_entry_blocked()

    wave203.reset()
    assert not wave203.is_entry_blocked()
    assert wave203.get_dislocation_bps() == 0.0
    status = wave203.get_status()
    assert not status["is_blocked"]
    assert not status["has_active_dislocation"]
