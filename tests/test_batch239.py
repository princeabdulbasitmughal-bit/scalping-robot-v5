"""
tests/test_batch239.py
-----------------------
Unit test suite for Batch 239:
- Wave 244: Level 2 Depth Imbalance Acceleration & Flank Exhaustion Guard
- Wave 245: Microstructure High-Frequency Variance Ratio Non-Random Walk Guard

Verifies order book depth imbalance acceleration, flank depletion collapses,
Lo-MacKinlay Variance Ratio non-random walk regimes (trending drift vs whiplash chop), and cooldowns.
"""

import math
import time
import pytest

import wave244_lob_depth_imbalance_acceleration_guard as wave244
import wave245_hf_variance_ratio_guard as wave245


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave244.reset()
    wave245.reset()
    yield
    wave244.reset()
    wave245.reset()


# ---------------------------------------------------------------------------
# Wave 244: Depth Imbalance Acceleration & Flank Exhaustion Guard Tests
# ---------------------------------------------------------------------------

def test_wave244_balanced_depths_no_block():
    """Symmetric, balanced depth levels (|I_depth| <= 0.30, smooth adjustments) do not block."""
    assert not wave244.is_entry_blocked()
    assert not wave244.is_blocked()

    # Balanced book with 5.0 lots each side
    wave244.record_depths(bid_depth_lots=5.0, ask_depth_lots=5.0)

    assert not wave244.is_entry_blocked()
    metrics = wave244.get_imbalance_metrics()
    assert metrics["depth_imbalance"] == 0.0
    status = wave244.get_status()
    assert not status["is_blocked"]


def test_wave244_imbalance_acceleration_blocks():
    """Rapid depth shift triggering acceleration (|a_imb| >= 0.60 on |I| >= 0.70) blocks entries for 45s."""
    # Step 1: Start at balanced state I = 0.0, v = 0.0
    wave244.record_imbalance(0.0)
    # Step 2: Gentle step to I = 0.10 -> v = 0.10, a = 0.10
    wave244.record_imbalance(0.10)
    # Step 3: Violent leap to I = 0.85 -> v = 0.75, a = 0.75 - 0.10 = 0.65 >= 0.60
    wave244.update(0.85)

    assert wave244.is_entry_blocked()
    assert wave244.is_blocked()
    metrics = wave244.get_imbalance_metrics()
    assert abs(metrics["imbalance_acceleration"]) >= wave244.MAX_ACCELERATION
    assert abs(metrics["depth_imbalance"]) >= wave244.MIN_IMBALANCE_THRESHOLD
    status = wave244.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave244_flank_exhaustion_blocks():
    """Flank exhaustion collapse (min flank <= 0.50 lots while dominant flank >= 8.0 lots) blocks entries for 45s."""
    # Bid depth collapses to 0.30 lots while Ask depth is 10.0 lots
    wave244.record_depths(bid_depth_lots=0.30, ask_depth_lots=10.0)

    assert wave244.is_entry_blocked()
    assert wave244.is_blocked()
    status = wave244.get_status()
    assert status["is_blocked"]
    assert status["bid_depth"] <= wave244.MIN_FLANK_DEPTH
    assert status["ask_depth"] >= wave244.DOMINANT_FLANK_DEPTH


def test_wave244_static_imbalance_ceiling_blocks():
    """Extreme static imbalance (|I| >= 0.90 with total depth >= 5.0 lots) blocks entries for 45s."""
    # Bid depth = 9.5 lots, Ask depth = 0.50 lots -> Imbalance = 9.0 / 10.0 = 0.90
    wave244.record_depths(bid_depth_lots=9.6, ask_depth_lots=0.6)  # tot = 10.2, imb = 9.0 / 10.2 ~ 0.88
    # Direct high static imbalance
    wave244.record_imbalance(0.92, total_depth=12.0)

    assert wave244.is_entry_blocked()
    status = wave244.get_status()
    assert status["is_blocked"]


