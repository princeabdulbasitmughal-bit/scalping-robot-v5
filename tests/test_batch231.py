"""
tests/test_batch231.py
-----------------------
Unit test suite for Batch 231:
- Wave 228: Realized Kurtosis Shock & Heavy-Tail Jump Blowup Guard
- Wave 229: LOB Level Depth Concentration & Liquidity Herfindahl Deficit Guard

Verifies 4th-moment realized kurtosis fat-tail explosions, multi-level depth concentration
Herfindahl index HHI, outer book air pockets, fail-closed assertions, and cooldowns.
"""

import math
import time
import pytest

import wave228_realized_kurtosis_heavy_tail_guard as wave228
import wave229_lob_depth_concentration_hhi_guard as wave229


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave228.reset()
    wave229.reset()
    yield
    wave228.reset()
    wave229.reset()


# ---------------------------------------------------------------------------
# Wave 228: Realized Kurtosis Heavy Tail Guard Tests
# ---------------------------------------------------------------------------

def test_wave228_mesokurtic_normal_returns_no_block():
    """Mesokurtic return distributions (K ~ 3.0 < 7.0) with moderate sigma do not block."""
    assert not wave228.is_entry_blocked()
    assert not wave228.is_blocked()

    p = 2000.0
    wave228.record_price(p)
    # 18 returns alternating between +0.40 and -0.40 (2.0 bps)
    for i in range(18):
        p += (0.40 if i % 2 == 0 else -0.40)
        wave228.record_price(p)

    assert not wave228.is_entry_blocked()
    metrics = wave228.get_kurtosis_metrics()
    assert metrics["realized_kurtosis"] < wave228.MAX_KURTOSIS
    status = wave228.get_status()
    assert not status["is_blocked"]


def test_wave228_realized_kurtosis_heavy_tail_blocks():
    """Severe leptokurtic outlier shock (K >= 7.00 with sigma >= 1.0 bps) blocks entries for 45s."""
    p = 2000.0
    wave228.record_price(p)

    # 15 small baseline returns around 0.10 - 0.20 (0.5 - 1.0 bps)
    for _ in range(15):
        p += 0.20
        wave228.record_price(p)

    # Now an extreme outlier return shock (+3.00 on 2000 = 15.0 bps)
    p += 3.00
    wave228.update(p)

    assert wave228.is_entry_blocked()
    assert wave228.is_blocked()
    metrics = wave228.get_kurtosis_metrics()
    assert metrics["realized_kurtosis"] >= wave228.MAX_KURTOSIS
    assert metrics["sigma_bps"] >= wave228.MIN_SIGMA_BPS
    status = wave228.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave228_insufficient_sigma_floor_no_block():
    """Kurtosis spikes below MIN_SIGMA_BPS (1.0 bps) do not block on dead tick noise."""
    p = 2000.0
    wave228.record_price(p)
    # 16 tiny returns of 0.001 (0.005 bps)
    for _ in range(16):
        p += 0.001
        wave228.record_price(p)

    assert not wave228.is_entry_blocked()
    metrics = wave228.get_kurtosis_metrics()
    assert metrics["sigma_bps"] < wave228.MIN_SIGMA_BPS


def test_wave228_insufficient_samples_no_block():
    """Fewer than MIN_SAMPLES=15 returns does not trigger kurtosis block."""
    p = 2000.0
    wave228.record_price(p)
    for _ in range(8):
        p += 1.00
        wave228.record_price(p)

    assert not wave228.is_entry_blocked()
    assert wave228.get_status()["sample_count"] == 8


