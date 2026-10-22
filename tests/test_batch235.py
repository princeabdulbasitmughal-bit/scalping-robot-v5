"""
tests/test_batch235.py
-----------------------
Unit test suite for Batch 235:
- Wave 236: Order Book Bid-Ask Slope Asymmetry & Liquidity Gradient Guard
- Wave 237: Trade Flow Markov Run Transition & Momentum Persistence Guard

Verifies order book liquidity gradient asymmetry, bilateral shallow air pockets,
2nd-order Markov trade run continuation persistence, directional streaks, and cooldowns.
"""

import math
import time
import pytest

import wave236_lob_slope_liquidity_gradient_asymmetry_guard as wave236
import wave237_trade_markov_run_momentum_persistence_guard as wave237


@pytest.fixture(autouse=True)
def reset_guards():
    """Reset guard modules before and after each test."""
    wave236.reset()
    wave237.reset()
    yield
    wave236.reset()
    wave237.reset()


# ---------------------------------------------------------------------------
# Wave 236: Order Book Slope Asymmetry Guard Tests
# ---------------------------------------------------------------------------

def test_wave236_symmetric_slopes_no_block():
    """Symmetric order book slopes (R_slope < 8.0x) with adequate depth do not block."""
    assert not wave236.is_entry_blocked()
    assert not wave236.is_blocked()

    # Both slopes = 3.0 lots/bp
    wave236.record_book_slopes(bid_slope_lots_per_bp=3.0, ask_slope_lots_per_bp=3.0)

    assert not wave236.is_entry_blocked()
    metrics = wave236.get_slope_metrics()
    assert metrics["slope_asymmetry"] == 1.0
    status = wave236.get_status()
    assert not status["is_blocked"]


def test_wave236_severe_slope_asymmetry_blocks():
    """Severe slope asymmetry (ratio >= 8.0x with dominant >= 5.0 and lagging <= 0.50) blocks entries for 45s."""
    # Bid slope = 12.0 lots/bp, Ask slope = 0.30 lots/bp -> Asymmetry = 40.0x >= 8.0x
    wave236.update(bid_slope=12.0, ask_slope=0.30)

    assert wave236.is_entry_blocked()
    assert wave236.is_blocked()
    metrics = wave236.get_slope_metrics()
    assert metrics["slope_asymmetry"] >= wave236.MAX_SLOPE_ASYMMETRY
    status = wave236.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave236_bilateral_shallow_air_pocket_blocks():
    """Bilateral shallow air pocket (both slopes <= 0.20 lots/bp) blocks entries."""
    # Both slopes = 0.10 lots/bp
    wave236.record_book_slopes(bid_slope_lots_per_bp=0.10, ask_slope_lots_per_bp=0.10)

    assert wave236.is_entry_blocked()
    assert wave236.is_blocked()
    status = wave236.get_status()
    assert status["is_blocked"]


def test_wave236_tier_computation_no_block():
    """Slopes derived from balanced multi-tier book depths do not block."""
    # (30 - 10) / 5 = 4.0 lots/bp on both sides
    wave236.record_book_tiers(
        bid_depth_touch=10.0,
        bid_depth_outer=30.0,
        bid_spread_bps=5.0,
        ask_depth_touch=10.0,
        ask_depth_outer=30.0,
        ask_spread_bps=5.0,
    )

    assert not wave236.is_entry_blocked()
    metrics = wave236.get_slope_metrics()
    assert metrics["bid_slope"] == 4.0
    assert metrics["ask_slope"] == 4.0


def test_wave236_input_validation_and_reset():
    """Negative slopes, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave236.record_book_slopes(True, 3.0)
    wave236.record_book_slopes(3.0, False)
    wave236.record_book_slopes(-3.0, 3.0)
    wave236.record_book_slopes(3.0, -3.0)
    wave236.record_book_slopes(float("nan"), 3.0)
    wave236.record_book_slopes(3.0, float("inf"))

    assert not wave236.is_entry_blocked()

    # Trigger block then reset
    wave236.record_book_slopes(10.0, 0.2)
    assert wave236.is_entry_blocked()

    wave236.reset()
    assert not wave236.is_entry_blocked()
    metrics = wave236.get_slope_metrics()
    assert metrics["slope_asymmetry"] == 1.0
    status = wave236.get_status()
    assert not status["is_blocked"]


# ---------------------------------------------------------------------------
# Wave 237: Trade Flow Markov Run Momentum Guard Tests
# ---------------------------------------------------------------------------

def test_wave237_alternating_diffusive_trades_no_block():
    """Diffusive alternating trades with zero Markov continuation do not block."""
    assert not wave237.is_entry_blocked()
    assert not wave237.is_blocked()

    # 18 alternating trades
    for i in range(18):
        wave237.record_trade("buy" if i % 2 == 0 else "sell")

    assert not wave237.is_entry_blocked()
    metrics = wave237.get_markov_metrics()
    assert metrics["p_plus_given_plus_plus"] < wave237.MAX_MARKOV_PERSISTENCE
    status = wave237.get_status()
    assert not status["is_blocked"]


def test_wave237_extreme_markov_continuation_blocks():
    """Persistent 2nd-order Markov continuation (P(+|++) >= 0.85 on N_++ >= 6) blocks entries for 45s."""
    # 8 buys, 1 sell, 8 buys produces N(++) ~ 12, P(+|++) ~ 0.92 >= 0.85
    trades = ["buy"] * 7 + ["sell"] + ["buy"] * 8
    for s in trades:
        wave237.update(s)

    assert wave237.is_entry_blocked()
    assert wave237.is_blocked()
    metrics = wave237.get_markov_metrics()
    assert metrics["p_plus_given_plus_plus"] >= wave237.MAX_MARKOV_PERSISTENCE
    status = wave237.get_status()
    assert status["is_blocked"]
    assert status["blocked_seconds_remaining"] > 40.0


def test_wave237_acute_directional_streak_blocks():
    """Streak of >= 8 consecutive trades in identical direction immediately triggers streak block."""
    for _ in range(8):
        wave237.record_trade("sell")

    assert wave237.is_entry_blocked()
    assert wave237.is_blocked()
    metrics = wave237.get_markov_metrics()
    assert metrics["streak_length"] >= wave237.MAX_STREAK_LENGTH
    status = wave237.get_status()
    assert status["is_blocked"]


def test_wave237_insufficient_samples_no_block():
    """Fewer than MIN_SAMPLES=15 trades without streak does not trigger Markov block."""
    trades = ["buy", "buy", "buy", "sell", "sell", "buy"]
    for s in trades:
        wave237.record_trade(s)

    assert not wave237.is_entry_blocked()
    assert wave237.get_status()["sample_count"] == 6


def test_wave237_input_validation_and_reset():
    """Invalid sides, booleans, NaNs, and Infs are rejected, and reset restores clean state."""
    wave237.record_trade("invalid")
    wave237.record_trade(True)
    wave237.record_trade(False)
    wave237.record_trade(float("nan"))
    wave237.record_trade(float("inf"))

    assert not wave237.is_entry_blocked()

    # Trigger block then reset
    for _ in range(8):
        wave237.record_trade("buy")
    assert wave237.is_entry_blocked()

    wave237.reset()
    assert not wave237.is_entry_blocked()
    metrics = wave237.get_markov_metrics()
    assert metrics["streak_length"] == 0.0
    status = wave237.get_status()
    assert status["sample_count"] == 0
    assert not status["is_blocked"]
