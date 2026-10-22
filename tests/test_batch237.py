"""
tests/test_batch237.py
-----------------------
Unit test suite for Batch 237:
- Wave 240: Limit Order Book Midpoint Drift & Momentum Slip Guard
- Wave 241: Order Fill Imbalance & Adverse Selection Velocity Guard

Verifies conditional midpoint drift following aggressive flow, acute momentum jumps,
directional volume imbalance ratios, acute fill velocity avalanches, and cooldowns.
"""

import math
import time
import pytest

import wave240_lob_midpoint_drift_momentum_guard as wave240
import wave241_order_fill_imbalance_velocity_guard as wave241


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave240.reset()
    wave241.reset()
    yield
    wave240.reset()
    wave241.reset()


# ---------------------------------------------------------------------------
# Wave 240: LOB Midpoint Drift & Momentum Slip Guard Tests
# ---------------------------------------------------------------------------

def test_wave240_normal_drift_no_block():
    """Mean-reverting, low midpoint drift (mean <= 0.50 bps) does not block."""
    assert not wave240.is_entry_blocked()
    assert not wave240.is_blocked()

    # Alternating tiny drift between +0.20 and -0.20 bps
    for i in range(12):
        drift = 0.20 if i % 2 == 0 else -0.20
        wave240.record_drift_bps(trade_side=1, drift_bps=drift)

    assert not wave240.is_entry_blocked()
    metrics = wave240.get_drift_metrics()
    assert abs(metrics["mean_drift_bps"]) < 0.50
    status = wave240.get_status()
    assert not status["is_blocked"]
    assert status["sample_count"] == 12


def test_wave240_sustained_adverse_drift_blocks():
    """Sustained adverse directional midpoint drift (mean >= 1.80 bps on N >= 10) blocks entries for 45s."""
    # Buy orders where mid drifts from 2000.00 to 2000.40 -> +2.0 bps drift
    for _ in range(12):
        wave240.record_midpoint_drift(trade_side="buy", initial_mid=2000.00, post_mid=2000.40)

    assert wave240.is_entry_blocked()
    assert wave240.is_blocked()
    metrics = wave240.get_drift_metrics()
    assert metrics["mean_drift_bps"] >= wave240.MAX_MEAN_DRIFT_BPS
    status = wave240.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave240_acute_momentum_jump_blocks():
    """Acute single trade midpoint momentum jump (drift >= 3.50 bps) blocks entries for 45s."""
    # Sell order where mid drops sharply from 2000.00 to 1999.20 -> side (-1) * -4.0 bps = +4.0 bps adverse drift
    wave240.update(trade_side="sell", initial_mid=2000.00, post_mid=1999.20)

    assert wave240.is_entry_blocked()
    assert wave240.is_blocked()
    metrics = wave240.get_drift_metrics()
    assert metrics["latest_drift_bps"] >= wave240.MAX_ACUTE_DRIFT_BPS
    status = wave240.get_status()
    assert status["is_blocked"]


def test_wave240_insufficient_samples_no_block():
    """Fewer than MIN_SAMPLES=10 trades without acute jump do not trigger sustained block."""
    for _ in range(6):
        wave240.record_drift_bps(trade_side=1, drift_bps=2.20)

    assert not wave240.is_entry_blocked()
    assert wave240.get_status()["sample_count"] == 6


