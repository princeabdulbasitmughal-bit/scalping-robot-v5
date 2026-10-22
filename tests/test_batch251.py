"""
test_batch251.py
----------------
Unit test suite for Batch 251:
- wave268_lob_depth_decay_curvature_guard.py (Wave 268: Order Book Depth Decay Curvature & Convexity Guard)
- wave269_trade_price_impact_asymmetry_guard.py (Wave 269: Trade Price Impact Asymmetry & Adverse Selection Drift Guard)
"""

import math
import pytest
import time

import wave268_lob_depth_decay_curvature_guard as w268
import wave269_trade_price_impact_asymmetry_guard as w269


# ---------------------------------------------------------------------------
# Wave 268: LOB Depth Decay Curvature Guard Tests
# ---------------------------------------------------------------------------

def test_wave268_healthy_cushion_no_block():
    """Healthy order book with deep outer cushion does not trigger block."""
    w268.reset()
    assert not w268.is_entry_blocked()
    assert not w268.is_blocked()

    # Top depth 4.0 lots, deep depth 12.0 lots -> cushion ratio = 3.0
    for i in range(15):
        w268.record_depth_levels(4.0, 12.0, ts=1000.0 + i)
        assert not w268.is_entry_blocked()

    metrics = w268.get_curvature_metrics()
    assert metrics["mean_cushion_ratio"] >= 2.0
    assert not metrics["is_blocked"]


def test_wave268_depth_cushion_collapse_blocks():
    """Persistent depth cushion ratio <= 0.65 with vulnerable top depth <= 4.0 lots triggers block."""
    w268.reset()
    assert not w268.is_entry_blocked()

    # Top depth 3.0 lots, deep depth 1.5 lots -> cushion ratio = 0.50 (<= 0.65)
    for i in range(12):
        w268.record_depth_levels(3.0, 1.5, ts=2000.0 + i)

    assert w268.is_entry_blocked()
    assert w268.is_blocked()

    metrics = w268.get_curvature_metrics()
    assert metrics["mean_cushion_ratio"] <= 0.65
    assert metrics["is_blocked"] is True


def test_wave268_acute_outer_depth_vanishing_blocks():
    """Acute outer depth vanishing (cushion <= 0.20 and deep <= 1.0 lot) triggers block."""
    w268.reset()
    assert not w268.is_entry_blocked()

    # Top depth 4.0 lots, deep depth 0.50 lots -> cushion ratio = 0.50 / 4.0 = 0.125 (<= 0.20)
    w268.record_depth_levels(4.0, 0.50, ts=3000.0)
    assert w268.is_entry_blocked()
    assert w268.is_blocked()


def test_wave268_insufficient_samples_no_block():
    """Fewer than 12 samples without acute vanishing does not trip condition 1."""
    w268.reset()
    assert not w268.is_entry_blocked()

    # Ingest only 6 samples of low cushion with deep depth > 1.0 lot (e.g. 1.5 lots)
    for i in range(6):
        w268.record_depth_levels(3.0, 1.5, ts=4000.0 + i)

    assert not w268.is_entry_blocked()


def test_wave268_input_validation_and_reset():
    """Invalid depth inputs are rejected and reset restores normal state."""
    w268.reset()

    # Booleans and invalid values rejected
    w268.record_depth_levels(True, 10.0)  # type: ignore
    w268.record_depth_levels(5.0, False)  # type: ignore
    w268.record_depth_levels(-2.0, 10.0)
    w268.record_depth_levels(5.0, float("nan"))
    w268.record_curvature(float("inf"))
    w268.update(True)  # type: ignore
    assert not w268.is_entry_blocked()

    # Trip block and reset
    w268.record_curvature(0.10)
    assert w268.is_entry_blocked()

    w268.reset()
    assert not w268.is_entry_blocked()
    status = w268.get_status()
    assert status["is_blocked"] is False


# ---------------------------------------------------------------------------
# Wave 269: Trade Price Impact Asymmetry Guard Tests
# ---------------------------------------------------------------------------

def test_wave269_symmetric_price_impact_no_block():
    """Symmetric buy and sell price impact produces low asymmetry and no block."""
    w269.reset()
    assert not w269.is_entry_blocked()
    assert not w269.is_blocked()

    # Equal buy and sell impacts of 1.2 bps
    for i in range(8):
        w269.record_trade_impact(1, 1.2)
        w269.record_trade_impact(-1, 1.2)
        assert not w269.is_entry_blocked()

    metrics = w269.get_impact_metrics()
    assert metrics["asymmetry_ratio"] < 0.10
    assert not metrics["is_blocked"]


def test_wave269_severe_price_impact_asymmetry_blocks():
    """Impact asymmetry >= 0.70 with combined impact >= 2.00 bps over 12 samples triggers block."""
    w269.reset()
    assert not w269.is_entry_blocked()

    # Buy impact = 4.0 bps, Sell impact = 0.50 bps
    # Comb = (4.0 + 0.5) / 2 = 2.25 bps (>= 2.00 bps)
    # Asymmetry = 3.5 / 4.5 = 0.778 (>= 0.70)
    for _ in range(6):
        w269.record_trade_impact(1, 4.0)
        w269.record_trade_impact(-1, 0.5)

    assert w269.is_entry_blocked()
    assert w269.is_blocked()

    metrics = w269.get_impact_metrics()
    assert metrics["asymmetry_ratio"] >= 0.70
    assert metrics["is_blocked"] is True


def test_wave269_acute_single_sided_impact_shock_blocks():
    """Single trade impact >= 4.50 bps triggers acute shock block."""
    w269.reset()
    assert not w269.is_entry_blocked()

    # Single buy order sweeps through book for 5.0 bps impact
    w269.record_trade_impact(1, 5.0)
    assert w269.is_entry_blocked()
    assert w269.is_blocked()


def test_wave269_insufficient_total_samples_no_block():
    """Fewer than 12 total trade samples does not trip asymmetry condition."""
    w269.reset()
    assert not w269.is_entry_blocked()

    # Only 4 samples with high asymmetry
    w269.record_trade_impact(1, 4.0)
    w269.record_trade_impact(1, 4.0)
    w269.record_trade_impact(-1, 0.5)
    w269.record_trade_impact(-1, 0.5)
    assert not w269.is_entry_blocked()


def test_wave269_input_validation_and_reset():
    """Invalid trade impact inputs are rejected and reset restores normal state."""
    w269.reset()

    # Booleans, zero signs, negative impact rejected
    w269.record_trade_impact(True, 2.0)  # type: ignore
    w269.record_trade_impact(1, False)  # type: ignore
    w269.record_trade_impact(0, 2.0)
    w269.record_trade_impact(1, -2.0)
    w269.record_trade_impact(1, float("nan"))
    w269.record_asymmetry(float("inf"))
    w269.update(True)  # type: ignore
    assert not w269.is_entry_blocked()

    # Trip block and reset
    w269.record_trade_impact(1, 4.80)
    assert w269.is_entry_blocked()

    w269.reset()
    assert not w269.is_entry_blocked()
    status = w269.get_status()
    assert status["is_blocked"] is False
