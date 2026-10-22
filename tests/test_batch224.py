"""
tests/test_batch224.py
-----------------------
Unit test suite for Batch 224:
- Wave 214: Volume-Weighted Spread & Depth Liquidity Wedge Guard
- Wave 215: Trade Interarrival Duration Shannon Entropy & Algorithmic Pacing Guard

Verifies top-of-book volume-weighted price displacement, depth asymmetry ratios,
discrete interarrival Shannon entropy collapse, fail-closed handling, and monotonic cooldowns.
"""

import math
import time
import pytest

import wave214_order_flow_imbalance_volume_weighted_spread_guard as wave214
import wave215_trade_arrival_interarrival_entropy_guard as wave215


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave214.reset()
    wave215.reset()
    yield
    wave214.reset()
    wave215.reset()


# ---------------------------------------------------------------------------
# Wave 214: Volume-Weighted Spread & Depth Liquidity Wedge Guard Tests
# ---------------------------------------------------------------------------

def test_wave214_balanced_liquidity_no_block():
    """Symmetric top-of-book depth yields zero wedge displacement and low depth ratio, no block."""
    assert not wave214.is_entry_blocked()
    assert not wave214.is_blocked()

    # Balanced book: Bid=2000.0 (10 lots), Ask=2000.20 (10 lots)
    # Mid = 2000.10, P_vw = 2000.10 -> Wedge = 0.0 bps, Depth Ratio = 1.0
    wave214.record_book(bid_price=2000.0, bid_depth=10.0, ask_price=2000.20, ask_depth=10.0)

    assert not wave214.is_entry_blocked()
    metrics = wave214.get_wedge_metrics()
    assert metrics["spread_wedge_bps"] < 0.01
    assert metrics["depth_ratio"] == 1.0
    status = wave214.get_status()
    assert not status["is_blocked"]


def test_wave214_volume_weighted_spread_wedge_blowout_blocks():
    """Severe volume-weighted center displacement (W_spread >= 2.5 bps) blocks entries for 45s."""
    # Bid=2000.0 (1 lot), Ask=2002.0 (99 lots)
    # Mid = 2001.0. P_vw = (2000*1 + 2002*99) / 100 = 2001.98
    # Wedge = |2001.98 - 2001.0| / 2001.0 * 10,000 = 4.897 bps >= 2.5 bps
    wave214.update(bid_price=2000.0, bid_depth=1.0, ask_price=2002.0, ask_depth=99.0)

    assert wave214.is_entry_blocked()
    assert wave214.is_blocked()
    metrics = wave214.get_wedge_metrics()
    assert metrics["spread_wedge_bps"] >= wave214.MAX_WEDGE_SPREAD_BPS
    status = wave214.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave214_depth_asymmetry_ratio_blowout_blocks():
    """Extreme top-of-book depth asymmetry (R_depth >= 15.0x with max_q >= 10.0) blocks entries."""
    # Bid=2000.0 (50 lots), Ask=2000.10 (1 lot)
    # Depth ratio = 50.0 / 1.0 = 50.0 >= 15.0
    wave214.record_book(bid_price=2000.0, bid_depth=50.0, ask_price=2000.10, ask_depth=1.0)

    assert wave214.is_entry_blocked()
    assert wave214.is_blocked()
    metrics = wave214.get_wedge_metrics()
    assert metrics["depth_ratio"] >= wave214.MAX_DEPTH_RATIO
    status = wave214.get_status()
    assert status["is_blocked"]


def test_wave214_input_validation_and_fail_closed():
    """Negative prices/depths, booleans, NaNs, Infs, and inverted books are safely rejected."""
    # Boolean rejected
    wave214.record_book(True, 10.0, 2000.20, 10.0)
    wave214.record_book(2000.0, True, 2000.20, 10.0)
    # Negative values rejected
    wave214.record_book(-2000.0, 10.0, 2000.20, 10.0)
    wave214.record_book(2000.0, -5.0, 2000.20, 10.0)
    # Inverted book rejected (Ask <= Bid)
    wave214.record_book(2000.50, 10.0, 2000.10, 10.0)
    # NaN and Inf rejected
    wave214.record_book(float("nan"), 10.0, 2000.20, 10.0)
    wave214.record_book(2000.0, 10.0, float("inf"), 10.0)

    assert not wave214.is_entry_blocked()


