"""
test_batch248.py
----------------
Unit test suite for Batch 248:
- wave262_lob_spread_jump_velocity_acceleration_guard.py (Wave 262: LOB Bid-Ask Spread Expansion Velocity & Acceleration Guard)
- wave263_trade_sign_markov_transition_entropy_guard.py (Wave 263: Trade Sign Markov Transition & Run Persistence Guard)
"""

import math
import pytest
import time

import wave262_lob_spread_jump_velocity_acceleration_guard as w262
import wave263_trade_sign_markov_transition_entropy_guard as w263


# ---------------------------------------------------------------------------
# Wave 262: LOB Spread Jump Velocity & Acceleration Guard Tests
# ---------------------------------------------------------------------------

def test_wave262_stable_spread_no_block():
    """Stable spread with negligible velocity and acceleration does not trigger block."""
    w262.reset()
    assert not w262.is_entry_blocked()
    assert not w262.is_blocked()

    t = 1000.0
    for i in range(10):
        # Bid 2400.0, Ask 2400.20 (spread ~0.83 bps, perfectly constant)
        w262.record_quote(2400.00, 2400.20, ts=t + i * 1.0)
        assert not w262.is_entry_blocked()

    metrics = w262.get_velocity_metrics()
    assert abs(metrics["latest_velocity"]) < 0.10
    assert not metrics["is_blocked"]


def test_wave262_high_velocity_expansion_blocks():
    """Spread expanding at velocity >= 3.50 bps/s with spread >= 2.50 bps triggers block."""
    w262.reset()
    assert not w262.is_entry_blocked()

    # Direct ingestion of high velocity
    w262.record_spread(3.00, velocity=4.00, accel=1.0)
    assert w262.is_entry_blocked()
    assert w262.is_blocked()

    metrics = w262.get_velocity_metrics()
    assert metrics["latest_velocity"] >= 3.50
    assert metrics["is_blocked"] is True


def test_wave262_spread_acceleration_surge_blocks():
    """Spread acceleration >= 6.00 bps/sec^2 triggers block."""
    w262.reset()
    assert not w262.is_entry_blocked()

    # Direct ingestion of acceleration surge
    w262.record_spread(2.00, velocity=2.00, accel=7.50)
    assert w262.is_entry_blocked()
    assert w262.is_blocked()

    metrics = w262.get_velocity_metrics()
    assert metrics["latest_acceleration"] >= 6.00
    assert metrics["is_blocked"] is True


def test_wave262_acute_spread_flash_jump_blocks():
    """Acute spread expansion jump >= 4.50 bps within 1.0s triggers block."""
    w262.reset()
    assert not w262.is_entry_blocked()

    t = 2000.0
    # Normal initial quote: bid 2000.0, ask 2000.20 (spread 1.0 bps)
    w262.record_quote(2000.00, 2000.20, ts=t)
    assert not w262.is_entry_blocked()

    # 0.5s later, ask blows out to 2001.40 (spread 7.0 bps -> jump of 6.0 bps)
    w262.record_quote(2000.00, 2001.40, ts=t + 0.5)
    assert w262.is_entry_blocked()
    assert w262.is_blocked()


def test_wave262_input_validation_and_reset():
    """Invalid quote inputs are rejected and reset restores normal state."""
    w262.reset()

    # Crossed quote rejected
    w262.record_quote(2002.0, 2000.0)
    # Booleans and invalid values rejected
    w262.record_quote(True, 2000.5)  # type: ignore
    w262.record_quote(2000.0, False)  # type: ignore
    w262.record_quote(-100.0, 2000.5)
    w262.record_quote(2000.0, float("nan"))
    w262.record_spread(float("inf"))
    w262.update(True)  # type: ignore
    assert not w262.is_entry_blocked()

    # Trip block and reset
    w262.record_spread(5.00)
    assert w262.is_entry_blocked()

    w262.reset()
    assert not w262.is_entry_blocked()
    status = w262.get_status()
    assert status["is_blocked"] is False


# ---------------------------------------------------------------------------
# Wave 263: Trade Sign Markov Transition & Run Persistence Guard Tests
# ---------------------------------------------------------------------------

def test_wave263_balanced_alternating_signs_no_block():
    """Balanced alternating trade flow (+1, -1, +1, -1...) yields zero persistence and no block."""
    w263.reset()
    assert not w263.is_entry_blocked()
    assert not w263.is_blocked()

    # Ingest 24 alternating trades
    for i in range(24):
        sign = 1 if i % 2 == 0 else -1
        w263.record_trade_sign(sign)
        assert not w263.is_entry_blocked()

    metrics = w263.get_markov_metrics()
    assert metrics["persistence_ratio"] == 0.0
    assert not metrics["is_blocked"]


def test_wave263_markov_persistence_herding_blocks():
    """Persistent sweeping flow with persistence ratio >= 0.82 triggers block."""
    w263.reset()
    assert not w263.is_entry_blocked()

    # Direct ingestion of high persistence
    w263.record_persistence(0.88, streak=5, sample_count=22)
    assert w263.is_entry_blocked()
    assert w263.is_blocked()

    metrics = w263.get_markov_metrics()
    assert metrics["persistence_ratio"] >= 0.82
    assert metrics["is_blocked"] is True


def test_wave263_acute_directional_streak_blocks():
    """8 consecutive identical buy signs (+1) triggers acute streak block."""
    w263.reset()
    assert not w263.is_entry_blocked()

    # First trade opposite
    w263.record_trade_sign(-1)
    assert not w263.is_entry_blocked()

    # 8 consecutive buys (+1)
    for i in range(7):
        w263.record_trade_sign(1)
        assert not w263.is_entry_blocked()

    # 8th consecutive buy
    w263.record_trade_sign(1)
    assert w263.is_entry_blocked()
    assert w263.is_blocked()

    metrics = w263.get_markov_metrics()
    assert metrics["current_streak"] >= 8
    assert metrics["is_blocked"] is True


def test_wave263_insufficient_trades_no_block():
    """Fewer than 20 trades without acute streak does not trip persistence condition."""
    w263.reset()
    assert not w263.is_entry_blocked()

    # Direct ingestion with only 12 samples
    w263.record_persistence(0.90, streak=4, sample_count=12)
    assert not w263.is_entry_blocked()


def test_wave263_input_validation_and_reset():
    """Invalid sign inputs are rejected and reset restores normal state."""
    w263.reset()

    # Booleans, zeros, and invalid numbers rejected
    w263.record_trade_sign(True)  # type: ignore
    w263.record_trade_sign(False)  # type: ignore
    w263.record_trade_sign(0)
    w263.record_trade_sign(float("nan"))  # type: ignore
    w263.record_persistence(float("nan"))
    w263.update(True)  # type: ignore
    assert not w263.is_entry_blocked()

    # Trip block and reset
    w263.record_persistence(0.85, streak=8, sample_count=20)
    assert w263.is_entry_blocked()

    w263.reset()
    assert not w263.is_entry_blocked()
    status = w263.get_status()
    assert status["is_blocked"] is False
