"""
test_batch255.py
----------------
Unit test suite for Batch 255 (2,800+ Tests Milestone!):
- wave276_lob_cross_level_liquidity_gradient_guard.py (Wave 276: LOB Cross-Level Liquidity Gradient Asymmetry Guard)
- wave277_trade_arrival_self_excitation_hawkes_branching_guard.py (Wave 277: High-Frequency Hawkes Process Branching Ratio Guard)
"""

import math
import pytest
import time

import wave276_lob_cross_level_liquidity_gradient_guard as w276
import wave277_trade_arrival_self_excitation_hawkes_branching_guard as w277


# ---------------------------------------------------------------------------
# Wave 276: LOB Cross-Level Liquidity Gradient Guard Tests
# ---------------------------------------------------------------------------

def test_wave276_symmetric_gradients_no_block():
    """Symmetric liquidity gradients on both sides do not trigger block."""
    w276.reset()
    assert not w276.is_entry_blocked()
    assert not w276.is_blocked()

    # 3.0 lots/pt bid, 3.0 lots/pt ask -> asymmetry = 0.0
    for i in range(15):
        w276.record_level_gradients(3.0, 3.0, total_depth=10.0, ts=1000.0 + i)
        assert not w276.is_entry_blocked()

    metrics = w276.get_gradient_metrics()
    assert abs(metrics["mean_asymmetry"]) < 0.10
    assert not metrics["is_blocked"]


def test_wave276_severe_gradient_asymmetry_blocks():
    """Gradient asymmetry >= 0.78 with depth >= 6.0 lots over 12 samples triggers block."""
    w276.reset()
    assert not w276.is_entry_blocked()

    # Grad bid = 9.0, Grad ask = 1.0 -> asym = 8.0 / 10.0 = 0.80 (>= 0.78)
    for i in range(12):
        w276.record_level_gradients(9.0, 1.0, total_depth=8.0, ts=2000.0 + i)

    assert w276.is_entry_blocked()
    assert w276.is_blocked()

    metrics = w276.get_gradient_metrics()
    assert abs(metrics["mean_asymmetry"]) >= 0.78
    assert metrics["is_blocked"] is True


def test_wave276_acute_flank_gradient_freeze_blocks():
    """Acute flank gradient freeze (one <= 0.10, other >= 8.0) triggers block."""
    w276.reset()
    assert not w276.is_entry_blocked()

    # Bid gradient flattened to 0.05, Ask gradient heavy at 9.0
    w276.record_level_gradients(0.05, 9.0, total_depth=9.5)
    assert w276.is_entry_blocked()
    assert w276.is_blocked()


def test_wave276_insufficient_samples_no_block():
    """Fewer than 12 samples without acute freeze does not trip condition 1."""
    w276.reset()
    assert not w276.is_entry_blocked()

    # Ingest only 6 samples with asymmetry = 0.82
    for _ in range(6):
        w276.record_gradient_asymmetry(0.82, total_depth=10.0)

    assert not w276.is_entry_blocked()


def test_wave276_input_validation_and_reset():
    """Invalid gradient inputs are rejected and reset restores normal state."""
    w276.reset()

    # Booleans and negative/invalid numbers rejected
    w276.record_level_gradients(True, 3.0)  # type: ignore
    w276.record_level_gradients(3.0, False)  # type: ignore
    w276.record_level_gradients(-2.0, 3.0)
    w276.record_level_gradients(3.0, float("nan"))
    w276.record_gradient_asymmetry(float("inf"))
    w276.update(True)  # type: ignore
    assert not w276.is_entry_blocked()

    # Trip block and reset
    w276.record_level_gradients(0.05, 8.5)
    assert w276.is_entry_blocked()

    w276.reset()
    assert not w276.is_entry_blocked()
    status = w276.get_status()
    assert status["is_blocked"] is False


# ---------------------------------------------------------------------------
# Wave 277: Hawkes Branching Ratio Criticality Guard Tests
# ---------------------------------------------------------------------------

def test_wave277_subcritical_arrivals_no_block():
    """Subcritical durations (> 100 ms) yield zero branching ratio and no block."""
    w277.reset()
    assert not w277.is_entry_blocked()
    assert not w277.is_blocked()

    for i in range(25):
        w277.record_duration(120.0 + (i % 4) * 20.0)
        assert not w277.is_entry_blocked()

    metrics = w277.get_branching_metrics()
    assert metrics["branching_ratio"] == 0.0
    assert not metrics["is_blocked"]


def test_wave277_supercritical_branching_blocks():
    """Endogenous branching ratio >= 0.80 over 25 trades triggers block."""
    w277.reset()
    assert not w277.is_entry_blocked()

    # Ingest 25 trades with 22 having duration <= 50ms (e.g. 40ms) and 3 having 200ms
    # Branching ratio = 22 / 25 = 0.88 (>= 0.80)
    for i in range(25):
        dur = 40.0 if i < 22 else 200.0
        w277.record_duration(dur)

    assert w277.is_entry_blocked()
    assert w277.is_blocked()

    metrics = w277.get_branching_metrics()
    assert metrics["branching_ratio"] >= 0.80
    assert metrics["is_blocked"] is True


def test_wave277_acute_cascade_streak_blocks():
    """12 consecutive supercritical cascade trades (<= 30.0 ms) triggers block."""
    w277.reset()
    assert not w277.is_entry_blocked()

    # First trade normal
    w277.record_duration(250.0)
    assert not w277.is_entry_blocked()

    # 12 consecutive trades with 20ms duration
    for _ in range(12):
        w277.record_duration(20.0)

    assert w277.is_entry_blocked()
    assert w277.is_blocked()

    metrics = w277.get_branching_metrics()
    assert metrics["current_streak"] >= 12
    assert metrics["is_blocked"] is True


def test_wave277_insufficient_trades_no_block():
    """Fewer than 25 trades without acute cascade does not trip condition 1."""
    w277.reset()
    assert not w277.is_entry_blocked()

    # Direct ingestion with only 15 trades
    w277.record_branching(0.90, sample_count=15)
    assert not w277.is_entry_blocked()


def test_wave277_input_validation_and_reset():
    """Invalid duration inputs are rejected and reset restores normal state."""
    w277.reset()

    # Booleans and negative/invalid numbers rejected
    w277.record_duration(True)  # type: ignore
    w277.record_duration(False)  # type: ignore
    w277.record_duration(-15.0)
    w277.record_duration(0.0)
    w277.record_duration(float("nan"))
    w277.record_branching(float("inf"))
    w277.update(True)  # type: ignore
    assert not w277.is_entry_blocked()

    # Trip block and reset
    for _ in range(12):
        w277.record_duration(15.0)
    assert w277.is_entry_blocked()

    w277.reset()
    assert not w277.is_entry_blocked()
    status = w277.get_status()
    assert status["is_blocked"] is False
