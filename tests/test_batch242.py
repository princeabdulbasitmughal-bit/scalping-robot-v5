"""
tests/test_batch242.py
-----------------------
Unit test suite for Batch 242:
- Wave 250: Order Book Bid-Ask Pressure Imbalance & Step Velocity Guard
- Wave 251: Microstructure Trade Run Sign Inversion & Ping-Pong Chaos Guard

Verifies multi-tier weighted order book pressure asymmetry, step velocity surges,
high-frequency trade sign inversion rates, acute alternating whipsaw streaks, and cooldowns.
"""

import math
import time
import pytest

import wave250_lob_pressure_imbalance_step_velocity_guard as wave250
import wave251_trade_run_sign_inversion_chaos_guard as wave251


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave250.reset()
    wave251.reset()
    yield
    wave250.reset()
    wave251.reset()


# ---------------------------------------------------------------------------
# Wave 250: Order Book Pressure Imbalance & Step Velocity Guard Tests
# ---------------------------------------------------------------------------

def test_wave250_balanced_pressure_no_block():
    """Symmetric order book weighted pressures (|Pi| <= 0.35, low velocity) do not block."""
    assert not wave250.is_entry_blocked()
    assert not wave250.is_blocked()

    # Balanced book: 5.0 lots each side
    wave250.record_pressures(bid_pressure=5.0, ask_pressure=5.0)

    assert not wave250.is_entry_blocked()
    metrics = wave250.get_pressure_metrics()
    assert metrics["pressure_asymmetry"] == 0.0
    status = wave250.get_status()
    assert not status["is_blocked"]


def test_wave250_pressure_asymmetry_blocks():
    """Severe weighted pressure gradient asymmetry (|Pi| >= 0.75 on total >= 5.0 lots) blocks entries for 45s."""
    # Bid pressure = 9.0 lots, Ask pressure = 1.0 lot -> Asymmetry = 8.0 / 10.0 = 0.80 >= 0.75
    wave250.record_pressures(bid_pressure=9.0, ask_pressure=1.0)

    assert wave250.is_entry_blocked()
    assert wave250.is_blocked()
    metrics = wave250.get_pressure_metrics()
    assert abs(metrics["pressure_asymmetry"]) >= wave250.MAX_PRESSURE_ASYMMETRY
    status = wave250.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave250_step_velocity_surge_blocks():
    """Rapid pressure step velocity surge (|v_step| >= 0.65 units/sec in <= 0.5s) blocks entries for 45s."""
    t0 = 1000.0
    # Step 1: Neutral pressure at t0
    wave250.record_pressures(bid_pressure=5.0, ask_pressure=5.0, ts=t0)
    # Step 2: Sudden violent flip to ask dominant pressure 0.2s later
    # Bid = 1.5, Ask = 8.5 -> asym = -7.0 / 10.0 = -0.70.
    # Shift = -0.70 in 0.2s -> velocity = -0.70 / 0.20 = -3.5 units/sec
    wave250.record_pressures(bid_pressure=1.5, ask_pressure=8.5, ts=t0 + 0.20)

    assert wave250.is_entry_blocked()
    assert wave250.is_blocked()
    metrics = wave250.get_pressure_metrics()
    assert abs(metrics["step_velocity"]) >= wave250.MAX_STEP_VELOCITY
    status = wave250.get_status()
    assert status["is_blocked"]


def test_wave250_tier_depths_calculation():
    """Multi-tier 1/k weighted depth calculation correctly aggregates and evaluates asymmetry."""
    # 3 tiers: Bid has [10.0, 6.0, 3.0] -> 10 + 3 + 1 = 14.0
    # Ask has [0.5, 0.4, 0.3] -> 0.5 + 0.2 + 0.1 = 0.8
    # Asymmetry = (14.0 - 0.8) / 14.8 = 0.89 >= 0.75
    wave250.update([10.0, 6.0, 3.0], [0.5, 0.4, 0.3])

    assert wave250.is_entry_blocked()
    metrics = wave250.get_pressure_metrics()
    assert metrics["pressure_asymmetry"] >= wave250.MAX_PRESSURE_ASYMMETRY


