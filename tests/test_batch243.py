"""
tests/test_batch243.py
-----------------------
Unit test suite for Batch 243:
- Wave 252: Microstructure Trade Size Relative Variance & Stealth Size Guard
- Wave 253: Limit Order Queue Cancellation Asymmetry Velocity Guard

Verifies trade lot size relative dispersion, institutional whale block sweeps,
differential limit order cancellation asymmetry, asymmetry acceleration surges, and cooldowns.
"""

import math
import time
import pytest

import wave252_trade_size_dispersion_stealth_guard as wave252
import wave253_lob_cancellation_asymmetry_velocity_guard as wave253


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave252.reset()
    wave253.reset()
    yield
    wave252.reset()
    wave253.reset()


# ---------------------------------------------------------------------------
# Wave 252: Trade Size Dispersion & Stealth Size Guard Tests
# ---------------------------------------------------------------------------

def test_wave252_compact_sizes_no_block():
    """Compact retail trade volumes (CV <= 1.20, spike ratio < 4.0x) do not block."""
    assert not wave252.is_entry_blocked()
    assert not wave252.is_blocked()

    # Compact trade volumes oscillating around 1.0 lot
    for i in range(16):
        v = 1.0 if i % 2 == 0 else 1.5
        wave252.record_trade_size(volume_lots=v)

    assert not wave252.is_entry_blocked()
    metrics = wave252.get_size_dispersion_metrics()
    assert metrics["size_cv"] < 1.00
    status = wave252.get_status()
    assert not status["is_blocked"]
    assert status["sample_count"] == 16


def test_wave252_size_variance_explosion_blocks():
    """Severe trade size variance explosion (CV >= 2.00 on spike >= 8.0x) blocks entries for 45s."""
    # 15 base trades of 0.5 lots and 1 institutional block of 12.0 lots
    # Median = 0.5, Max = 12.0 -> spike ratio = 12.0 / 0.5 = 24.0x >= 8.0x
    # CV of fifteen 0.5s and one 12.0: mean ~ 1.22, std ~ 2.87 -> CV ~ 2.35 >= 2.00
    for _ in range(15):
        wave252.record_trade_size(0.5)
    wave252.update(12.0)

    assert wave252.is_entry_blocked()
    assert wave252.is_blocked()
    metrics = wave252.get_size_dispersion_metrics()
    assert metrics["size_cv"] >= wave252.MAX_SIZE_CV
    assert metrics["spike_ratio"] >= wave252.MAX_SPIKE_RATIO
    status = wave252.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave252_single_whale_block_blocks():
    """Single massive whale block trade (volume >= 25.0 lots) immediately blocks entries for 45s."""
    wave252.record_trade_size(volume_lots=28.0)

    assert wave252.is_entry_blocked()
    assert wave252.is_blocked()
    metrics = wave252.get_size_dispersion_metrics()
    assert metrics["latest_volume"] >= wave252.MAX_WHALE_SIZE
    status = wave252.get_status()
    assert status["is_blocked"]


def test_wave252_insufficient_samples_no_block():
    """Fewer than MIN_SAMPLES=15 trades without whale block does not trigger CV block."""
    for _ in range(8):
        wave252.record_trade_size(2.0)

    assert not wave252.is_entry_blocked()
    assert wave252.get_status()["sample_count"] == 8