def test_wave214_reset_and_status():
    """Reset clears metrics, depth ratio, and active cooldown blocks."""
    wave214.record_book(bid_price=2000.0, bid_depth=1.0, ask_price=2002.0, ask_depth=99.0)
    assert wave214.is_entry_blocked()

    wave214.reset()
    assert not wave214.is_entry_blocked()
    metrics = wave214.get_wedge_metrics()
    assert metrics["spread_wedge_bps"] == 0.0
    assert metrics["depth_ratio"] == 1.0
    status = wave214.get_status()
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 215: Trade Arrival Interarrival Entropy Guard Tests
# ---------------------------------------------------------------------------

def test_wave215_normal_stochastic_interarrivals_no_block():
    """Stochastic trade interarrival times maintain high Shannon entropy (>= 0.50 bits), no block."""
    assert not wave215.is_entry_blocked()
    assert not wave215.is_blocked()

    # Varied trade durations across all discrete bins:
    # 0.02s (<50ms), 0.08s (50-100ms), 0.15s (100-250ms), 0.35s (250-500ms), 0.70s (500-1000ms), 1.50s (>1000ms)
    intervals = [0.02, 0.08, 0.15, 0.35, 0.70, 1.50, 0.03, 0.09, 0.20, 0.40, 0.80, 1.20, 0.04, 0.18, 0.30]
    t = 1000.0
    wave215.record_trade(ts=t)
    for dt in intervals:
        t += dt
        wave215.record_trade(ts=t)

    assert not wave215.is_entry_blocked()
    metrics = wave215.get_entropy_metrics()
    assert metrics["interarrival_entropy"] > wave215.MIN_INTERARRIVAL_ENTROPY
    status = wave215.get_status()
    assert not status["is_blocked"]


def test_wave215_deterministic_clockwork_pacing_blocks():
    """Deterministic, identical interarrival pacing with mean dt <= 0.30s collapses entropy and blocks."""
    # 15 trades arriving with strict clockwork interval of exactly 120ms (0.12s)
    # All intervals fall into bin 2 [100-250ms] -> p_2 = 1.0, Entropy = 0.0 bits <= 0.50 bits.
    # Mean dt = 0.12s <= 0.30s.
    t = 2000.0
    wave215.record_trade(ts=t)
    for _ in range(15):
        t += 0.12
        wave215.update(ts=t)

    assert wave215.is_entry_blocked()
    assert wave215.is_blocked()
    metrics = wave215.get_entropy_metrics()
    assert metrics["interarrival_entropy"] <= wave215.MIN_INTERARRIVAL_ENTROPY
    assert metrics["mean_duration_sec"] <= wave215.MAX_PACING_DT
    status = wave215.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave215_insufficient_samples_no_block():
    """Less than MIN_SAMPLES=12 trade durations does not trigger block regardless of pacing."""
    t = 3000.0
    wave215.record_trade(ts=t)
    # Only 8 intervals recorded
    for _ in range(8):
        t += 0.10
        wave215.record_trade(ts=t)

    assert not wave215.is_entry_blocked()
    status = wave215.get_status()
    assert status["sample_count"] == 8
    assert not status["is_blocked"]


def test_wave215_input_validation_and_fail_closed():
    """Booleans, negative timestamps, NaNs, and Infs are safely ignored without crashing."""
    wave215.record_trade(ts=True)
    wave215.record_trade(ts=False)
    wave215.record_trade(ts=-100.0)
    wave215.record_trade(ts=float("nan"))
    wave215.record_trade(ts=float("inf"))

    assert not wave215.is_entry_blocked()
    assert wave215.get_status()["sample_count"] == 0


def test_wave215_reset_and_status():
    """Reset clears trade duration deque, metrics, and active cooldown blocks."""
    t = 4000.0
    wave215.record_trade(ts=t)
    for _ in range(15):
        t += 0.10
        wave215.record_trade(ts=t)

    assert wave215.is_entry_blocked()

    wave215.reset()
    assert not wave215.is_entry_blocked()
    metrics = wave215.get_entropy_metrics()
    assert metrics["interarrival_entropy"] == 2.0
    status = wave215.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]
