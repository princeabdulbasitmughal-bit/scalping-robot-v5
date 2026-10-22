"""
tests/test_batch229.py
-----------------------
Unit test suite for Batch 229:
- Wave 224: LOB Queue First-Passage Depletion Hazard Guard
- Wave 225: Multi-Scale Realized Volatility Ratio & Fractal Dimension Shift Guard

Verifies order book queue aggressive absorption, runaway depletion velocity,
multiscale variance scaling across super-diffusive and sub-diffusive regimes,
fail-closed assertions, and monotonic cooldown timers.
"""

import math
import time
import pytest

import wave224_queue_first_passage_depletion_hazard_guard as wave224
import wave225_multiscale_fractal_variance_ratio_guard as wave225


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave224.reset()
    wave225.reset()
    yield
    wave224.reset()
    wave225.reset()


# ---------------------------------------------------------------------------
# Wave 224: Queue First-Passage Depletion Hazard Guard Tests
# ---------------------------------------------------------------------------

def test_wave224_normal_queue_absorption_no_block():
    """Normal queue absorption (< 85%) with steady standing depth does not block."""
    assert not wave224.is_entry_blocked()
    assert not wave224.is_blocked()

    t = 1000.0
    for _ in range(5):
        t += 0.5
        wave224.record_queue_state(standing_depth=20.0, aggr_fill_vol=1.0, ts=t)

    assert not wave224.is_entry_blocked()
    metrics = wave224.get_depletion_metrics()
    assert metrics["absorption_ratio"] < wave224.MAX_ABSORPTION_RATIO
    status = wave224.get_status()
    assert not status["is_blocked"]


def test_wave224_aggressive_absorption_shock_blocks():
    """Aggressive order flow consuming >= 85% of standing depth blocks entries for 45s."""
    t = 2000.0
    # Initial standing depth = 10.0 lots
    wave224.record_queue_state(standing_depth=10.0, aggr_fill_vol=0.0, ts=t)

    # 3 aggressive sweep fills totaling 9.0 lots (90% absorption >= 85%)
    for _ in range(3):
        t += 0.2
        wave224.update(standing_depth=7.0, aggr_fill_vol=3.0, ts=t)

    assert wave224.is_entry_blocked()
    assert wave224.is_blocked()
    metrics = wave224.get_depletion_metrics()
    assert metrics["absorption_ratio"] >= wave224.MAX_ABSORPTION_RATIO
    status = wave224.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave224_runaway_depletion_velocity_blocks():
    """Rapid queue burn rate (depletion velocity >= 12.0 lots/sec) blocks entries."""
    t = 3000.0
    # Standing depth drops from 25.0 to 10.0 lots (15.0 lots drop) in 0.5s -> 30.0 lots/sec >= 12.0
    wave224.record_queue_state(standing_depth=25.0, aggr_fill_vol=0.0, ts=t)
    wave224.record_queue_state(standing_depth=10.0, aggr_fill_vol=0.0, ts=t + 0.5)

    assert wave224.is_entry_blocked()
    assert wave224.is_blocked()
    metrics = wave224.get_depletion_metrics()
    assert metrics["depletion_velocity"] >= wave224.MAX_DEPLETION_VELOCITY


def test_wave224_input_validation_and_fail_closed():
    """Negative values, booleans, NaNs, and Infs are safely rejected without throwing."""
    wave224.record_queue_state(standing_depth=True, aggr_fill_vol=1.0)
    wave224.record_queue_state(standing_depth=10.0, aggr_fill_vol=False)
    wave224.record_queue_state(standing_depth=-10.0, aggr_fill_vol=1.0)
    wave224.record_queue_state(standing_depth=10.0, aggr_fill_vol=-1.0)
    wave224.record_queue_state(standing_depth=float("nan"), aggr_fill_vol=1.0)
    wave224.record_queue_state(standing_depth=10.0, aggr_fill_vol=float("inf"))

    assert not wave224.is_entry_blocked()
    assert wave224.get_status()["event_count"] == 0