def test_wave252_input_validation_and_reset():
    """Non-positive volumes, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave252.record_trade_size(-5.0)
    wave252.record_trade_size(0.0)
    wave252.record_trade_size(True)
    wave252.record_trade_size(float("nan"))
    wave252.record_trade_size(float("inf"))

    assert not wave252.is_entry_blocked()
    assert wave252.get_status()["sample_count"] == 0

    # Trigger block then reset
    wave252.record_trade_size(30.0)
    assert wave252.is_entry_blocked()

    wave252.reset()
    assert not wave252.is_entry_blocked()
    status = wave252.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 253: Limit Order Queue Cancellation Asymmetry Velocity Guard Tests
# ---------------------------------------------------------------------------

def test_wave253_symmetric_cancellations_no_block():
    """Symmetric cancellation rates (|Delta C| <= 5.0, ratio < 2.5x) do not block."""
    assert not wave253.is_entry_blocked()
    assert not wave253.is_blocked()

    # Balanced cancellations: 5.0 cancels/sec on both sides
    wave253.record_cancellations(bid_cancels=5.0, ask_cancels=5.0)

    assert not wave253.is_entry_blocked()
    metrics = wave253.get_cancellation_asymmetry_metrics()
    assert metrics["net_difference"] == 0.0
    status = wave253.get_status()
    assert not status["is_blocked"]


def test_wave253_cancellation_asymmetry_blocks():
    """Severe directional cancellation asymmetry (|Delta C| >= 15.0 and ratio >= 6.0x) blocks entries for 45s."""
    # Bid cancels = 20.0, Ask cancels = 2.0 -> Diff = 18.0 >= 15.0, Ratio = 10.0x >= 6.0x
    wave253.record_cancellations(bid_cancels=20.0, ask_cancels=2.0)

    assert wave253.is_entry_blocked()
    assert wave253.is_blocked()
    metrics = wave253.get_cancellation_asymmetry_metrics()
    assert abs(metrics["net_difference"]) >= wave253.MAX_NET_CANCEL_RATE
    assert metrics["asymmetry_ratio"] >= wave253.MAX_CANCEL_RATIO
    status = wave253.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave253_asymmetry_velocity_surge_blocks():
    """Acute cancellation asymmetry acceleration surge (|v_asym| >= 12.0 cancels/sec^2) blocks entries for 45s."""
    t0 = 2000.0
    # Step 1: Start symmetric at t0
    wave253.record_cancellations(bid_cancels=5.0, ask_cancels=5.0, ts=t0)
    # Step 2: Sudden violent divergence 0.2s later
    # Bid = 2.0, Ask = 12.0 -> diff = -10.0.
    # Shift = -10.0 in 0.2s -> velocity = -50.0 cancels/sec^2
    wave253.record_cancellations(bid_cancels=2.0, ask_cancels=12.0, ts=t0 + 0.20)

    assert wave253.is_entry_blocked()
    assert wave253.is_blocked()
    metrics = wave253.get_cancellation_asymmetry_metrics()
    assert abs(metrics["asymmetry_velocity"]) >= wave253.MAX_ASYM_ACCELERATION
    status = wave253.get_status()
    assert status["is_blocked"]


def test_wave253_single_cancellation_side_updates():
    """Single-side cancellation updates increment rates and trigger blocks when threshold reached."""
    # Base rates start at 5.0 each side. Add 16.0 to bid side -> 21.0 vs 5.0 -> diff = 16.0 >= 15.0
    # But ratio is 21.0 / 5.0 = 4.2 < 6.0. Add 27.0 to bid side -> 32.0 vs 5.0 -> diff = 27.0, ratio = 6.4 >= 6.0
    wave253.update(32.0)  # alias for record_single_cancellation(side=1, count=32.0)

    assert wave253.is_entry_blocked()
    metrics = wave253.get_cancellation_asymmetry_metrics()
    assert metrics["net_difference"] >= wave253.MAX_NET_CANCEL_RATE


def test_wave253_input_validation_and_reset():
    """Negative rates, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave253.record_cancellations(-5.0, 10.0)
    wave253.record_cancellations(10.0, -5.0)
    wave253.record_cancellations(True, 10.0)
    wave253.record_cancellations(float("nan"), 10.0)
    wave253.record_single_cancellation("invalid", 5.0)

    assert not wave253.is_entry_blocked()

    # Trigger block then reset
    wave253.record_cancellations(25.0, 1.0)
    assert wave253.is_entry_blocked()

    wave253.reset()
    assert not wave253.is_entry_blocked()
    status = wave253.get_status()
    assert status["net_difference"] == 0.0
    assert not status["is_blocked"]
