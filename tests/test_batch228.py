"""
tests/test_batch228.py
-----------------------
Unit test suite for Batch 228:
- Wave 222: LOB Queue Priority Turnover & Order Book Churn Guard
- Wave 223: Cross-Asset Microstructure Correlation Breakdown Guard

Verifies limit order queue turnover churn, rapid queue drain velocity, paired return
correlation inversion/breakdown, fail-closed handling, and monotonic cooldown timers.
"""

import math
import time
import pytest

import wave222_queue_priority_turnover_churn_guard as wave222
import wave223_cross_asset_microstructure_correlation_breakdown_guard as wave223


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave222.reset()
    wave223.reset()
    yield
    wave222.reset()
    wave223.reset()


# ---------------------------------------------------------------------------
# Wave 222: LOB Queue Priority Turnover Churn Guard Tests
# ---------------------------------------------------------------------------

def test_wave222_normal_low_turnover_no_block():
    """Normal queue updates with low turnover ratio (< 4.0x) do not block."""
    assert not wave222.is_entry_blocked()
    assert not wave222.is_blocked()

    t = 1000.0
    for _ in range(5):
        t += 0.5
        wave222.record_queue_update(standing_depth=20.0, added_vol=1.0, cancelled_vol=1.0, ts=t)

    assert not wave222.is_entry_blocked()
    metrics = wave222.get_queue_metrics()
    assert metrics["turnover_ratio"] < wave222.MAX_TURNOVER_RATIO
    status = wave222.get_status()
    assert not status["is_blocked"]


def test_wave222_excessive_queue_turnover_churn_blocks():
    """Heavy queue insertion and cancellation churn (R_turnover >= 4.0x) blocks entries for 45s."""
    t = 2000.0
    # Standing depth = 10.0 lots
    # 5 events within 1.5s each adding 5.0 lots and cancelling 5.0 lots (total churn = 50.0 lots)
    # Turnover ratio = 50.0 / 10.0 = 5.0x >= 4.0x
    for _ in range(5):
        t += 0.25
        wave222.update(standing_depth=10.0, added_vol=5.0, cancelled_vol=5.0, ts=t)

    assert wave222.is_entry_blocked()
    assert wave222.is_blocked()
    metrics = wave222.get_queue_metrics()
    assert metrics["turnover_ratio"] >= wave222.MAX_TURNOVER_RATIO
    status = wave222.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave222_toxic_queue_drain_velocity_blocks():
    """Rapid queue depth evaporation without matching trades (drain >= 8.0 lots/sec) blocks entries."""
    t = 3000.0
    # 15 lots cancelled across 0.5s -> 30.0 lots/sec >= 8.0 lots/sec
    wave222.record_queue_update(standing_depth=25.0, added_vol=0.0, cancelled_vol=7.5, ts=t)
    wave222.record_queue_update(standing_depth=17.5, added_vol=0.0, cancelled_vol=7.5, ts=t + 0.5)

    assert wave222.is_entry_blocked()
    assert wave222.is_blocked()
    metrics = wave222.get_queue_metrics()
    assert metrics["drain_velocity"] >= wave222.MAX_DRAIN_VELOCITY


def test_wave222_input_validation_and_fail_closed():
    """Negative values, booleans, NaNs, and Infs are safely rejected without throwing."""
    wave222.record_queue_update(standing_depth=True, added_vol=1.0, cancelled_vol=1.0)
    wave222.record_queue_update(standing_depth=10.0, added_vol=False, cancelled_vol=1.0)
    wave222.record_queue_update(standing_depth=-10.0, added_vol=1.0, cancelled_vol=1.0)
    wave222.record_queue_update(standing_depth=10.0, added_vol=-1.0, cancelled_vol=1.0)
    wave222.record_queue_update(standing_depth=float("nan"), added_vol=1.0, cancelled_vol=1.0)
    wave222.record_queue_update(standing_depth=10.0, added_vol=1.0, cancelled_vol=float("inf"))

    assert not wave222.is_entry_blocked()
    assert wave222.get_status()["event_count"] == 0