def test_wave250_input_validation_and_reset():
    """Negative pressures, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave250.record_pressures(-5.0, 10.0)
    wave250.record_pressures(10.0, -5.0)
    wave250.record_pressures(True, 10.0)
    wave250.record_pressures(float("nan"), 10.0)
    wave250.record_tier_depths([-1.0, 2.0], [1.0, 2.0])

    assert not wave250.is_entry_blocked()

    # Trigger block then reset
    wave250.record_pressures(10.0, 0.5)
    assert wave250.is_entry_blocked()

    wave250.reset()
    assert not wave250.is_entry_blocked()
    status = wave250.get_status()
    assert status["pressure_asymmetry"] == 0.0
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 251: Trade Run Sign Inversion & Ping-Pong Chaos Guard Tests
# ---------------------------------------------------------------------------

def test_wave251_directional_flow_no_block():
    """Directional trend or diffusive flow (R_inv ~ 0.50, streak <= 4) does not block."""
    assert not wave251.is_entry_blocked()
    assert not wave251.is_blocked()

    # Series with runs of buys and sells: 3 buys, 3 sells, etc.
    flow = ["buy", "buy", "buy", "sell", "sell", "sell"] * 3  # 18 trades
    for s in flow:
        wave251.record_trade(s)

    assert not wave251.is_entry_blocked()
    metrics = wave251.get_inversion_metrics()
    assert metrics["inversion_rate"] < 0.60
    status = wave251.get_status()
    assert not status["is_blocked"]
    assert status["sample_count"] == 18


def test_wave251_ping_pong_chaos_blocks():
    """Severe ping-pong sign inversion chaos (R_inv >= 85% on N >= 15) blocks entries for 45s."""
    # 18 alternating trades: buy, sell, buy, sell, ...
    for i in range(18):
        side = "buy" if i % 2 == 0 else "sell"
        wave251.update(side)

    assert wave251.is_entry_blocked()
    assert wave251.is_blocked()
    metrics = wave251.get_inversion_metrics()
    assert metrics["inversion_rate"] >= wave251.MAX_INVERSION_RATE
    status = wave251.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave251_acute_alternating_streak_blocks():
    """Acute alternating reversal streak of >= 8 trades immediately blocks entries for 45s."""
    # 8 consecutive alternating trade directions
    for i in range(8):
        wave251.record_trade(1 if i % 2 == 0 else -1)

    assert wave251.is_entry_blocked()
    assert wave251.is_blocked()
    metrics = wave251.get_inversion_metrics()
    assert metrics["alternating_streak"] >= wave251.MAX_ALTERNATING_STREAK
    status = wave251.get_status()
    assert status["is_blocked"]


def test_wave251_insufficient_samples_no_block():
    """Fewer than MIN_SAMPLES=15 trades without 8-trade alternating streak does not block."""
    # 5 trades alternating: buy, sell, buy, sell, buy
    for i in range(5):
        wave251.record_trade("buy" if i % 2 == 0 else "sell")

    assert not wave251.is_entry_blocked()
    assert wave251.get_status()["sample_count"] == 5


def test_wave251_input_validation_and_reset():
    """Invalid sides, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave251.record_trade("invalid")
    wave251.record_trade(True)
    wave251.record_trade(False)
    wave251.record_trade(float("nan"))
    wave251.record_trade(float("inf"))

    assert not wave251.is_entry_blocked()
    assert wave251.get_status()["sample_count"] == 0

    # Trigger block then reset
    for i in range(8):
        wave251.record_trade("buy" if i % 2 == 0 else "sell")
    assert wave251.is_entry_blocked()

    wave251.reset()
    assert not wave251.is_entry_blocked()
    status = wave251.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]
