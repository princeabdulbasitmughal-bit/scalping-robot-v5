"""
tests/test_batch234.py
-----------------------
Unit test suite for Batch 234:
- Wave 234: Top-of-Book Queue Replenishment Latency Blowout Guard
- Wave 235: Multi-Scale Trade Volume Volatility Shock & Volume Clustering Guard

Verifies touch depth replenishment latency blowout, unreplenished void timeouts,
volume variance CV shocks, massive block order executions, fail-closed handling, and cooldowns.
"""

import math
import time
import pytest

import wave234_queue_depth_replenishment_latency_guard as wave234
import wave235_trade_volume_volatility_clustering_guard as wave235


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave234.reset()
    wave235.reset()
    yield
    wave234.reset()
    wave235.reset()


# ---------------------------------------------------------------------------
# Wave 234: Queue Depth Replenishment Latency Guard Tests
# ---------------------------------------------------------------------------

def test_wave234_normal_steady_depth_no_block():
    """Steady top-of-book depth without severe drains does not block."""
    assert not wave234.is_entry_blocked()
    assert not wave234.is_blocked()

    t = 1000.0
    for _ in range(12):
        t += 0.2
        wave234.record_touch_depth(20.0, ts=t)

    assert not wave234.is_entry_blocked()
    metrics = wave234.get_latency_metrics()
    assert metrics["mean_depth"] == 20.0
    status = wave234.get_status()
    assert not status["is_blocked"]


def test_wave234_replenishment_latency_blowout_blocks():
    """Slow depth recovery (replenishment latency >= 1.20s) blocks entries for 45s."""
    t = 2000.0
    # Establish baseline of 20.0 lots
    for _ in range(10):
        t += 0.1
        wave234.record_touch_depth(20.0, ts=t)

    # Severe drain to 5.0 lots (<= 50% of 20.0) at t=2001.0
    wave234.record_touch_depth(5.0, ts=t)

    # Restored to 18.0 lots at t=2002.5 (latency = 1.5s >= 1.20s)
    wave234.update(18.0, ts=t + 1.5)

    assert wave234.is_entry_blocked()
    assert wave234.is_blocked()
    metrics = wave234.get_latency_metrics()
    assert metrics["replenish_latency_sec"] >= wave234.MAX_REPLENISH_LATENCY_SEC
    status = wave234.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave234_unreplenished_void_timeout_blocks():
    """Depth lingering in drained state for >= 2.0s triggers void timeout block."""
    t = 3000.0
    for _ in range(10):
        t += 0.1
        wave234.record_touch_depth(20.0, ts=t)

    # Drain to 5.0 lots
    drain_time = t
    wave234.record_touch_depth(5.0, ts=drain_time)

    # 2.2 seconds later, depth is still drained at 6.0 lots
    wave234.record_touch_depth(6.0, ts=drain_time + 2.2)

    assert wave234.is_entry_blocked()
    assert wave234.is_blocked()
    status = wave234.get_status()
    assert status["is_blocked"]


def test_wave234_fast_healthy_recovery_no_block():
    """Rapid depth replenishment (< 0.5s) does not block."""
    t = 4000.0
    for _ in range(10):
        t += 0.1
        wave234.record_touch_depth(20.0, ts=t)

    # Drain to 5.0 lots
    wave234.record_touch_depth(5.0, ts=t)

    # Fast replenishment in 0.2s back to 18.0 lots
    wave234.record_touch_depth(18.0, ts=t + 0.2)

    assert not wave234.is_entry_blocked()


def test_wave234_input_validation_and_reset():
    """Negative depths, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave234.record_touch_depth(True)
    wave234.record_touch_depth(False)
    wave234.record_touch_depth(-10.0)
    wave234.record_touch_depth(float("nan"))
    wave234.record_touch_depth(float("inf"))

    assert not wave234.is_entry_blocked()

    # Trigger block then reset
    t = 5000.0
    for _ in range(10):
        t += 0.1
        wave234.record_touch_depth(20.0, ts=t)
    wave234.record_touch_depth(5.0, ts=t)
    wave234.record_touch_depth(18.0, ts=t + 1.5)
    assert wave234.is_entry_blocked()

    wave234.reset()
    assert not wave234.is_entry_blocked()
    metrics = wave234.get_latency_metrics()
    assert metrics["replenish_latency_sec"] == 0.0
    status = wave234.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 235: Trade Volume Volatility Shock Guard Tests
# ---------------------------------------------------------------------------

def test_wave235_normal_uniform_trade_volumes_no_block():
    """Uniform trade volumes with moderate variance (CV < 2.50) do not block."""
    assert not wave235.is_entry_blocked()
    assert not wave235.is_blocked()

    # 18 trade volumes between 1.0 and 2.5 lots
    volumes = [1.0, 1.5, 2.0, 1.2, 1.8, 2.2, 1.4, 1.6,
               1.5, 2.0, 1.1, 1.9, 2.3, 1.3, 1.7, 2.1, 1.4, 1.8]
    for v in volumes:
        wave235.record_trade_volume(v)

    assert not wave235.is_entry_blocked()
    metrics = wave235.get_volume_metrics()
    assert metrics["volume_cv"] < wave235.MAX_VOLUME_CV
    status = wave235.get_status()
    assert not status["is_blocked"]


def test_wave235_volume_volatility_shock_blocks():
    """Volume variance explosion (CV >= 2.50 with burst ratio >= 4.0x) blocks entries for 45s."""
    # 15 small baseline volumes of 1.0 lot
    for _ in range(15):
        wave235.record_trade_volume(1.0)

    # Massive volume spike: 18.0 lots (burst ratio ~ 8.7x >= 4.0x, CV >= 2.50)
    wave235.update(18.0)

    assert wave235.is_entry_blocked()
    assert wave235.is_blocked()
    metrics = wave235.get_volume_metrics()
    assert metrics["volume_cv"] >= wave235.MAX_VOLUME_CV
    assert metrics["burst_ratio"] >= wave235.MAX_BURST_RATIO
    status = wave235.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave235_massive_single_block_trade_blocks():
    """Single execution volume >= 25.0 lots immediately triggers block cooldown."""
    wave235.record_trade_volume(30.0)

    assert wave235.is_entry_blocked()
    assert wave235.is_blocked()
    status = wave235.get_status()
    assert status["is_blocked"]


def test_wave235_insufficient_samples_no_block():
    """Fewer than MIN_SAMPLES=15 trade volumes without block trade does not trigger CV block."""
    for _ in range(6):
        wave235.record_trade_volume(2.0)

    assert not wave235.is_entry_blocked()
    assert wave235.get_status()["sample_count"] == 6


def test_wave235_input_validation_and_reset():
    """Non-positive volumes, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave235.record_trade_volume(True)
    wave235.record_trade_volume(False)
    wave235.record_trade_volume(-5.0)
    wave235.record_trade_volume(0.0)
    wave235.record_trade_volume(float("nan"))
    wave235.record_trade_volume(float("inf"))

    assert not wave235.is_entry_blocked()

    # Trigger block then reset
    wave235.record_trade_volume(30.0)
    assert wave235.is_entry_blocked()

    wave235.reset()
    assert not wave235.is_entry_blocked()
    metrics = wave235.get_volume_metrics()
    assert metrics["mean_volume"] == 1.0
    status = wave235.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]
