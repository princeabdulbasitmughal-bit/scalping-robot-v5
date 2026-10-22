"""
tests/test_batch223.py
-----------------------
Unit test suite for Batch 223:
- Wave 212: Microstructure Noise-to-Signal Ratio (NSR) & High-Frequency Frictional Trap Guard
- Wave 213: Second-Order Trade Direction Markov Transition & Drift Acceleration Guard

Verifies raw vs subsampled realized variance noise decomposition, 2nd-order Markov transition
probabilities, fail-closed assertions, and monotonic cooldown timers.
"""

import math
import time
import pytest

import wave212_microstructure_noise_snr_decay_guard as wave212
import wave213_trade_sign_markov_drift_acceleration_guard as wave213


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave212.reset()
    wave213.reset()
    yield
    wave212.reset()
    wave213.reset()


# ---------------------------------------------------------------------------
# Wave 212: Microstructure Noise-to-Signal Ratio Guard Tests
# ---------------------------------------------------------------------------

def test_wave212_normal_low_noise_smooth_trend_no_block():
    """Smooth trending prices without excessive bounce noise maintain low NSR, no block."""
    assert not wave212.is_entry_blocked()
    assert not wave212.is_blocked()

    # Steady directional trend: price increases by 0.10 every tick
    # r_{1, i} = 0.10 / 2000. Sparse r_{5, j} = 0.50 / 2000.
    # RV_raw = 25 * (0.1)^2 = 0.25. RV_sparse = 5 * (0.5)^2 = 1.25. NSR = 0!
    price = 2000.0
    for _ in range(28):
        price += 0.10
        wave212.record_price(price)

    assert not wave212.is_entry_blocked()
    metrics = wave212.get_noise_metrics()
    assert metrics["nsr"] <= wave212.MAX_NOISE_RATIO
    status = wave212.get_status()
    assert not status["is_blocked"]


def test_wave212_high_frequency_bid_ask_bounce_noise_blocks():
    """High-frequency bid-ask bouncing creates massive raw RV but zero sparse RV, blocking entries."""
    price = 2000.0
    # Alternating bounce (+0.50, -0.50) every tick for 28 ticks
    # Every 5th tick lands back near origin (sparse return ~ 0), but raw return variance is huge!
    for i in range(28):
        p = price + (0.50 if i % 2 == 0 else 0.0)
        wave212.update(p)

    assert wave212.is_entry_blocked()
    assert wave212.is_blocked()
    metrics = wave212.get_noise_metrics()
    assert metrics["nsr"] >= wave212.MAX_NOISE_RATIO
    status = wave212.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave212_insufficient_samples_no_block():
    """Less than MIN_SAMPLES prices do not trigger block regardless of noise."""
    price = 2000.0
    for i in range(15):
        p = price + (0.50 if i % 2 == 0 else 0.0)
        wave212.record_price(p)

    assert not wave212.is_entry_blocked()
    assert wave212.get_status()["sample_count"] == 15


def test_wave212_input_validation_and_fail_closed():
    """Booleans, negative prices, NaNs, and Infs are safely rejected."""
    wave212.record_price(True)
    wave212.record_price(False)
    wave212.record_price(-2000.0)
    wave212.record_price(0.0)
    wave212.record_price(float("nan"))
    wave212.record_price(float("inf"))

    assert not wave212.is_entry_blocked()


def test_wave212_reset_and_status():
    """Reset clears price deque, metrics, and active cooldown blocks."""
    for i in range(28):
        wave212.record_price(2000.0 + (0.50 if i % 2 == 0 else 0.0))

    assert wave212.is_entry_blocked()

    wave212.reset()
    assert not wave212.is_entry_blocked()
    metrics = wave212.get_noise_metrics()
    assert metrics["nsr"] == 0.0
    status = wave212.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 213: Trade Direction Markov Transition Guard Tests
# ---------------------------------------------------------------------------

def test_wave213_normal_diffusive_alternation_no_block():
    """Stochastically alternating trades with balanced Markov transition probabilities do not block."""
    assert not wave213.is_entry_blocked()
    assert not wave213.is_blocked()

    # Pattern: ++- ++- --+ --+
    trades = ["buy", "buy", "sell", "buy", "buy", "sell", "sell", "sell", "buy", "sell",
              "sell", "buy", "buy", "sell", "buy", "sell", "buy", "buy"]
    for t in trades:
        wave213.record_trade(side=t)

    assert not wave213.is_entry_blocked()
    metrics = wave213.get_markov_metrics()
    assert metrics["p_plus_given_plus_plus"] < wave213.MAX_MARKOV_DRIFT
    assert metrics["p_minus_given_minus_minus"] < wave213.MAX_MARKOV_DRIFT
    status = wave213.get_status()
    assert not status["is_blocked"]


def test_wave213_persistent_upward_markov_drift_blocks():
    """Persistent buyer-initiated flow with P(+|++) >= 0.85 blocks entries for 45s."""
    # Feed runs of 4 buys, 1 sell, 4 buys, 1 sell...
    # (++, +) occurs frequently and overwhelmingly resolves to another buy (+)
    trades = ["buy", "buy", "buy", "buy", "sell",
              "buy", "buy", "buy", "buy", "sell",
              "buy", "buy", "buy", "buy", "sell"]
    for t in trades:
        wave213.update(side=t)

    assert wave213.is_entry_blocked()
    assert wave213.is_blocked()
    metrics = wave213.get_markov_metrics()
    assert metrics["p_plus_given_plus_plus"] >= wave213.MAX_MARKOV_DRIFT
    status = wave213.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave213_persistent_downward_markov_drift_blocks():
    """Persistent seller-initiated flow with P(-|--) >= 0.85 blocks entries for 45s."""
    trades = ["sell", "sell", "sell", "sell", "buy",
              "sell", "sell", "sell", "sell", "buy",
              "sell", "sell", "sell", "sell", "buy"]
    for t in trades:
        wave213.record_trade(side=t)

    assert wave213.is_entry_blocked()
    metrics = wave213.get_markov_metrics()
    assert metrics["p_minus_given_minus_minus"] >= wave213.MAX_MARKOV_DRIFT


def test_wave213_tick_rule_and_input_validation():
    """Tick rule correctly infers buy and sell signs; invalid values are rejected."""
    wave213.record_trade(side=True)  # bool rejected
    wave213.record_trade(price=False)  # bool rejected
    wave213.record_trade(side="hold")  # invalid side rejected
    wave213.record_trade(price=-10.0)  # negative rejected
    wave213.record_trade(price=float("nan"))  # nan rejected

    assert not wave213.is_entry_blocked()
    assert wave213.get_status()["sample_count"] == 0

    # Test tick rule price inference
    wave213.record_trade(price=2000.0)  # seed
    wave213.record_trade(price=2000.5)  # up -> +1
    wave213.record_trade(price=2000.2)  # down -> -1
    status = wave213.get_status()
    assert status["sample_count"] == 2


def test_wave213_reset_and_status():
    """Reset clears signed trade history, Markov metrics, and active cooldown blocks."""
    trades = ["buy", "buy", "buy", "buy", "sell"] * 3
    for t in trades:
        wave213.record_trade(side=t)
    assert wave213.is_entry_blocked()

    wave213.reset()
    assert not wave213.is_entry_blocked()
    metrics = wave213.get_markov_metrics()
    assert metrics["p_plus_given_plus_plus"] == 0.50
    assert metrics["p_minus_given_minus_minus"] == 0.50
    status = wave213.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]
