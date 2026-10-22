"""
tests/test_batch240.py
-----------------------
Unit test suite for Batch 240:
- Wave 246: Trade Flow Acceleration & Volume Clustered Avalanche Guard
- Wave 247: Limit Order Fill-to-Cancel Ratio Decay & Toxic Fading Guard

Verifies trade arrival acceleration surges, institutional clustered volume avalanches,
acute sub-second bursts, fill-to-cancel ratio decays, toxic cancellation explosions, and cooldowns.
"""

import math
import time
import pytest

import wave246_trade_flow_acceleration_avalanche_guard as wave246
import wave247_fill_to_cancel_ratio_decay_guard as wave247


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave246.reset()
    wave247.reset()
    yield
    wave246.reset()
    wave247.reset()


# ---------------------------------------------------------------------------
# Wave 246: Trade Flow Acceleration & Volume Avalanche Guard Tests
# ---------------------------------------------------------------------------

def test_wave246_steady_trades_no_block():
    """Steady, moderate trade arrivals (lambda ~ 4 trades/sec, low volume) do not block."""
    assert not wave246.is_entry_blocked()
    assert not wave246.is_blocked()

    t0 = 1000.0
    for i in range(8):
        wave246.record_trade(volume_lots=0.5, ts=t0 + 0.25 * i)

    assert not wave246.is_entry_blocked()
    metrics = wave246.get_avalanche_metrics()
    assert metrics["rate_curr"] < wave246.MIN_CURRENT_RATE
    status = wave246.get_status()
    assert not status["is_blocked"]


def test_wave246_acceleration_surge_blocks():
    """Trade arrival acceleration surge (a_trade >= 12.0 with lambda_curr >= 18.0) blocks entries for 45s."""
    t0 = 2000.0
    # 2 trades in previous second [t0 - 1.5]
    wave246.record_trade(volume_lots=0.1, ts=t0 - 1.5)
    wave246.record_trade(volume_lots=0.1, ts=t0 - 1.4)

    # 19 trades in current second [t0 - 0.9 to t0 - 0.4] (spread out so acute 0.3s volume burst is not tripped)
    for i in range(19):
        wave246.record_trade(volume_lots=0.1, ts=t0 - 0.9 + 0.02 * i)

    # Trigger evaluation at t0
    wave246.update(volume_lots=0.1, ts=t0)

    assert wave246.is_entry_blocked()
    assert wave246.is_blocked()
    metrics = wave246.get_avalanche_metrics()
    assert metrics["trade_acceleration"] >= wave246.MAX_TRADE_ACCELERATION
    assert metrics["rate_curr"] >= wave246.MIN_CURRENT_RATE
    status = wave246.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave246_cluster_volume_avalanche_blocks():
    """Institutional clustered volume avalanche (V_cluster >= 20.0 lots in <= 1.0s) blocks entries for 45s."""
    t0 = 3000.0
    # 4 institutional block trades of 5.5 lots each within 0.8s -> 22.0 lots
    wave246.record_trade(volume_lots=5.5, ts=t0 - 0.8)
    wave246.record_trade(volume_lots=5.5, ts=t0 - 0.6)
    wave246.record_trade(volume_lots=5.5, ts=t0 - 0.4)
    wave246.record_trade(volume_lots=5.5, ts=t0)

    assert wave246.is_entry_blocked()
    assert wave246.is_blocked()
    metrics = wave246.get_avalanche_metrics()
    assert metrics["cluster_volume"] >= wave246.MAX_CLUSTER_VOLUME
    status = wave246.get_status()
    assert status["is_blocked"]


def test_wave246_acute_volume_burst_blocks():
    """Acute sub-second volume burst (V_acute >= 12.0 lots in <= 0.3s) immediately blocks entries for 45s."""
    t0 = 4000.0
    # 13.0 lots within 0.1s
    wave246.record_trade(volume_lots=6.5, ts=t0)
    wave246.record_trade(volume_lots=6.5, ts=t0 + 0.1)

    assert wave246.is_entry_blocked()
    assert wave246.is_blocked()
    metrics = wave246.get_avalanche_metrics()
    assert metrics["acute_volume"] >= wave246.MAX_ACUTE_VOLUME
    status = wave246.get_status()
    assert status["is_blocked"]


