"""
test_batch253.py
----------------
Unit test suite for Batch 253:
- wave272_lob_spread_asymmetry_drift_guard.py (Wave 272: LOB Bid-Ask Half-Spread Dynamic Asymmetry & Skew Drift Guard)
- wave273_trade_size_pareto_tail_alpha_guard.py (Wave 273: Trade Size Power-Law Tail Index (Pareto Alpha) Fragility Guard)
"""

import math
import pytest
import time

import wave272_lob_spread_asymmetry_drift_guard as w272
import wave273_trade_size_pareto_tail_alpha_guard as w273


# ---------------------------------------------------------------------------
# Wave 272: LOB Half-Spread Asymmetry Guard Tests
# ---------------------------------------------------------------------------

def test_wave272_centered_quotes_no_block():
    """Quotes centered symmetrically around rolling fair price do not trigger block."""
    w272.reset()
    assert not w272.is_entry_blocked()
    assert not w272.is_blocked()

    # Ingest 15 balanced quotes around 2400.0: bid 2399.90, ask 2400.10
    for i in range(15):
        w272.record_quote(2399.90, 2400.10, fair_price=2400.00, ts=1000.0 + i)
        assert not w272.is_entry_blocked()

    metrics = w272.get_asymmetry_metrics()
    assert abs(metrics["mean_asymmetry"]) < 0.10
    assert not metrics["is_blocked"]


def test_wave272_persistent_spread_asymmetry_blocks():
    """Asymmetry ratio >= 0.75 with spread >= 2.50 bps over 12 samples triggers block."""
    w272.reset()
    assert not w272.is_entry_blocked()

    # Fair price = 2000.0, Bid = 1999.00 (d_bid = 1.0), Ask = 2000.10 (d_ask = 0.10)
    # Spread = 1.10 pts on 2000 (~5.5 bps >= 2.50 bps)
    # Asymmetry = (1.0 - 0.10) / (1.10) = 0.818 (>= 0.75)
    for i in range(12):
        w272.record_quote(1999.00, 2000.10, fair_price=2000.00, ts=2000.0 + i)

    assert w272.is_entry_blocked()
    assert w272.is_blocked()

    metrics = w272.get_asymmetry_metrics()
    assert abs(metrics["mean_asymmetry"]) >= 0.75
    assert metrics["is_blocked"] is True


def test_wave272_acute_asymmetric_quote_shift_blocks():
    """Acute asymmetric quote shift >= 0.90 with spread >= 3.50 bps triggers block."""
    w272.reset()
    assert not w272.is_entry_blocked()

    # Direct ingestion of acute shift
    w272.record_spread_asymmetry(0.95, spread_bps=4.00)
    assert w272.is_entry_blocked()
    assert w272.is_blocked()

    metrics = w272.get_asymmetry_metrics()
    assert abs(metrics["latest_asymmetry"]) >= 0.90
    assert metrics["is_blocked"] is True


def test_wave272_insufficient_samples_no_block():
    """Fewer than 12 samples without acute shift does not trip condition 1."""
    w272.reset()
    assert not w272.is_entry_blocked()

    # Ingest only 6 samples with asymmetry = 0.80 and spread = 2.80 bps
    for _ in range(6):
        w272.record_spread_asymmetry(0.80, spread_bps=2.80)

    assert not w272.is_entry_blocked()


def test_wave272_input_validation_and_reset():
    """Invalid quote inputs are rejected and reset restores normal state."""
    w272.reset()

    # Crossed quote rejected
    w272.record_quote(2001.0, 2000.0)
    # Booleans and invalid values rejected
    w272.record_quote(True, 2000.5)  # type: ignore
    w272.record_quote(2000.0, False)  # type: ignore
    w272.record_quote(-10.0, 2000.5)
    w272.record_quote(2000.0, float("nan"))
    w272.record_spread_asymmetry(float("inf"))
    w272.update(True)  # type: ignore
    assert not w272.is_entry_blocked()

    # Trip block and reset
    w272.record_spread_asymmetry(0.95, spread_bps=5.0)
    assert w272.is_entry_blocked()

    w272.reset()
    assert not w272.is_entry_blocked()
    status = w272.get_status()
    assert status["is_blocked"] is False


# ---------------------------------------------------------------------------
# Wave 273: Trade Size Pareto Tail Alpha Guard Tests
# ---------------------------------------------------------------------------

def test_wave273_moderate_trade_sizes_no_block():
    """Moderate trade sizes (0.5 to 1.5 lots) maintain high Pareto alpha and no block."""
    w273.reset()
    assert not w273.is_entry_blocked()
    assert not w273.is_blocked()

    for i in range(15):
        w273.record_trade_size(0.50 + (i % 5) * 0.20)
        assert not w273.is_entry_blocked()

    metrics = w273.get_tail_metrics()
    assert metrics["pareto_alpha"] >= 1.50
    assert not metrics["is_blocked"]


def test_wave273_pareto_alpha_collapse_blocks():
    """Heavy tail collapse with alpha <= 1.15 and top size >= 8.0 lots triggers block."""
    w273.reset()
    assert not w273.is_entry_blocked()

    # Direct ingestion of low alpha
    w273.record_alpha(1.05, top_size=12.0, sample_count=10)
    assert w273.is_entry_blocked()
    assert w273.is_blocked()

    metrics = w273.get_tail_metrics()
    assert metrics["pareto_alpha"] <= 1.15
    assert metrics["is_blocked"] is True


def test_wave273_acute_whale_block_blocks():
    """Acute single whale block trade >= 20.0 lots triggers block."""
    w273.reset()
    assert not w273.is_entry_blocked()

    w273.record_trade_size(25.0)
    assert w273.is_entry_blocked()
    assert w273.is_blocked()

    metrics = w273.get_tail_metrics()
    assert metrics["latest_single_size"] >= 20.0
    assert metrics["is_blocked"] is True


def test_wave273_insufficient_tail_samples_no_block():
    """Fewer than 10 samples without acute whale does not trip condition 1."""
    w273.reset()
    assert not w273.is_entry_blocked()

    # Direct ingestion with only 5 samples
    w273.record_alpha(0.90, top_size=10.0, sample_count=5)
    assert not w273.is_entry_blocked()


def test_wave273_input_validation_and_reset():
    """Invalid trade size inputs are rejected and reset restores normal state."""
    w273.reset()

    # Booleans and negative/invalid numbers rejected
    w273.record_trade_size(True)  # type: ignore
    w273.record_trade_size(False)  # type: ignore
    w273.record_trade_size(-5.0)
    w273.record_trade_size(0.0)
    w273.record_trade_size(float("nan"))
    w273.record_alpha(float("inf"))
    w273.update(True)  # type: ignore
    assert not w273.is_entry_blocked()

    # Trip block and reset
    w273.record_trade_size(22.0)
    assert w273.is_entry_blocked()

    w273.reset()
    assert not w273.is_entry_blocked()
    status = w273.get_status()
    assert status["is_blocked"] is False
