"""
test_batch247.py
----------------
Unit test suite for Batch 247:
- wave260_lob_slope_decay_elasticity_guard.py (Wave 260: LOB Slope Decay & Price-Impact Elasticity Guard)
- wave261_trade_clustering_dispersion_entropy_guard.py (Wave 261: Trade Arrival Dispersion & Shannon Entropy Guard)
"""

import math
import pytest
import time

import wave260_lob_slope_decay_elasticity_guard as w260
import wave261_trade_clustering_dispersion_entropy_guard as w261


# ---------------------------------------------------------------------------
# Wave 260: LOB Slope Decay & Price-Impact Elasticity Guard Tests
# ---------------------------------------------------------------------------

def test_wave260_calm_quotes_no_block():
    """Calm quotes with healthy slope and low elasticity do not trigger block."""
    w260.reset()
    assert not w260.is_entry_blocked()
    assert not w260.is_blocked()

    # Quote: bid 2400.0, ask 2400.20 (spread ~0.83 bps), depth 10.0 lots (5 bid, 5 ask)
    # Slope = 10.0 / 0.83 = 12.0 lots/bps (very high)
    for i in range(15):
        w260.record_quote(2400.00, 2400.20, 5.0, 5.0, ts=1000.0 + i)
        assert not w260.is_entry_blocked()

    metrics = w260.get_elasticity_metrics()
    assert metrics["latest_slope"] > 5.0
    assert not metrics["is_blocked"]


def test_wave260_mean_elasticity_persistence_blocks():
    """Mean price-impact elasticity >= 2.20 over 12 samples triggers block."""
    w260.reset()
    assert not w260.is_entry_blocked()

    for _ in range(12):
        w260.record_elasticity(2.80, slope=3.0, spread_bps=1.0)

    assert w260.is_entry_blocked()
    assert w260.is_blocked()

    metrics = w260.get_elasticity_metrics()
    assert metrics["mean_elasticity"] >= 2.20
    assert metrics["is_blocked"] is True


def test_wave260_acute_slope_collapse_blocks():
    """Acute slope <= 0.50 lots/bps with spread >= 2.50 bps triggers block."""
    w260.reset()
    assert not w260.is_entry_blocked()

    # Spread 3.0 bps (on 2000, 3 bps = 0.60): bid 2000.0, ask 2000.60
    # Depth very thin: 0.10 bid, 0.10 ask -> total depth = 0.20 lots
    # Slope = 0.20 / 3.0 = 0.067 lots/bps (far below 0.50 floor)
    w260.record_quote(2000.00, 2000.60, 0.10, 0.10, ts=2000.0)
    assert w260.is_entry_blocked()
    assert w260.is_blocked()


def test_wave260_insufficient_samples_no_block():
    """Fewer than 12 elasticity samples does not trip persistence condition."""
    w260.reset()
    assert not w260.is_entry_blocked()

    # Only 8 samples of high elasticity with normal slope
    for _ in range(8):
        w260.record_elasticity(3.50, slope=4.0, spread_bps=1.0)

    assert not w260.is_entry_blocked()


def test_wave260_input_validation_and_reset():
    """Invalid quote inputs are rejected and reset restores normal state."""
    w260.reset()

    # Crossed quote (bid >= ask) rejected
    w260.record_quote(2001.0, 2000.0, 5.0, 5.0)
    # Booleans and invalid numeric inputs rejected
    w260.record_quote(True, 2000.5, 5.0, 5.0)  # type: ignore
    w260.record_quote(2000.0, False, 5.0, 5.0)  # type: ignore
    w260.record_quote(-2000.0, 2000.5, 5.0, 5.0)
    w260.record_quote(2000.0, 2000.5, -5.0, 5.0)
    w260.record_quote(2000.0, 2000.5, float("nan"), 5.0)
    w260.update(True)  # type: ignore
    assert not w260.is_entry_blocked()

    # Trip block and reset
    w260.record_elasticity(4.0, slope=0.10, spread_bps=4.0)
    assert w260.is_entry_blocked()

    w260.reset()
    assert not w260.is_entry_blocked()
    status = w260.get_status()
    assert status["is_blocked"] is False


# ---------------------------------------------------------------------------
# Wave 261: Trade Arrival Dispersion & Shannon Entropy Guard Tests
# ---------------------------------------------------------------------------

def test_wave261_uniform_trade_dispersion_no_block():
    """Uniformly distributed trades across time bins produce high entropy and no block."""
    w261.reset()
    assert not w261.is_entry_blocked()
    assert not w261.is_blocked()

    # 20 trades evenly spaced across a 20.0s window (1 trade every 1.0s)
    t_start = 1000.0
    for i in range(20):
        w261.record_trade(ts=t_start + i * 1.0, volume=1.0)

    assert not w261.is_entry_blocked()
    metrics = w261.get_entropy_metrics()
    assert metrics["normalized_entropy"] >= 0.70
    assert metrics["max_concentration"] <= 0.30
    assert not metrics["is_blocked"]


def test_wave261_temporal_entropy_collapse_blocks():
    """Severe trade concentration into narrow bins drops entropy <= 0.35 and blocks."""
    w261.reset()
    assert not w261.is_entry_blocked()

    # Direct ingestion of low entropy
    w261.record_entropy(0.20, max_concentration=0.70, sample_count=18)
    assert w261.is_entry_blocked()
    assert w261.is_blocked()

    metrics = w261.get_entropy_metrics()
    assert metrics["normalized_entropy"] <= 0.35
    assert metrics["is_blocked"] is True


def test_wave261_acute_single_bin_concentration_blocks():
    """Acute burst of 12 trades in the exact same 1.0s interval triggers concentration block."""
    w261.reset()
    assert not w261.is_entry_blocked()

    t = 2000.0
    # Ingest 12 trades in the same sub-second interval
    for i in range(12):
        w261.record_trade(ts=t + i * 0.05, volume=1.0)

    assert w261.is_entry_blocked()
    assert w261.is_blocked()

    metrics = w261.get_entropy_metrics()
    assert metrics["max_concentration"] >= 0.80
    assert metrics["is_blocked"] is True


def test_wave261_insufficient_trades_no_block():
    """Fewer than 10 trades does not trip concentration or entropy collapse."""
    w261.reset()
    assert not w261.is_entry_blocked()

    t = 3000.0
    # Only 5 trades in rapid succession
    for i in range(5):
        w261.record_trade(ts=t + i * 0.1, volume=1.0)

    assert not w261.is_entry_blocked()


def test_wave261_input_validation_and_reset():
    """Invalid trade inputs are rejected and reset restores normal state."""
    w261.reset()

    # Booleans and invalid values rejected
    w261.record_trade(ts=100.0, volume=-1.0)
    w261.record_trade(ts=100.0, volume=0.0)
    w261.record_trade(ts=100.0, volume=float("nan"))
    w261.record_trade(ts=True)  # type: ignore
    w261.record_entropy(float("nan"))
    w261.update(ts=True)  # type: ignore
    assert not w261.is_entry_blocked()

    # Trip block and reset
    w261.record_entropy(0.15, max_concentration=0.85, sample_count=20)
    assert w261.is_entry_blocked()

    w261.reset()
    assert not w261.is_entry_blocked()
    status = w261.get_status()
    assert status["is_blocked"] is False