def test_wave246_input_validation_and_reset():
    """Negative volumes, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave246.record_trade(-1.0)
    wave246.record_trade(0.0)
    wave246.record_trade(True)
    wave246.record_trade(float("nan"))
    wave246.record_trade(float("inf"))
    wave246.record_trade_rate(-5.0)

    assert not wave246.is_entry_blocked()
    assert wave246.get_status()["event_count"] == 0

    # Trigger block then reset
    wave246.record_trade(25.0)
    assert wave246.is_entry_blocked()

    wave246.reset()
    assert not wave246.is_entry_blocked()
    status = wave246.get_status()
    assert status["event_count"] == 0
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 247: Fill-to-Cancel Ratio Decay & Toxic Fading Guard Tests
# ---------------------------------------------------------------------------

def test_wave247_healthy_ratio_no_block():
    """Orderly trading with healthy fill-to-cancel ratio (theta ~ 0.25, 1 fill per 4 cancels) does not block."""
    assert not wave247.is_entry_blocked()
    assert not wave247.is_blocked()

    t0 = 5000.0
    # 10 fills and 40 cancels over 20 seconds (ratio = 10 / 40 = 0.25)
    for i in range(50):
        evt = "fill" if i % 5 == 0 else "cancel"
        wave247.record_event(evt, ts=t0 + 0.4 * i)

    assert not wave247.is_entry_blocked()
    metrics = wave247.get_ratio_metrics()
    assert metrics["fill_to_cancel_ratio"] >= 0.20
    status = wave247.get_status()
    assert not status["is_blocked"]


def test_wave247_ratio_collapse_blocks():
    """Severe fill-to-cancel ratio collapse (theta <= 0.025 on N_cancel >= 40) blocks entries for 45s."""
    t0 = 6000.0
    # 1 fill and 45 cancels (ratio = 1 / 45 = 0.022 <= 0.025)
    wave247.record_event("fill", ts=t0)
    for i in range(45):
        wave247.update("cancel", ts=t0 + 0.1 * (i + 1))

    assert wave247.is_entry_blocked()
    assert wave247.is_blocked()
    metrics = wave247.get_ratio_metrics()
    assert metrics["fill_to_cancel_ratio"] <= wave247.MIN_FILL_CANCEL_RATIO
    assert metrics["cancels_count"] >= wave247.MIN_CANCELS_THRESHOLD
    status = wave247.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave247_acute_cancel_explosion_blocks():
    """Acute cancellation explosion (>= 35 cancels in <= 2.0s with 0 fills) blocks entries for 45s."""
    t0 = 7000.0
    for i in range(36):
        wave247.record_event("cancel", ts=t0 + 0.04 * i)  # all within 1.5s

    assert wave247.is_entry_blocked()
    assert wave247.is_blocked()
    metrics = wave247.get_ratio_metrics()
    assert metrics["acute_cancels"] >= wave247.ACUTE_CANCEL_EXPLOSION
    status = wave247.get_status()
    assert status["is_blocked"]


def test_wave247_record_counts_blocks():
    """Direct counts ingestion triggers fill-to-cancel collapse block."""
    # 1 fill and 50 cancels -> ratio = 0.020 <= 0.025
    wave247.record_counts(fills_count=1, cancels_count=50)

    assert wave247.is_entry_blocked()
    metrics = wave247.get_ratio_metrics()
    assert metrics["fill_to_cancel_ratio"] == 0.020
    status = wave247.get_status()
    assert status["is_blocked"]


def test_wave247_input_validation_and_reset():
    """Invalid event types, booleans, negative counts, NaNs, and Infs are rejected, and reset restores clean state."""
    wave247.record_event("invalid")
    wave247.record_event(True)
    wave247.record_event(False)
    wave247.record_event(float("nan"))
    wave247.record_counts(-5, 10)
    wave247.record_counts(10, -5)

    assert not wave247.is_entry_blocked()
    assert wave247.get_status()["event_count"] == 0

    # Trigger block then reset
    wave247.record_counts(0, 50)
    assert wave247.is_entry_blocked()

    wave247.reset()
    assert not wave247.is_entry_blocked()
    status = wave247.get_status()
    assert status["event_count"] == 0
    assert not status["is_blocked"]