def test_wave224_reset_and_status():
    """Reset clears event deque, metrics, and active cooldown blocks."""
    t = 4000.0
    wave224.record_queue_state(standing_depth=10.0, aggr_fill_vol=0.0, ts=t)
    for _ in range(3):
        t += 0.2
        wave224.record_queue_state(standing_depth=7.0, aggr_fill_vol=3.0, ts=t)
    assert wave224.is_entry_blocked()

    wave224.reset()
    assert not wave224.is_entry_blocked()
    metrics = wave224.get_depletion_metrics()
    assert metrics["absorption_ratio"] == 0.0
    status = wave224.get_status()
    assert status["event_count"] == 0
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 225: Multiscale Fractal Variance Ratio Guard Tests
# ---------------------------------------------------------------------------

def test_wave225_normal_brownian_scaling_no_block():
    """Random walk returns with balanced multi-scale variance (S_scale ~ 1.0) do not block."""
    assert not wave225.is_entry_blocked()
    assert not wave225.is_blocked()

    steps = [-0.043, -0.052, -0.033, 0.211, -0.038, -0.449, 0.100, -0.080,
             -0.065, 0.035, 0.070, 0.349, 0.197, 0.033, -0.221, -0.304,
             0.074, 0.393, 0.012, -0.032]
    p = 2000.0
    wave225.record_price(p)
    for s in steps:
        p += s
        wave225.record_price(p)

    assert not wave225.is_entry_blocked()
    metrics = wave225.get_scaling_metrics()
    assert 0.50 <= metrics["scaling_ratio"] <= 1.80
    status = wave225.get_status()
    assert not status["is_blocked"]


def test_wave225_super_diffusive_runaway_trend_blocks():
    """Constructive return compounding in strong trend (S_scale >= 2.20x) blocks entries for 45s."""
    p = 2000.0
    wave225.record_price(p)

    # 20 consecutive unidirectional steps (+0.50 each)
    # Each 4-tick block: sum = 2.00 -> r_4^2 = 4.0. sum of 4 r_1^2 = 4 * 0.25 = 1.0.
    # Scaling ratio = 4.0 / 1.0 = 4.0 >= 2.20!
    for _ in range(20):
        p += 0.50
        wave225.update(p)

    assert wave225.is_entry_blocked()
    assert wave225.is_blocked()
    metrics = wave225.get_scaling_metrics()
    assert metrics["scaling_ratio"] >= wave225.MAX_SCALING_RATIO
    status = wave225.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave225_sub_diffusive_noise_trap_blocks():
    """Destructive return cancellation in bid-ask bounce noise (S_scale <= 0.30) blocks entries."""
    p = 2000.0
    wave225.record_price(p)

    # 20 alternating steps (+0.60, -0.60)
    # Every 4-tick block cancels out completely: r_4 = 0.0 -> RV_4 = 0.0!
    # While RV_1 is large (20 * 0.36 = 7.2 >= 2.0). Scaling ratio = 0.0 <= 0.30.
    for i in range(20):
        p += (0.60 if i % 2 == 0 else -0.60)
        wave225.record_price(p)

    assert wave225.is_entry_blocked()
    metrics = wave225.get_scaling_metrics()
    assert metrics["scaling_ratio"] <= wave225.MIN_SCALING_RATIO


def test_wave225_insufficient_samples_no_block():
    """Fewer than MIN_SAMPLES=16 prices does not trigger block."""
    p = 2000.0
    wave225.record_price(p)
    for _ in range(8):
        p += 0.50
        wave225.record_price(p)

    assert not wave225.is_entry_blocked()
    assert wave225.get_status()["sample_count"] == 9


def test_wave225_input_validation_and_reset():
    """Non-positive prices, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave225.record_price(True)
    wave225.record_price(False)
    wave225.record_price(-2000.0)
    wave225.record_price(0.0)
    wave225.record_price(float("nan"))
    wave225.record_price(float("inf"))

    assert not wave225.is_entry_blocked()

    # Trigger block then reset
    p = 2000.0
    wave225.record_price(p)
    for _ in range(20):
        p += 0.50
        wave225.record_price(p)
    assert wave225.is_entry_blocked()

    wave225.reset()
    assert not wave225.is_entry_blocked()
    metrics = wave225.get_scaling_metrics()
    assert metrics["realized_var_scale1"] == 0.0
    status = wave225.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]
