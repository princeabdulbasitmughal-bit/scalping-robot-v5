"""
tests/test_batch219.py
-----------------------
Unit test suite for Batch 219:
- Wave 204: High-Frequency Midquote Micro-Jitter & Transition Entropy Guard
- Wave 205: Realized Effective Spread Expansion Burst Guard

Verifies midquote sign flip kinematics, transition Shannon entropy, effective spread blowout,
fail-closed assertions, and monotonic cooldown timers.
"""

import math
import time
import pytest

import wave204_midquote_jitter_entropy_guard as wave204
import wave205_effective_spread_expansion_burst_guard as wave205


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave204.reset()
    wave205.reset()
    yield
    wave204.reset()
    wave205.reset()


# ---------------------------------------------------------------------------
# Wave 204: Midquote Jitter Entropy Guard Tests
# ---------------------------------------------------------------------------

def test_wave204_normal_midquote_diffusion_no_block():
    """Normal stochastic midquote movements (Jitter ratio ~ 0.50, Entropy ~ 1.0) do not block."""
    assert not wave204.is_entry_blocked()
    assert not wave204.is_blocked()

    # Stochastic walk: 2 up, 1 down, 2 up, 1 down ...
    base_price = 2000.0
    for i in range(16):
        step = 0.10 if (i % 3 != 0) else -0.10
        base_price += step
        wave204.record_midquote(bid=base_price, ask=base_price + 0.20, ts=100.0 + (i * 0.30))

    assert not wave204.is_entry_blocked()
    metrics = wave204.get_jitter_metrics()
    assert metrics["jitter_ratio"] < wave204.MAX_JITTER_RATIO
    assert metrics["jitter_entropy"] > wave204.MIN_JITTER_ENTROPY
    status = wave204.get_status()
    assert not status["is_blocked"]


def test_wave204_high_frequency_pinging_jitter_blocks():
    """Rapid back-and-forth pinging (+tick, -tick) with fast cadence blocks entries for 45s."""
    base_price = 2000.0
    # 14 alternating ticks at 0.05s intervals (dt = 0.05s <= 0.20s)
    for i in range(14):
        p = base_price + (0.05 if i % 2 == 0 else -0.05)
        wave204.update(bid=p, ask=p + 0.20, ts=100.0 + (i * 0.05))

    assert wave204.is_entry_blocked()
    assert wave204.is_blocked()
    metrics = wave204.get_jitter_metrics()
    assert metrics["jitter_ratio"] >= wave204.MAX_JITTER_RATIO
    status = wave204.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave204_deterministic_entropy_collapse_blocks():
    """Extreme near-100% alternation collapses transition entropy <= 0.35, blocking entries."""
    base_price = 2000.0
    # 16 perfectly alternating ticks
    for i in range(16):
        p = base_price + (0.05 if i % 2 == 0 else -0.05)
        wave204.record_midquote(bid=p, ask=p + 0.20, ts=100.0 + (i * 0.10))

    assert wave204.is_entry_blocked()
    metrics = wave204.get_jitter_metrics()
    assert metrics["jitter_entropy"] <= wave204.MIN_JITTER_ENTROPY


def test_wave204_input_validation_and_fail_closed():
    """Inverted quotes, booleans, negatives, NaNs, and Infs are rejected safely."""
    wave204.record_midquote(2000.20, 2000.00)  # inverted quote rejected
    wave204.record_midquote(2000.00, 2000.00)  # zero spread rejected
    wave204.record_midquote(True, 2000.20)  # bool rejected
    wave204.record_midquote(2000.00, False)  # bool rejected
    wave204.record_midquote(-2000.00, 2000.20)  # negative rejected
    wave204.record_midquote(float("nan"), 2000.20)  # nan rejected
    wave204.record_midquote(2000.00, float("inf"))  # inf rejected

    assert not wave204.is_entry_blocked()
    assert wave204.get_status()["sample_count"] == 0


def test_wave204_reset_and_status():
    """Reset clears signs history, metrics, and active blocks."""
    for i in range(14):
        p = 2000.0 + (0.05 if i % 2 == 0 else -0.05)
        wave204.record_midquote(bid=p, ask=p + 0.20, ts=100.0 + (i * 0.05))

    assert wave204.is_entry_blocked()

    wave204.reset()
    assert not wave204.is_entry_blocked()
    metrics = wave204.get_jitter_metrics()
    assert metrics["jitter_ratio"] == 0.50
    assert metrics["jitter_entropy"] == 1.0
    status = wave204.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 205: Effective Spread Expansion Burst Guard Tests