def test_wave240_input_validation_and_reset():
    """Invalid sides, non-positive prices, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave240.record_midpoint_drift("invalid_side", 2000.0, 2000.5)
    wave240.record_midpoint_drift("buy", -2000.0, 2000.5)
    wave240.record_midpoint_drift("buy", 2000.0, -2000.5)
    wave240.record_drift_bps(True, 2.0)
    wave240.record_drift_bps("buy", float("nan"))
    wave240.record_drift_bps("buy", float("inf"))

    assert not wave240.is_entry_blocked()
    assert wave240.get_status()["sample_count"] == 0

    # Trigger block then reset
    wave240.record_drift_bps("buy", 4.0)
    assert wave240.is_entry_blocked()

    wave240.reset()
    assert not wave240.is_entry_blocked()
    status = wave240.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 241: Order Fill Imbalance & Velocity Guard Tests
# ---------------------------------------------------------------------------

def test_wave241_balanced_fills_no_block():
    """Balanced two-way trade fills (R_vimb <= 0.40, gentle velocity) do not block."""
    assert not wave241.is_entry_blocked()
    assert not wave241.is_blocked()

    t0 = 5000.0
    # Alternating buys and sells of 1.0 lot spaced 0.5s apart
    for i in range(12):
        side = "buy" if i % 2 == 0 else "sell"
        wave241.record_fill(side=side, volume=1.0, ts=t0 + 0.5 * i)

    assert not wave241.is_entry_blocked()
    metrics = wave241.get_imbalance_metrics()
    assert metrics["volume_imbalance"] <= 0.40
    status = wave241.get_status()
    assert not status["is_blocked"]
    assert status["sample_count"] == 12


def test_wave241_extreme_volume_imbalance_blocks():
    """Extreme directional volume imbalance (R_vimb >= 80% on V_total >= 15.0 and N >= 10) blocks entries for 45s."""
    t0 = 6000.0
    # 10 consecutive buy fills of 2.0 lots spaced 1.0s apart (total 20.0 lots, R_vimb = 100%, v_fill = 2.0 lots/sec)
    for i in range(11):
        wave241.update(side="buy", volume=2.0, ts=t0 + 1.0 * i)

    assert wave241.is_entry_blocked()
    assert wave241.is_blocked()
    metrics = wave241.get_imbalance_metrics()
    assert metrics["volume_imbalance"] >= wave241.MAX_VOLUME_IMBALANCE
    assert metrics["total_volume"] >= wave241.MIN_TOTAL_VOLUME
    status = wave241.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave241_acute_fill_velocity_avalanche_blocks():
    """Acute fill velocity avalanche (v_fill >= 8.0 lots/sec in <= 2.0s) blocks entries for 45s."""
    t0 = 7000.0
    # Rapid burst of 10.0 lots in 1.0s -> 10.0 lots/sec >= 8.0 lots/sec
    wave241.record_fill(side="sell", volume=5.0, ts=t0)
    wave241.record_fill(side="sell", volume=5.0, ts=t0 + 0.8)

    assert wave241.is_entry_blocked()
    assert wave241.is_blocked()
    metrics = wave241.get_imbalance_metrics()
    assert metrics["fill_velocity"] >= wave241.MAX_FILL_VELOCITY
    status = wave241.get_status()
    assert status["is_blocked"]


def test_wave241_insufficient_volume_or_samples_no_block():
    """Fewer than MIN_SAMPLES=10 trades or under 15.0 total lots without velocity avalanche does not block."""
    t0 = 8000.0
    # 5 buy trades of 1.0 lot spaced 2.5s apart (total 5.0 lots < 15.0, v_fill < 1.0 lots/sec)
    for i in range(5):
        wave241.record_fill(side="buy", volume=1.0, ts=t0 + 2.5 * i)

    assert not wave241.is_entry_blocked()
    status = wave241.get_status()
    assert status["sample_count"] == 5
    assert not status["is_blocked"]


def test_wave241_input_validation_and_reset():
    """Invalid sides, non-positive volume, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave241.record_fill("invalid", 1.0)
    wave241.record_fill("buy", -1.0)
    wave241.record_fill("buy", 0.0)
    wave241.record_fill(True, 1.0)
    wave241.record_fill("buy", float("nan"))
    wave241.record_fill("buy", float("inf"))

    assert not wave241.is_entry_blocked()
    assert wave241.get_status()["sample_count"] == 0

    # Trigger block then reset
    wave241.record_fill("buy", 10.0, ts=9000.0)
    wave241.record_fill("buy", 10.0, ts=9000.5)
    assert wave241.is_entry_blocked()

    wave241.reset()
    assert not wave241.is_entry_blocked()
    status = wave241.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]
