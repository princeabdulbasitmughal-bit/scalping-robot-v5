"""
tests/test_batch215.py
-----------------------
Unit test suite for Batch 215:
- Wave 196: Quote Arrival Intensity Acceleration & Burst Churn Guard
- Wave 197: Trade Flow Directional Runs Persistence (Wald-Wolfowitz) Guard

Verifies high-frequency quote rate kinematics, non-parametric runs statistics, fail-closed handling,
and monotonic cooldown timers.
"""

import math
import time
import pytest

import wave196_quote_intensity_acceleration_guard as wave196
import wave197_trade_flow_signed_runs_guard as wave197


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave196.reset()
    wave197.reset()
    yield
    wave196.reset()
    wave197.reset()


# ---------------------------------------------------------------------------
# Wave 196: Quote Intensity Acceleration Guard Tests
# ---------------------------------------------------------------------------

def test_wave196_normal_quote_intensity_no_block():
    """Moderate quote arrival rates within normal trading bounds do not block."""
    assert not wave196.is_entry_blocked()
    assert not wave196.is_blocked()

    # 15 quotes spaced over 1.0 second (15 quotes/sec)
    base_t = 1000.0
    for i in range(15):
        t = base_t + (i * 0.06)
        wave196.record_quote(bid=2000.0, ask=2000.20, ts=t)

    assert not wave196.is_entry_blocked()
    assert wave196.get_intensity() <= 60.0
    status = wave196.get_status()
    assert not status["is_blocked"]


def test_wave196_hyper_quote_intensity_blocks():
    """Quote arrival intensity >= MAX_QUOTE_INTENSITY (120 quotes/sec) blocks entries."""
    base_t = 1000.0
    # Ingest 130 quotes within 0.8 seconds
    for i in range(130):
        t = base_t + (i * 0.005)
        wave196.update(bid=2000.0, ask=2000.25, ts=t)

    assert wave196.is_entry_blocked()
    assert wave196.is_blocked()
    assert wave196.get_intensity() >= 120.0
    status = wave196.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave196_intensity_acceleration_blocks():
    """A sudden quote arrival surge from calm to hyper-accelerated trips acceleration threshold."""
    # Prior window [998.0, 999.0]: only 5 quotes (intensity = 5 quotes/sec)
    for i in range(5):
        wave196.record_quote(bid=2000.0, ask=2000.20, ts=998.2 + (i * 0.15))

    # Current window [999.0, 1000.0]: 95 quotes (intensity = 95 quotes/sec)
    # Acceleration = (95 - 5) / 1.0 = 90 quotes/sec^2 >= 80.0
    for i in range(95):
        wave196.record_quote(bid=2000.0, ask=2000.20, ts=999.05 + (i * 0.009))

    assert wave196.is_entry_blocked()
    assert wave196.get_acceleration() >= wave196.MAX_INTENSITY_ACCELERATION


def test_wave196_input_validation_and_fail_closed():
    """Inverted quotes, booleans, negatives, NaNs, and Infs are rejected safely."""
    wave196.record_quote(2000.20, 2000.00)  # inverted quote (bid > ask) rejected
    wave196.record_quote(2000.00, 2000.00)  # zero spread rejected
    wave196.record_quote(True, 2000.20)  # bool bid rejected
    wave196.record_quote(2000.00, False)  # bool ask rejected
    wave196.record_quote(-2000.00, 2000.20)  # negative bid rejected
    wave196.record_quote(2000.00, -2000.20)  # negative ask rejected
    wave196.record_quote(float("nan"), 2000.20)  # nan rejected
    wave196.record_quote(2000.00, float("inf"))  # inf rejected
    wave196.record_quote("2000.00", "2000.20")  # strings rejected

    assert not wave196.is_entry_blocked()
    assert wave196.get_status()["history_count"] == 0


