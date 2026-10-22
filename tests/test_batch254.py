"""
test_batch254.py
----------------
Unit test suite for Batch 254:
- wave274_lob_flow_depth_correlation_guard.py (Wave 274: LOB Order Flow Imbalance & Level-1 Depth Correlation Breakdown Guard)
- wave275_trade_arrival_interevent_entropy_burst_guard.py (Wave 275: Trade Inter-Event Duration Multi-Scale Entropy & Burstiness Guard)
"""

import math
import pytest
import time

import wave274_lob_flow_depth_correlation_guard as w274
import wave275_trade_arrival_interevent_entropy_burst_guard as w275


# ---------------------------------------------------------------------------
# Wave 274: LOB Flow-Depth Correlation Breakdown Guard Tests
# ---------------------------------------------------------------------------

def test_wave274_correlated_flow_depth_no_block():
    """Conforming OFI and depth delta (strong positive correlation) do not trigger block."""
    w274.reset()
    assert not w274.is_entry_blocked()
    assert not w274.is_blocked()

    # Ingest 15 conforming events: positive OFI corresponds to positive depth delta
    for i in range(16):
        val = 1.0 + (i % 4) * 0.5
        w274.record_flow_and_depth(val, val * 0.8)
        assert not w274.is_entry_blocked()

    metrics = w274.get_correlation_metrics()
    assert metrics["flow_depth_correlation"] >= 0.50
    assert not metrics["is_blocked"]


def test_wave274_flow_depth_correlation_breakdown_blocks():
    """Flow-depth correlation breakdown <= 0.15 with active flow >= 10.0 lots triggers block."""
    w274.reset()
    assert not w274.is_entry_blocked()

    # Ingest 16 alternating uncorrelated/anticorrelated events without hitting acute product (-20)
    # OFI = +1.5, Depth = -1.5 -> product = -2.25 (well above -20)
    for i in range(16):
        x = 1.5 if i % 2 == 0 else -1.5
        y = -1.2 if i % 2 == 0 else 1.2
        w274.record_flow_and_depth(x, y)

    assert w274.is_entry_blocked()
    assert w274.is_blocked()

    metrics = w274.get_correlation_metrics()
    assert metrics["flow_depth_correlation"] <= 0.15
    assert metrics["is_blocked"] is True


def test_wave274_acute_opposing_flow_mismatch_blocks():
    """Acute opposing flow mismatch (product <= -20.0 lots^2) triggers block."""
    w274.reset()
    assert not w274.is_entry_blocked()

    # OFI = +6.0 lots (aggressive buying), Depth delta = -5.0 lots -> product = -30.0 (<= -20.0)
    w274.record_flow_and_depth(6.0, -5.0)
    assert w274.is_entry_blocked()
    assert w274.is_blocked()

    metrics = w274.get_correlation_metrics()
    assert metrics["latest_product"] <= -20.0
    assert metrics["is_blocked"] is True


def test_wave274_insufficient_samples_no_block():
    """Fewer than 15 observations without acute mismatch does not trip condition 1."""
    w274.reset()
    assert not w274.is_entry_blocked()

    # Only 8 samples with poor correlation
    for i in range(8):
        w274.record_flow_and_depth(1.0 if i % 2 == 0 else -1.0, -0.8 if i % 2 == 0 else 0.8)

    assert not w274.is_entry_blocked()


def test_wave274_input_validation_and_reset():
    """Invalid flow inputs are rejected and reset restores normal state."""
    w274.reset()

    # Booleans and invalid values rejected
    w274.record_flow_and_depth(True, 5.0)  # type: ignore
    w274.record_flow_and_depth(5.0, False)  # type: ignore
    w274.record_flow_and_depth(float("nan"), 5.0)
    w274.record_correlation(float("inf"))
    w274.update(True)  # type: ignore
    assert not w274.is_entry_blocked()

    # Trip block and reset
    w274.record_correlation(-0.50, active_volume=20.0)
    assert w274.is_entry_blocked()

    w274.reset()
    assert not w274.is_entry_blocked()
    status = w274.get_status()
    assert status["is_blocked"] is False


# ---------------------------------------------------------------------------
# Wave 275: Trade Arrival Inter-Event Burstiness Guard Tests
# ---------------------------------------------------------------------------

def test_wave275_poisson_durations_no_block():
    """Poisson exponential durations with moderate burstiness do not trigger block."""
    w275.reset()
    assert not w275.is_entry_blocked()
    assert not w275.is_blocked()

    # 25 steady durations around 250ms
    for i in range(25):
        w275.record_duration(200.0 + (i % 5) * 25.0)
        assert not w275.is_entry_blocked()

    metrics = w275.get_burstiness_metrics()
    assert metrics["burstiness"] < 0.30
    assert not metrics["is_blocked"]


def test_wave275_extreme_burstiness_blocks():
    """Goh-Barabasi burstiness >= 0.65 with mean duration <= 150 ms triggers block."""
    w275.reset()
    assert not w275.is_entry_blocked()

    # Direct ingestion of extreme burstiness
    w275.record_burstiness(0.72, mean_duration_ms=80.0, sample_count=20)
    assert w275.is_entry_blocked()
    assert w275.is_blocked()

    metrics = w275.get_burstiness_metrics()
    assert metrics["burstiness"] >= 0.65
    assert metrics["is_blocked"] is True


def test_wave275_acute_rapid_cluster_streak_blocks():
    """6 consecutive ultra-rapid trades (<= 15.0 ms) triggers acute streak block."""
    w275.reset()
    assert not w275.is_entry_blocked()

    # First trade normal
    w275.record_duration(200.0)
    assert not w275.is_entry_blocked()

    # 6 consecutive ultra-rapid arrivals (10ms each)
    for _ in range(6):
        w275.record_duration(10.0)

    assert w275.is_entry_blocked()
    assert w275.is_blocked()

    metrics = w275.get_burstiness_metrics()
    assert metrics["current_streak"] >= 6
    assert metrics["is_blocked"] is True


def test_wave275_insufficient_trades_no_block():
    """Fewer than 20 trades without acute cluster does not trip condition 1."""
    w275.reset()
    assert not w275.is_entry_blocked()

    # Direct ingestion with only 12 samples
    w275.record_burstiness(0.80, mean_duration_ms=60.0, sample_count=12)
    assert not w275.is_entry_blocked()


def test_wave275_input_validation_and_reset():
    """Invalid duration inputs are rejected and reset restores normal state."""
    w275.reset()

    # Booleans and negative/invalid numbers rejected
    w275.record_duration(True)  # type: ignore
    w275.record_duration(False)  # type: ignore
    w275.record_duration(-20.0)
    w275.record_duration(0.0)
    w275.record_duration(float("nan"))
    w275.record_burstiness(float("inf"))
    w275.update(True)  # type: ignore
    assert not w275.is_entry_blocked()

    # Trip block and reset
    for _ in range(6):
        w275.record_duration(12.0)
    assert w275.is_entry_blocked()

    w275.reset()
    assert not w275.is_entry_blocked()
    status = w275.get_status()
    assert status["is_blocked"] is False
