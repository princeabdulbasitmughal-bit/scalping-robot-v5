"""
tests/test_batch232.py
-----------------------
Unit test suite for Batch 232:
- Wave 230: Quote Life Dispersion & Transient Cancellation Uniformity Guard
- Wave 231: LOB Liquidity Replenishment Asymmetry & Replenishment Deficit Slope Guard

Verifies robotic quote cancellation uniformity, sub-30ms blitz streaks, post-sweep
replenishment slope asymmetry, bilateral liquidity drought, fail-closed assertions, and cooldowns.
"""

import math
import time
import pytest

import wave230_quote_life_dispersion_uniformity_guard as wave230
import wave231_lob_replenishment_asymmetry_slope_guard as wave231


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave230.reset()
    wave231.reset()
    yield
    wave230.reset()
    wave231.reset()


# ---------------------------------------------------------------------------
# Wave 230: Quote Life Dispersion Uniformity Guard Tests
# ---------------------------------------------------------------------------

def test_wave230_normal_variable_lifespans_no_block():
    """Natural heterogeneous quote lifespans (mean >= 200ms, CV > 0.15) do not block."""
    assert not wave230.is_entry_blocked()
    assert not wave230.is_blocked()

    # 18 varied lifespans
    lifespans = [120.0, 350.0, 500.0, 80.0, 750.0, 220.0, 410.0, 600.0,
                 150.0, 320.0, 480.0, 90.0, 680.0, 290.0, 510.0, 390.0]
    for l in lifespans:
        wave230.record_quote_lifespan(l)

    assert not wave230.is_entry_blocked()
    metrics = wave230.get_dispersion_metrics()
    assert metrics["mean_lifespan_ms"] > wave230.MAX_MEAN_LIFESPAN_MS
    assert metrics["lifespan_cv"] > wave230.MIN_LIFESPAN_CV
    status = wave230.get_status()
    assert not status["is_blocked"]


def test_wave230_rigid_clockwork_uniformity_blocks():
    """Robotic uniform cancellation lifespans (mean <= 120ms, CV <= 0.15) block entries for 45s."""
    # 16 cancellations with rigid clockwork lifespan of ~80ms (+- 0.5ms)
    for i in range(16):
        life = 80.0 + (0.5 if i % 2 == 0 else -0.5)
        wave230.update(life)

    assert wave230.is_entry_blocked()
    assert wave230.is_blocked()
    metrics = wave230.get_dispersion_metrics()
    assert metrics["mean_lifespan_ms"] <= wave230.MAX_MEAN_LIFESPAN_MS
    assert metrics["lifespan_cv"] <= wave230.MIN_LIFESPAN_CV
    status = wave230.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave230_sub_30ms_blitz_streak_blocks():
    """Streak of >= 8 consecutive sub-30ms cancellations triggers immediate blitz block."""
    for _ in range(8):
        wave230.record_quote_lifespan(20.0)

    assert wave230.is_entry_blocked()
    assert wave230.is_blocked()
    status = wave230.get_status()
    assert status["is_blocked"]
    assert status["blitz_streak"] >= wave230.MIN_BLITZ_STREAK


def test_wave230_insufficient_samples_no_block():
    """Fewer than MIN_SAMPLES=15 lifespans without blitz streak does not trigger CV block."""
    for _ in range(8):
        wave230.record_quote_lifespan(80.0)

    assert not wave230.is_entry_blocked()
    assert wave230.get_status()["sample_count"] == 8


def test_wave230_input_validation_and_reset():
    """Negative lifespans, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave230.record_quote_lifespan(True)
    wave230.record_quote_lifespan(False)
    wave230.record_quote_lifespan(-100.0)
    wave230.record_quote_lifespan(float("nan"))
    wave230.record_quote_lifespan(float("inf"))

    assert not wave230.is_entry_blocked()

    # Trigger block then reset
    for _ in range(8):
        wave230.record_quote_lifespan(15.0)
    assert wave230.is_entry_blocked()

    wave230.reset()
    assert not wave230.is_entry_blocked()
    metrics = wave230.get_dispersion_metrics()
    assert metrics["blitz_streak"] == 0.0
    status = wave230.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 231: LOB Liquidity Replenishment Asymmetry Guard Tests
# ---------------------------------------------------------------------------

def test_wave231_balanced_two_sided_replenishment_no_block():
    """Symmetric replenishment (A_replenish < 8.0x) does not block."""
    assert not wave231.is_entry_blocked()
    assert not wave231.is_blocked()

    # Both sides replenish 8.0 lots in 1.0s -> 8.0 lots/sec each
    wave231.record_replenishment(bid_lots=8.0, ask_lots=8.0, dt_sec=1.0)

    assert not wave231.is_entry_blocked()
    metrics = wave231.get_replenishment_metrics()
    assert metrics["asymmetry_ratio"] == 1.0
    status = wave231.get_status()
    assert not status["is_blocked"]


def test_wave231_severe_replenishment_asymmetry_blocks():
    """Severe replenishment asymmetry (ratio >= 8.0x with dominant >= 10.0 and lagging <= 1.0) blocks entries."""
    # Bid replenishes 15.0 lots in 1.0s (15.0 lots/s), Ask replenishes 0.5 lots (0.5 lots/s)
    # Ratio = 15.0 / 0.5 = 30.0x >= 8.0x
    wave231.update(bid_lots=15.0, ask_lots=0.5, dt_sec=1.0)

    assert wave231.is_entry_blocked()
    assert wave231.is_blocked()
    metrics = wave231.get_replenishment_metrics()
    assert metrics["asymmetry_ratio"] >= wave231.MAX_REPLENISH_ASYMMETRY
    status = wave231.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave231_bilateral_replenishment_drought_blocks():
    """Bilateral post-sweep drought (both rates <= 0.20 lots/s with dt >= 1.0s) blocks entries."""
    # Both sides fail to replenish: 0.10 lots in 1.0s -> 0.10 lots/s each
    wave231.record_replenishment(bid_lots=0.10, ask_lots=0.10, dt_sec=1.0)

    assert wave231.is_entry_blocked()
    assert wave231.is_blocked()
    status = wave231.get_status()
    assert status["is_blocked"]


def test_wave231_moderate_asymmetry_below_threshold_no_block():
    """Moderate replenishment asymmetry below threshold does not block."""
    # Dominant = 8.0 lots/s (< 10.0), lagging = 3.0 lots/s (> 1.0)
    wave231.record_replenishment(bid_lots=8.0, ask_lots=3.0, dt_sec=1.0)

    assert not wave231.is_entry_blocked()


def test_wave231_input_validation_and_reset():
    """Negative volumes, zero/negative dt, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave231.record_replenishment(True, 5.0, 1.0)
    wave231.record_replenishment(5.0, False, 1.0)
    wave231.record_replenishment(-5.0, 5.0, 1.0)
    wave231.record_replenishment(5.0, -5.0, 1.0)
    wave231.record_replenishment(5.0, 5.0, 0.0)
    wave231.record_replenishment(5.0, 5.0, -1.0)
    wave231.record_replenishment(float("nan"), 5.0, 1.0)
    wave231.record_replenishment(5.0, float("inf"), 1.0)

    assert not wave231.is_entry_blocked()

    # Trigger block then reset
    wave231.record_replenishment(15.0, 0.5, 1.0)
    assert wave231.is_entry_blocked()

    wave231.reset()
    assert not wave231.is_entry_blocked()
    metrics = wave231.get_replenishment_metrics()
    assert metrics["asymmetry_ratio"] == 1.0
    status = wave231.get_status()
    assert not status["is_blocked"]