def test_wave228_input_validation_and_reset():
    """Non-positive prices, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave228.record_price(True)
    wave228.record_price(False)
    wave228.record_price(-2000.0)
    wave228.record_price(0.0)
    wave228.record_price(float("nan"))
    wave228.record_price(float("inf"))

    assert not wave228.is_entry_blocked()

    # Trigger block then reset
    p = 2000.0
    wave228.record_price(p)
    for _ in range(15):
        p += 0.20
        wave228.record_price(p)
    wave228.record_price(p + 3.00)
    assert wave228.is_entry_blocked()

    wave228.reset()
    assert not wave228.is_entry_blocked()
    metrics = wave228.get_kurtosis_metrics()
    assert metrics["realized_kurtosis"] == 3.0
    status = wave228.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 229: LOB Level Depth Concentration HHI Guard Tests
# ---------------------------------------------------------------------------

def test_wave229_distributed_multi_level_depth_no_block():
    """Balanced order book depth across levels (HHI ~ 0.20) does not block."""
    assert not wave229.is_entry_blocked()
    assert not wave229.is_blocked()

    # 5 levels each with 5.0 lots (total 25.0 lots) -> HHI = 5 * (0.2)^2 = 0.20
    levels = [5.0, 5.0, 5.0, 5.0, 5.0]
    wave229.record_depth_levels(levels)

    assert not wave229.is_entry_blocked()
    metrics = wave229.get_concentration_metrics()
    assert metrics["depth_hhi"] < 0.25
    assert metrics["touch_dominance_ratio"] == 0.20
    status = wave229.get_status()
    assert not status["is_blocked"]


def test_wave229_extreme_hhi_depth_concentration_blocks():
    """Severe depth concentration (HHI >= 0.75 with total depth >= 5.0) blocks entries for 45s."""
    # Level 1 has 18.0 lots out of 20.0 lots (90% at touch) -> HHI >= 0.81 >= 0.75
    levels = [18.0, 1.0, 0.5, 0.3, 0.2]
    wave229.update(levels)

    assert wave229.is_entry_blocked()
    assert wave229.is_blocked()
    metrics = wave229.get_concentration_metrics()
    assert metrics["depth_hhi"] >= wave229.MAX_DEPTH_HHI
    assert metrics["touch_dominance_ratio"] >= wave229.MAX_TOUCH_DOMINANCE
    status = wave229.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave229_two_tier_touch_outer_air_pocket_blocks():
    """Two-tier distribution with touch dominance >= 85% blocks entries."""
    # Touch = 20.0 lots, outer levels = 1.0 lot (total 21.0 lots) -> 95.2% dominance
    wave229.record_book_depth_distribution(touch_depth=20.0, outer_depth=1.0)

    assert wave229.is_entry_blocked()
    assert wave229.is_blocked()
    metrics = wave229.get_concentration_metrics()
    assert metrics["touch_dominance_ratio"] >= wave229.MAX_TOUCH_DOMINANCE


def test_wave229_low_total_depth_below_floor_no_block():
    """Concentrated depth below MIN_TOTAL_DEPTH (5.0 lots) does not trigger block on thin penny size."""
    # 90% concentration but total depth is only 1.0 lot
    levels = [0.90, 0.05, 0.05]
    wave229.record_depth_levels(levels)

    assert not wave229.is_entry_blocked()
    metrics = wave229.get_concentration_metrics()
    assert metrics["total_depth"] < wave229.MIN_TOTAL_DEPTH


def test_wave229_input_validation_and_reset():
    """Negative depths, booleans, NaNs, Infs, and empty lists are rejected, and reset restores clean state."""
    wave229.record_depth_levels([])
    wave229.record_depth_levels([True, 5.0])
    wave229.record_depth_levels([5.0, False])
    wave229.record_depth_levels([-5.0, 5.0])
    wave229.record_depth_levels([float("nan"), 5.0])
    wave229.record_depth_levels([5.0, float("inf")])

    assert not wave229.is_entry_blocked()

    # Trigger block then reset
    wave229.record_depth_levels([20.0, 1.0])
    assert wave229.is_entry_blocked()

    wave229.reset()
    assert not wave229.is_entry_blocked()
    metrics = wave229.get_concentration_metrics()
    assert metrics["depth_hhi"] == 0.20
    status = wave229.get_status()
    assert status["total_depth"] == 0.0
    assert not status["is_blocked"]
