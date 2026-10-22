"""
test_batch252.py
----------------
Unit test suite for Batch 252:
- wave270_lob_quote_life_entropy_guard.py (Wave 270: LOB Quote Life Duration Distribution & Exponential Decay Guard)
- wave271_trade_vwap_slippage_drift_guard.py (Wave 271: Execution VWAP vs Midpoint Execution Drift & Slippage Escalation Guard)
"""

import math
import pytest
import time

import wave270_lob_quote_life_entropy_guard as w270
import wave271_trade_vwap_slippage_drift_guard as w271


# ---------------------------------------------------------------------------
# Wave 270: LOB Quote Life Duration Guard Tests
# ---------------------------------------------------------------------------

def test_wave270_healthy_lifespans_no_block():
    """Healthy resting quote lifespans (> 200 ms) do not trigger fleeting guard."""
    w270.reset()
    assert not w270.is_entry_blocked()
    assert not w270.is_blocked()

    # Ingest 25 quotes with lifespans between 250ms and 800ms
    for i in range(25):
        w270.record_quote_lifetime(300.0 + i * 20.0)
        assert not w270.is_entry_blocked()

    metrics = w270.get_lifetime_metrics()
    assert metrics["fleeting_ratio"] == 0.0
    assert metrics["median_lifetime_ms"] >= 200.0
    assert not metrics["is_blocked"]


def test_wave270_dominant_fleeting_share_blocks():
    """Fleeting quote share >= 0.75 over 20 cancellations triggers block."""
    w270.reset()
    assert not w270.is_entry_blocked()

    # Ingest 20 quotes with 18 having lifespan <= 50ms (e.g. 45ms) and 2 having 300ms
    # Median is 45ms, fleeting ratio = 18/20 = 0.90
    for i in range(20):
        lt = 45.0 if i < 18 else 300.0
        w270.record_quote_lifetime(lt)

    assert w270.is_entry_blocked()
    assert w270.is_blocked()

    metrics = w270.get_lifetime_metrics()
    assert metrics["fleeting_ratio"] >= 0.75
    assert metrics["is_blocked"] is True


def test_wave270_acute_median_lifespan_decay_blocks():
    """Median quote lifespan <= 40.0 ms over 15 cancellations triggers block."""
    w270.reset()
    assert not w270.is_entry_blocked()

    # Direct ingestion of low median lifespan
    w270.record_fleeting_metrics(0.60, median_lifetime_ms=35.0, sample_count=16)
    assert w270.is_entry_blocked()
    assert w270.is_blocked()

    metrics = w270.get_lifetime_metrics()
    assert metrics["median_lifetime_ms"] <= 40.0
    assert metrics["is_blocked"] is True


def test_wave270_ultra_fleeting_streak_blocks():
    """8 consecutive ultra-fleeting quotes (<= 25.0 ms) triggers acute streak block."""
    w270.reset()
    assert not w270.is_entry_blocked()

    # First quote normal
    w270.record_quote_lifetime(300.0)
    assert not w270.is_entry_blocked()

    # 8 consecutive ultra-fleeting cancellations (20ms each)
    for _ in range(8):
        w270.record_quote_lifetime(20.0)

    assert w270.is_entry_blocked()
    assert w270.is_blocked()

    metrics = w270.get_lifetime_metrics()
    assert metrics["current_streak"] >= 8
    assert metrics["is_blocked"] is True


def test_wave270_input_validation_and_reset():
    """Invalid quote lifetime inputs are rejected and reset restores normal state."""
    w270.reset()

    # Booleans and invalid values rejected
    w270.record_quote_lifetime(True)  # type: ignore
    w270.record_quote_lifetime(False)  # type: ignore
    w270.record_quote_lifetime(-10.0)
    w270.record_quote_lifetime(float("nan"))
    w270.record_fleeting_metrics(float("inf"))
    w270.update(True)  # type: ignore
    assert not w270.is_entry_blocked()

    # Trip block and reset
    w270.record_fleeting_metrics(0.85, sample_count=22)
    assert w270.is_entry_blocked()

    w270.reset()
    assert not w270.is_entry_blocked()
    status = w270.get_status()
    assert status["is_blocked"] is False


# ---------------------------------------------------------------------------
# Wave 271: Execution VWAP Slippage Drift Guard Tests
# ---------------------------------------------------------------------------

def test_wave271_controlled_slippage_no_block():
    """Controlled slippage (< 1.20 bps) does not trigger slippage block."""
    w271.reset()
    assert not w271.is_entry_blocked()
    assert not w271.is_blocked()

    # 10 executions with 0.80 bps slippage
    for _ in range(12):
        w271.record_slippage(0.80, volume=1.0)
        assert not w271.is_entry_blocked()

    metrics = w271.get_slippage_metrics()
    assert metrics["latest_mean_slippage_bps"] < 1.20
    assert not metrics["is_blocked"]


def test_wave271_elevated_mean_slippage_blocks():
    """Mean VWAP slippage >= 2.50 bps over 10 fills triggers block."""
    w271.reset()
    assert not w271.is_entry_blocked()

    # Ingest 10 fills with 3.0 bps slippage
    for _ in range(10):
        w271.record_slippage(3.00, volume=2.0)

    assert w271.is_entry_blocked()
    assert w271.is_blocked()

    metrics = w271.get_slippage_metrics()
    assert metrics["latest_mean_slippage_bps"] >= 2.50
    assert metrics["is_blocked"] is True


def test_wave271_acute_single_fill_blowout_blocks():
    """Acute single fill slippage >= 5.00 bps triggers block."""
    w271.reset()
    assert not w271.is_entry_blocked()

    # Executed at 2001.20 vs mid 2000.00 -> 6.0 bps slippage
    w271.record_execution(2001.20, 2000.00, volume=1.0)
    assert w271.is_entry_blocked()
    assert w271.is_blocked()

    metrics = w271.get_slippage_metrics()
    assert metrics["latest_single_slippage_bps"] >= 5.00
    assert metrics["is_blocked"] is True


def test_wave271_insufficient_fills_no_block():
    """Fewer than 10 fills without acute blowout does not trip condition 1."""
    w271.reset()
    assert not w271.is_entry_blocked()

    # Ingest only 6 fills with 3.5 bps slippage (below 5.0 acute blowout)
    for _ in range(6):
        w271.record_slippage(3.50, volume=1.0)

    assert not w271.is_entry_blocked()


def test_wave271_input_validation_and_reset():
    """Invalid execution inputs are rejected and reset restores normal state."""
    w271.reset()

    # Booleans and negative/invalid numbers rejected
    w271.record_execution(True, 2000.0)  # type: ignore
    w271.record_execution(2000.0, False)  # type: ignore
    w271.record_execution(-2000.0, 2000.0)
    w271.record_execution(2000.0, float("nan"))
    w271.record_slippage(float("inf"))
    w271.record_slippage(2.0, volume=-1.0)
    w271.update(True)  # type: ignore
    assert not w271.is_entry_blocked()

    # Trip block and reset
    w271.record_slippage(6.00)
    assert w271.is_entry_blocked()

    w271.reset()
    assert not w271.is_entry_blocked()
    status = w271.get_status()
    assert status["is_blocked"] is False
