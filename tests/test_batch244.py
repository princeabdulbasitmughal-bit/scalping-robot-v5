"""
tests/test_batch244.py
-----------------------
Unit test suite for Batch 244:
- Wave 254: Order Book Bid-Ask Spread Dynamic Jitter & Bounce Guard
- Wave 255: Microstructure High-Frequency Return Skewness Extreme Guard

Verifies quoted spread dynamic jitter standard deviations, acute spread flapping jumps,
3rd-moment realized return skewness extremes, acute crash skewness, and cooldowns.
"""

import math
import time
import pytest

import wave254_lob_spread_dynamic_jitter_guard as wave254
import wave255_hf_return_skewness_extreme_guard as wave255


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave254.reset()
    wave255.reset()
    yield
    wave254.reset()
    wave255.reset()


# ---------------------------------------------------------------------------
# Wave 254: LOB Spread Dynamic Jitter Guard Tests
# ---------------------------------------------------------------------------

def test_wave254_smooth_spread_no_block():
    """Smooth spread adjustments (low dynamic jitter sigma <= 1.0 bps) do not block."""
    assert not wave254.is_entry_blocked()
    assert not wave254.is_blocked()

    # Steady spread with smooth tiny adjustments: 2.0, 2.1, 2.0, 2.1...
    for i in range(20):
        s = 2.0 if i % 2 == 0 else 2.1
        wave254.record_spread(spread_bps=s)

    assert not wave254.is_entry_blocked()
    metrics = wave254.get_jitter_metrics()
    assert metrics["jitter_volatility_bps"] < 1.00
    status = wave254.get_status()
    assert not status["is_blocked"]
    assert status["sample_count"] >= 15


def test_wave254_spread_jitter_explosion_blocks():
    """Severe spread jitter explosion (sigma(delta S) >= 2.50 bps on N >= 15) blocks entries for 45s."""
    # Alternating spread between 1.0 bps and 5.0 bps -> delta S alternates between +4.0 and -4.0 bps
    # Standard deviation of +/-4.0 bps is ~4.1 bps >= 2.50 bps
    for i in range(18):
        s = 1.0 if i % 2 == 0 else 5.0
        wave254.record_spread(spread_bps=s)

    assert wave254.is_entry_blocked()
    assert wave254.is_blocked()
    metrics = wave254.get_jitter_metrics()
    assert metrics["jitter_volatility_bps"] >= wave254.MAX_SPREAD_JITTER
    status = wave254.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave254_acute_spread_flapping_jump_blocks():
    """Acute spread flapping jump (|delta S| >= 5.00 bps) immediately blocks entries for 45s."""
    wave254.record_spread(spread_bps=2.0)
    # Sudden explosion to 7.5 bps -> delta = 5.5 bps >= 5.00 bps
    wave254.update(bid_or_spread=7.5)

    assert wave254.is_entry_blocked()
    assert wave254.is_blocked()
    metrics = wave254.get_jitter_metrics()
    assert abs(metrics["latest_spread_delta"]) >= wave254.MAX_ACUTE_SPREAD_JUMP
    status = wave254.get_status()
    assert status["is_blocked"]


def test_wave254_insufficient_samples_no_block():
    """Fewer than MIN_SAMPLES=15 transitions without acute jump does not trigger jitter block."""
    for i in range(8):
        wave254.record_spread(spread_bps=1.0 if i % 2 == 0 else 4.0)

    assert not wave254.is_entry_blocked()
    assert wave254.get_status()["sample_count"] == 7  # 8 quotes = 7 deltas


def test_wave254_input_validation_and_reset():
    """Crossed quotes (bid >= ask), non-positive prices, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave254.record_quote(2000.5, 2000.0)  # crossed
    wave254.record_quote(-2000.0, 2001.0)
    wave254.record_quote(True, 2001.0)
    wave254.record_spread(float("nan"))
    wave254.record_spread(float("inf"))

    assert not wave254.is_entry_blocked()
    assert wave254.get_status()["sample_count"] == 0

    # Trigger block then reset
    wave254.record_spread(2.0)
    wave254.record_spread(8.0)
    assert wave254.is_entry_blocked()

    wave254.reset()
    assert not wave254.is_entry_blocked()
    status = wave254.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 255: Microstructure High-Frequency Return Skewness Extreme Guard Tests
# ---------------------------------------------------------------------------

def test_wave255_symmetric_returns_no_block():
    """Symmetric tick returns (|S_k| <= 1.0) do not block."""
    assert not wave255.is_entry_blocked()
    assert not wave255.is_blocked()

    # Balanced oscillations: +0.5, -0.5 bps
    sym = [0.5, -0.5] * 11  # 22 ticks
    for r in sym:
        wave255.record_return(return_bps=r)

    assert not wave255.is_entry_blocked()
    metrics = wave255.get_skewness_metrics()
    assert abs(metrics["skewness"]) < 1.0
    status = wave255.get_status()
    assert not status["is_blocked"]
    assert status["sample_count"] == 22


def test_wave255_skewness_extreme_blocks():
    """Severe return skewness extreme (|S_k| >= 2.20 on sigma >= 0.60 bps) blocks entries for 45s."""
    # 20 ticks: nineteen small positive drifts (+0.3 bps), one crash drop (-5.0 bps)
    # Skewness ~ -3.8 <= -2.20, sigma ~ 1.15 >= 0.60
    crash = [0.3] * 19 + [-5.0]
    for r in crash:
        wave255.update(price_or_return=r, is_return=True)

    assert wave255.is_entry_blocked()
    assert wave255.is_blocked()
    metrics = wave255.get_skewness_metrics()
    assert abs(metrics["skewness"]) >= wave255.MAX_SKEWNESS
    assert metrics["volatility_bps"] >= wave255.MIN_VOLATILITY_BPS
    status = wave255.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave255_acute_crash_skewness_blocks():
    """Acute crash skewness (|S_k| >= 3.00 on sigma >= 1.00 bps) blocks entries for 45s."""
    # Nineteen +0.2 bps and one severe flash drop of -6.0 bps -> Skewness = -4.13, sigma = 1.35
    crash = [0.2] * 19 + [-6.0]
    for r in crash:
        wave255.record_return(return_bps=r)

    assert wave255.is_entry_blocked()
    assert wave255.is_blocked()
    metrics = wave255.get_skewness_metrics()
    assert abs(metrics["skewness"]) >= wave255.ACUTE_SKEWNESS
    assert metrics["volatility_bps"] >= wave255.ACUTE_VOLATILITY_BPS
    status = wave255.get_status()
    assert status["is_blocked"]


def test_wave255_insufficient_samples_no_block():
    """Fewer than MIN_SAMPLES=20 returns does not evaluate or trigger block."""
    crash = [0.2] * 9 + [-6.0]  # 10 returns (< 20)
    for r in crash:
        wave255.record_return(return_bps=r)

    assert not wave255.is_entry_blocked()
    status = wave255.get_status()
    assert status["sample_count"] == 10
    assert not status["is_blocked"]


def test_wave255_input_validation_and_reset():
    """Non-positive prices, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave255.record_price(-2000.0)
    wave255.record_price(True)
    wave255.record_return(float("nan"))
    wave255.record_return(float("inf"))

    assert not wave255.is_entry_blocked()
    assert wave255.get_status()["sample_count"] == 0

    # Trigger block then reset
    for r in [0.2] * 19 + [-6.0]:
        wave255.record_return(r)
    assert wave255.is_entry_blocked()

    wave255.reset()
    assert not wave255.is_entry_blocked()
    status = wave255.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]