# ---------------------------------------------------------------------------

def test_wave205_normal_tight_execution_no_block():
    """Executions at the touch (expansion ratio ~ 1.0, low effective spread) do not block."""
    assert not wave205.is_entry_blocked()
    assert not wave205.is_blocked()

    # Quoted: Bid=2000.00, Ask=2000.20 (mid=2000.10, spread = 1.0 bp)
    # Execution at Ask=2000.20 -> effective spread = 2 * 0.10 / 2000.10 * 10,000 = 1.0 bp
    wave205.record_execution(trade_price=2000.20, bid=2000.00, ask=2000.20)

    assert not wave205.is_entry_blocked()
    metrics = wave205.get_spread_metrics()
    assert metrics["expansion_ratio"] <= wave205.MAX_EXPANSION_RATIO
    assert metrics["effective_spread_bps"] < wave205.MAX_EFFECTIVE_SPREAD_BPS
    status = wave205.get_status()
    assert not status["is_blocked"]


def test_wave205_expansion_ratio_blowout_blocks():
    """Execution swept deep into book (expansion ratio >= 2.5x) blocks entries for 45s."""
    # Quoted: Bid=2000.00, Ask=2000.20 (mid=2000.10, quoted spread = 1.0 bp)
    # Filled at 2000.50 (adverse move 0.40 beyond mid -> effective spread = 4.0 bps)
    # Expansion ratio = 4.0 / 1.0 = 4.0 >= 2.5
    wave205.update(trade_price=2000.50, bid=2000.00, ask=2000.20)

    assert wave205.is_entry_blocked()
    assert wave205.is_blocked()
    metrics = wave205.get_spread_metrics()
    assert metrics["expansion_ratio"] >= wave205.MAX_EXPANSION_RATIO
    status = wave205.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave205_extreme_effective_spread_blocks():
    """Large absolute effective spread (>= 8.0 bps) blocks entries."""
    # Quoted: Bid=2000.00, Ask=2001.00 (mid=2000.50, quoted spread = 5.0 bps)
    # Trade executes at 2001.50 -> effective spread = 2 * 1.0 / 2000.5 * 10,000 = 10.0 bps >= 8.0
    wave205.record_execution(trade_price=2001.50, bid=2000.00, ask=2001.00)

    assert wave205.is_entry_blocked()
    metrics = wave205.get_spread_metrics()
    assert metrics["effective_spread_bps"] >= wave205.MAX_EFFECTIVE_SPREAD_BPS


def test_wave205_input_validation_and_fail_closed():
    """Inverted quotes, booleans, negative prices, NaNs, and Infs are safely rejected."""
    wave205.record_execution(trade_price=2000.20, bid=2000.30, ask=2000.10)  # inverted rejected
    wave205.record_execution(trade_price=2000.20, bid=2000.00, ask=2000.00)  # zero spread rejected
    wave205.record_execution(trade_price=True, bid=2000.00, ask=2000.20)  # bool rejected
    wave205.record_execution(trade_price=2000.20, bid=2000.00, ask=False)  # bool rejected
    wave205.record_execution(trade_price=-2000.0, bid=2000.00, ask=2000.20)  # negative rejected
    wave205.record_execution(trade_price=float("nan"), bid=2000.00, ask=2000.20)  # nan rejected
    wave205.record_execution(trade_price=2000.20, bid=2000.00, ask=float("inf"))  # inf rejected

    assert not wave205.is_entry_blocked()


def test_wave205_reset_and_status():
    """Reset clears spread metrics and active cooldown blocks."""
    wave205.record_execution(2002.0, 2000.0, 2000.20)  # massive blowout -> blocked
    assert wave205.is_entry_blocked()

    wave205.reset()
    assert not wave205.is_entry_blocked()
    metrics = wave205.get_spread_metrics()
    assert metrics["quoted_spread_bps"] == 0.0
    assert metrics["effective_spread_bps"] == 0.0
    assert metrics["expansion_ratio"] == 1.0
    status = wave205.get_status()
    assert not status["is_blocked"]
