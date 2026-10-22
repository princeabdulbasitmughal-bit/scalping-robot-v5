"""
test_batch249.py
----------------
Unit test suite for Batch 249:
- wave264_lob_queue_depletion_hazard_rate_guard.py (Wave 264: LOB Queue Depletion Survival Hazard Rate Guard)
- wave265_hf_volume_sync_asymmetry_vpin_guard.py (Wave 265: High-Frequency Volume-Synchronized Probability of Toxicity Guard)
"""

import math
import pytest
import time

import wave264_lob_queue_depletion_hazard_rate_guard as w264
import wave265_hf_volume_sync_asymmetry_vpin_guard as w265


# ---------------------------------------------------------------------------
# Wave 264: LOB Queue Depletion Hazard Rate Guard Tests
# ---------------------------------------------------------------------------

def test_wave264_stable_depth_no_block():
    """Stable queue depth with zero depletions does not trigger hazard rate block."""
    w264.reset()
    assert not w264.is_entry_blocked()
    assert not w264.is_blocked()

    t = 1000.0
    for i in range(10):
        # 5.0 bid, 5.0 ask = 10.0 lots constant
        w264.record_depth(5.0, 5.0, ts=t + i * 1.0)
        assert not w264.is_entry_blocked()

    metrics = w264.get_hazard_metrics()
    assert metrics["depletion_events_count"] == 0
    assert metrics["hazard_rate"] == 0.0
    assert not metrics["is_blocked"]


def test_wave264_elevated_hazard_rate_blocks():
    """Depletion hazard rate >= 0.25 events/s over rolling window triggers block."""
    w264.reset()
    assert not w264.is_entry_blocked()

    t = 2000.0
    # Ingest 8 depletion events (60% drop each) within 20s (rate = 8/30 = 0.267 >= 0.25)
    for i in range(8):
        # Normal duration > 0.20s to avoid acute vaporization trigger
        w264.record_depletion_event(0.60, duration_sec=1.5, ts=t + i * 2.0)

    assert w264.is_entry_blocked()
    assert w264.is_blocked()

    metrics = w264.get_hazard_metrics()
    assert metrics["hazard_rate"] >= 0.25
    assert metrics["is_blocked"] is True


def test_wave264_acute_instantaneous_vaporization_blocks():
    """Acute depth drop >= 80% within <= 0.20s triggers block."""
    w264.reset()
    assert not w264.is_entry_blocked()

    t = 3000.0
    # Initial depth: 10.0 lots (5 bid, 5 ask)
    w264.record_depth(5.0, 5.0, ts=t)
    assert not w264.is_entry_blocked()

    # 100ms later (t+0.10s), depth vaporizes to 1.0 lot (0.5 bid, 0.5 ask) -> 90% drop
    w264.record_depth(0.5, 0.5, ts=t + 0.10)
    assert w264.is_entry_blocked()
    assert w264.is_blocked()


def test_wave264_insufficient_events_no_block():
    """Fewer than 5 depletion events does not trip rolling hazard rate condition."""
    w264.reset()
    assert not w264.is_entry_blocked()

    t = 4000.0
    # Only 3 events
    for i in range(3):
        w264.record_depletion_event(0.60, duration_sec=1.0, ts=t + i * 2.0)

    assert not w264.is_entry_blocked()


def test_wave264_input_validation_and_reset():
    """Invalid inputs are rejected and reset restores normal state."""
    w264.reset()

    # Booleans and invalid values rejected
    w264.record_depth(True, 5.0)  # type: ignore
    w264.record_depth(5.0, False)  # type: ignore
    w264.record_depth(-1.0, 5.0)
    w264.record_depth(5.0, float("nan"))
    w264.record_depletion_event(float("inf"))
    w264.update(True)  # type: ignore
    assert not w264.is_entry_blocked()

    # Trip block and reset
    w264.record_depletion_event(0.90, duration_sec=0.10, ts=100.0)
    assert w264.is_entry_blocked()

    w264.reset()
    assert not w264.is_entry_blocked()
    status = w264.get_status()
    assert status["is_blocked"] is False


# ---------------------------------------------------------------------------
# Wave 265: High-Frequency VPIN Guard Tests
# ---------------------------------------------------------------------------

def test_wave265_balanced_volume_flow_no_block():
    """Balanced alternating buy/sell volume produces low VPIN and no block."""
    w265.reset()
    assert not w265.is_entry_blocked()
    assert not w265.is_blocked()

    # Ingest 10 balanced buckets (2.5 buy, 2.5 sell per 5.0 lot bucket)
    t = 1000.0
    for i in range(10):
        w265.record_trade(1, 2.5, ts=t + i * 2.0)
        w265.record_trade(-1, 2.5, ts=t + i * 2.0 + 1.0)
        assert not w265.is_entry_blocked()

    metrics = w265.get_vpin_metrics()
    assert metrics["vpin"] < 0.20
    assert not metrics["is_blocked"]


def test_wave265_elevated_vpin_blocks():
    """Rolling VPIN >= 0.75 across 10 completed buckets triggers block."""
    w265.reset()
    assert not w265.is_entry_blocked()

    # Ingest direct VPIN
    w265.record_vpin(0.85, bucket_imbalance=0.80, sample_count=10)
    assert w265.is_entry_blocked()
    assert w265.is_blocked()

    metrics = w265.get_vpin_metrics()
    assert metrics["vpin"] >= 0.75
    assert metrics["is_blocked"] is True


def test_wave265_acute_single_bucket_toxicity_blocks():
    """Single bucket with >= 95% imbalance completed in <= 1.0s triggers block."""
    w265.reset()
    assert not w265.is_entry_blocked()

    t = 2000.0
    # Ingest 5.0 lots of pure buy volume in 0.5s
    w265.record_trade(1, 5.0, ts=t)
    assert w265.is_entry_blocked()
    assert w265.is_blocked()

    metrics = w265.get_vpin_metrics()
    assert metrics["latest_bucket_imbalance"] >= 0.95
    assert metrics["is_blocked"] is True


def test_wave265_insufficient_buckets_no_block():
    """Fewer than 10 completed buckets without acute spike does not trip rolling VPIN."""
    w265.reset()
    assert not w265.is_entry_blocked()

    # Direct ingestion with only 6 buckets
    w265.record_vpin(0.90, bucket_imbalance=0.50, sample_count=6)
    assert not w265.is_entry_blocked()


def test_wave265_input_validation_and_reset():
    """Invalid trade inputs are rejected and reset restores normal state."""
    w265.reset()

    # Booleans, zero signs, negative volume rejected
    w265.record_trade(True, 5.0)  # type: ignore
    w265.record_trade(1, False)  # type: ignore
    w265.record_trade(0, 5.0)
    w265.record_trade(1, -5.0)
    w265.record_trade(1, float("nan"))
    w265.record_vpin(float("inf"))
    w265.update(True)  # type: ignore
    assert not w265.is_entry_blocked()

    # Trip block and reset
    w265.record_vpin(0.80, bucket_imbalance=0.98, sample_count=10)
    assert w265.is_entry_blocked()

    w265.reset()
    assert not w265.is_entry_blocked()
    status = w265.get_status()
    assert status["is_blocked"] is False