def test_wave244_input_validation_and_reset():
    """Negative depths, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave244.record_depths(-5.0, 10.0)
    wave244.record_depths(10.0, -5.0)
    wave244.record_depths(True, 10.0)
    wave244.record_imbalance(float("nan"))
    wave244.record_imbalance(float("inf"))

    assert not wave244.is_entry_blocked()

    # Trigger block then reset
    wave244.record_depths(0.20, 12.0)
    assert wave244.is_entry_blocked()

    wave244.reset()
    assert not wave244.is_entry_blocked()
    status = wave244.get_status()
    assert status["depth_imbalance"] == 0.0
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 245: Microstructure High-Frequency Variance Ratio Guard Tests
# ---------------------------------------------------------------------------

def test_wave245_diffusive_walk_no_block():
    """Diffusive random walk returns (VR(4) ~ 1.0) do not block."""
    assert not wave245.is_entry_blocked()
    assert not wave245.is_blocked()

    # Uncorrelated diffusive returns from Gaussian walk
    diffusive = [
        -0.57, -0.32, 2.22, -0.49, -1.44, 0.3, 0.16, 0.69,
        -0.37, 1.49, 0.62, 2.59, 0.59, 0.28, 1.45, 0.91,
        -0.76, 0.84, -0.65, 1.26, -0.56, 0.39, -0.77, 0.36,
        1.43, 1.19, -0.63, -1.34, 0.74, -0.67, -0.76, 0.72
    ]
    for r in diffusive:
        wave245.record_tick_return(return_bps=r)

    assert not wave245.is_entry_blocked()
    metrics = wave245.get_variance_ratio_metrics()
    assert 0.60 < metrics["variance_ratio"] < 1.40
    status = wave245.get_status()
    assert not status["is_blocked"]
    assert status["sample_count"] == 32


def test_wave245_persistent_trend_drift_blocks():
    """Persistent trending sweep with positive serial correlation (VR(4) >= 1.85 with sigma_1 >= 0.50) blocks entries for 45s."""
    # Autocorrelated momentum series with persistent directional drift
    trend = [
        1.0, 1.2, 1.5, 1.8, 1.2, 1.4, 1.6, 2.0,
        0.5, 0.8, 1.0, 1.2, 1.5, 1.3, 1.1, 1.4,
        1.8, 2.0, 2.2, 2.5, 2.1, 1.9, 2.3, 2.4,
        1.5, 1.7, 1.8, 2.0, 2.2, 2.1, 2.3, 2.5
    ]
    for r in trend:
        wave245.update(price_or_return=r, is_return=True)

    assert wave245.is_entry_blocked()
    assert wave245.is_blocked()
    metrics = wave245.get_variance_ratio_metrics()
    assert metrics["variance_ratio"] >= wave245.MAX_VARIANCE_RATIO
    assert metrics["sigma_1_bps"] >= wave245.MIN_VOLATILITY_BPS
    status = wave245.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave245_whiplash_bounce_blocks():
    """Toxic ping-pong whiplash with extreme negative serial correlation (VR(4) <= 0.30 with sigma_1 >= 0.80) blocks entries for 45s."""
    # Alternating returns: +1.5, -1.5, +1.5, -1.5 ...
    # Sum over 4 ticks is identically 0.0 -> var(4) = 0.0 -> VR(4) = 0.0 <= 0.30
    whiplash = [1.5, -1.5] * 16  # 32 ticks
    for r in whiplash:
        wave245.record_tick_return(return_bps=r)

    assert wave245.is_entry_blocked()
    assert wave245.is_blocked()
    metrics = wave245.get_variance_ratio_metrics()
    assert metrics["variance_ratio"] <= wave245.MIN_VARIANCE_RATIO
    assert metrics["sigma_1_bps"] >= wave245.WHIPLASH_VOLATILITY_BPS
    status = wave245.get_status()
    assert status["is_blocked"]


def test_wave245_insufficient_samples_no_block():
    """Fewer than MIN_SAMPLES=24 ticks does not evaluate or trigger block."""
    for r in [1.5, -1.5] * 6:  # 12 ticks (< 24)
        wave245.record_tick_return(return_bps=r)

    assert not wave245.is_entry_blocked()
    status = wave245.get_status()
    assert status["sample_count"] == 12
    assert not status["is_blocked"]


def test_wave245_input_validation_and_reset():
    """Non-positive prices, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave245.record_price(-2000.0)
    wave245.record_price(True)
    wave245.record_tick_return(float("nan"))
    wave245.record_tick_return(float("inf"))

    assert not wave245.is_entry_blocked()
    assert wave245.get_status()["sample_count"] == 0

    # Trigger block then reset
    for r in [1.5, -1.5] * 14:
        wave245.record_tick_return(r)
    assert wave245.is_entry_blocked()

    wave245.reset()
    assert not wave245.is_entry_blocked()
    status = wave245.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]