def test_wave222_reset_and_status():
    """Reset clears event deque, metrics, and active cooldown blocks."""
    t = 4000.0
    for _ in range(5):
        t += 0.2
        wave222.record_queue_update(standing_depth=10.0, added_vol=5.0, cancelled_vol=5.0, ts=t)
    assert wave222.is_entry_blocked()

    wave222.reset()
    assert not wave222.is_entry_blocked()
    metrics = wave222.get_queue_metrics()
    assert metrics["turnover_ratio"] == 0.0
    status = wave222.get_status()
    assert status["event_count"] == 0
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 223: Cross-Asset Correlation Breakdown Guard Tests
# ---------------------------------------------------------------------------

def test_wave223_normal_healthy_inverse_correlation_no_block():
    """Normal strong inverse correlation (rho <= -0.50) between target and anchor does not block."""
    assert not wave223.is_entry_blocked()
    assert not wave223.is_blocked()

    p_tgt = 2000.0
    p_anc = 100.0
    wave223.record_prices(p_tgt, p_anc)

    # 18 paired ticks moving inversely (+0.40 tgt, -0.20 anc; then -0.40 tgt, +0.20 anc)
    for i in range(18):
        if i % 2 == 0:
            p_tgt += 0.40
            p_anc -= 0.20
        else:
            p_tgt -= 0.40
            p_anc += 0.20
        wave223.record_prices(p_tgt, p_anc)

    assert not wave223.is_entry_blocked()
    metrics = wave223.get_correlation_metrics()
    assert metrics["correlation_rho"] <= -0.80
    status = wave223.get_status()
    assert not status["is_blocked"]


def test_wave223_correlation_breakdown_inversion_blocks():
    """Severe cross-asset decoupling / inversion (rho >= +0.25) blocks entries for 45s."""
    p_tgt = 2000.0
    p_anc = 100.0
    wave223.record_prices(p_tgt, p_anc)

    # 18 paired ticks moving in lockstep (positive correlation rho ~ +1.0)
    for i in range(18):
        step_tgt = 0.50 if i % 2 == 0 else -0.30
        step_anc = 0.25 if i % 2 == 0 else -0.15
        p_tgt += step_tgt
        p_anc += step_anc
        wave223.update(p_tgt, p_anc)

    assert wave223.is_entry_blocked()
    assert wave223.is_blocked()
    metrics = wave223.get_correlation_metrics()
    assert metrics["correlation_rho"] >= wave223.BREAKDOWN_CORRELATION_THRESHOLD
    status = wave223.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave223_flat_market_below_volatility_floor_no_block():
    """Returns below MIN_VOLATILITY_BPS (0.5 bps) do not trigger correlation evaluation."""
    p_tgt = 2000.0
    p_anc = 100.0
    wave223.record_prices(p_tgt, p_anc)

    # 18 tiny increments (0.001 on 2000 = 0.005 bps)
    for _ in range(18):
        p_tgt += 0.001
        p_anc += 0.001
        wave223.record_prices(p_tgt, p_anc)

    assert not wave223.is_entry_blocked()


def test_wave223_insufficient_samples_no_block():
    """Fewer than MIN_SAMPLES=15 return pairs does not trigger block."""
    p_tgt = 2000.0
    p_anc = 100.0
    wave223.record_prices(p_tgt, p_anc)

    for _ in range(6):
        p_tgt += 0.50
        p_anc += 0.25
        wave223.record_prices(p_tgt, p_anc)

    assert not wave223.is_entry_blocked()
    assert wave223.get_status()["sample_count"] == 6


def test_wave223_input_validation_and_reset():
    """Non-positive prices, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave223.record_prices(True, 100.0)
    wave223.record_prices(2000.0, False)
    wave223.record_prices(-2000.0, 100.0)
    wave223.record_prices(2000.0, -100.0)
    wave223.record_prices(float("nan"), 100.0)
    wave223.record_prices(2000.0, float("inf"))

    assert not wave223.is_entry_blocked()

    # Trigger block then reset
    p_tgt = 2000.0
    p_anc = 100.0
    wave223.record_prices(p_tgt, p_anc)
    for i in range(18):
        p_tgt += (0.50 if i % 2 == 0 else -0.30)
        p_anc += (0.25 if i % 2 == 0 else -0.15)
        wave223.record_prices(p_tgt, p_anc)
    assert wave223.is_entry_blocked()

    wave223.reset()
    assert not wave223.is_entry_blocked()
    metrics = wave223.get_correlation_metrics()
    assert metrics["correlation_rho"] == -0.70
    status = wave223.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]