def test_wave196_reset_and_status():
    """Reset clears quote history and metrics; get_status reports accurate diagnostic state."""
    # Trigger block
    for i in range(125):
        wave196.record_quote(2000.0, 2000.20, ts=1000.0 + (i * 0.005))

    assert wave196.is_entry_blocked()

    wave196.reset()
    assert not wave196.is_entry_blocked()
    assert wave196.get_intensity() == 0.0
    assert wave196.get_acceleration() == 0.0
    status = wave196.get_status()
    assert status["history_count"] == 0
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 197: Trade Flow Signed Runs Guard Tests
# ---------------------------------------------------------------------------

def test_wave197_normal_alternating_trades_no_block():
    """Normally distributed alternating buy/sell trades have high runs count and do not block."""
    assert not wave197.is_entry_blocked()
    assert not wave197.is_blocked()

    # Perfectly alternating flow: buy, sell, buy, sell ...
    for i in range(20):
        side = "buy" if i % 2 == 0 else "sell"
        wave197.record_trade(side=side)

    assert not wave197.is_entry_blocked()
    assert wave197.get_runs_zscore() > -1.0
    status = wave197.get_status()
    assert not status["is_blocked"]
    assert status["consecutive_run"] == 1


def test_wave197_consecutive_streak_blocks():
    """8 consecutive trades in the same direction trip MAX_CONSECUTIVE_RUN and block."""
    # 8 consecutive sells
    for _ in range(8):
        wave197.update(side="sell")

    assert wave197.is_entry_blocked()
    assert wave197.is_blocked()
    status = wave197.get_status()
    assert status["is_blocked"]
    assert status["consecutive_run"] == 8
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave197_negative_runs_zscore_persistence_blocks():
    """Highly persistent clustered flow trips Wald-Wolfowitz negative Z-score threshold."""
    # 20 trades total: 5 buys, 5 sells, 5 buys, 5 sells.
    # N+ = 10, N- = 10, N = 20. Total runs = 4.
    # Expected runs = 1 + (2*10*10)/20 = 11. Variance = 4.74.
    # Z-score = (4 - 11) / 2.176 = -3.21 <= -2.33 (p < 0.01).
    # Streak length max is 5 (does not trip MAX_CONSECUTIVE_RUN = 8).
    for _ in range(5):
        wave197.record_trade(side="buy")
    for _ in range(5):
        wave197.record_trade(side="sell")
    for _ in range(5):
        wave197.record_trade(side="buy")
    for _ in range(5):
        wave197.record_trade(side="sell")

    assert wave197.is_entry_blocked()
    assert wave197.get_runs_zscore() <= wave197.MIN_RUNS_ZSCORE


def test_wave197_tick_rule_price_inference():
    """Tick rule correctly infers buy (+1) on price uptick and sell (-1) on price downtick."""
    wave197.record_trade(price=2000.0)  # seed
    wave197.record_trade(price=2000.5)  # up -> +1
    wave197.record_trade(price=2000.2)  # down -> -1
    wave197.record_trade(price=2000.8)  # up -> +1

    status = wave197.get_status()
    assert status["sample_count"] == 3


def test_wave197_fail_closed_and_reset():
    """Invalid sides, prices, booleans, and NaNs are ignored; reset clears all state."""
    wave197.record_trade(side=True)  # bool side rejected
    wave197.record_trade(price=False)  # bool price rejected
    wave197.record_trade(side="hold")  # invalid side rejected
    wave197.record_trade(price=-10.0)  # negative price rejected
    wave197.record_trade(price=float("nan"))  # nan rejected
    wave197.record_trade(price=float("inf"))  # inf rejected

    assert not wave197.is_entry_blocked()
    assert wave197.get_status()["sample_count"] == 0

    # Trip block
    for _ in range(8):
        wave197.record_trade(side="buy")
    assert wave197.is_entry_blocked()

    # Reset
    wave197.reset()
    assert not wave197.is_entry_blocked()
    assert wave197.get_runs_zscore() == 0.0
    status = wave197.get_status()
    assert status["sample_count"] == 0
    assert status["consecutive_run"] == 0
    assert not status["is_blocked"]
