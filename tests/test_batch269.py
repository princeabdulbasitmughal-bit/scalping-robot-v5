"""
tests/test_batch269.py
----------------------
Unit tests for Batch 269:
  - Wave 304: Wave304LobDepthSlopeGradientGuard
  - Wave 305: Wave305TradeArrivalBurstinessGuard
"""

import math
import time
import pytest

from wave304_lob_depth_slope_gradient_guard import Wave304LobDepthSlopeGradientGuard
from wave305_trade_arrival_burstiness_guard import Wave305TradeArrivalBurstinessGuard


# ----------------------------------------------------------------------
# Wave 304 Tests: LOB Multi-Tier Cumulative Depth Slope Guard
# ----------------------------------------------------------------------

def test_wave304_thick_liquidity_gradient_no_block():
    guard = Wave304LobDepthSlopeGradientGuard(
        min_gradient_slope=0.80,
        min_samples=8,
    )

    # 10 snapshots of a thick liquid order book:
    # Tier depths: 2.0, 3.5, 4.0, 5.0, 6.0 lots per side
    for _ in range(10):
        bids = [2.0, 3.5, 4.0, 5.0, 6.0]
        asks = [2.0, 3.5, 4.0, 5.0, 6.0]
        guard.record_lob_depths(bid_depths=bids, ask_depths=asks, spread_bps=1.0)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_gradient_metrics()
    assert metrics["mean_slope"] >= 5.0
    assert not metrics["is_blocked"]


def test_wave304_depleted_book_gradient_blocks():
    guard = Wave304LobDepthSlopeGradientGuard(
        min_gradient_slope=0.80,
        min_samples=8,
        cooldown_seconds=45.0,
    )

    # Flat, depleted book: outer tiers have 1.20 lots total (> 1.00 acute limit),
    # but slope across tiers is only 0.40 lots/tick (< 0.80 min_gradient_slope)
    for _ in range(9):
        bids = [0.50, 0.20, 0.20, 0.20]
        asks = [0.50, 0.20, 0.20, 0.20]
        guard.record_lob_depths(bid_depths=bids, ask_depths=asks, spread_bps=1.0)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    status = guard.get_status()
    assert status["is_blocked"]
    assert "DEPLETED_BOOK_GRADIENT" in status["last_block_reason"]


def test_wave304_acute_liquidity_vacuum_blocks():
    guard = Wave304LobDepthSlopeGradientGuard(
        acute_gradient_slope=0.15,
        acute_spread_bps=2.20,
        cooldown_seconds=45.0,
    )

    # Book with trivial depth and blowout spread of 3.50 bps
    bids = [0.05, 0.02, 0.02, 0.02]
    asks = [0.05, 0.02, 0.02, 0.02]
    guard.record_lob_depths(bid_depths=bids, ask_depths=asks, spread_bps=3.50)

    assert guard.is_entry_blocked()
    metrics = guard.get_gradient_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_LIQUIDITY_VACUUM" in metrics["last_block_reason"]


def test_wave304_outer_depth_collapse_blocks():
    guard = Wave304LobDepthSlopeGradientGuard(
        acute_min_outer_depth=1.00,
        acute_gradient_slope=0.20,
        cooldown_seconds=45.0,
    )

    # Inside quotes have 1.0 lot, but outer tiers 2-4 are completely empty (0.01 lot)
    bids = [1.0, 0.01, 0.01, 0.01]
    asks = [1.0, 0.01, 0.01, 0.01]
    guard.record_lob_depths(bid_depths=bids, ask_depths=asks, spread_bps=1.0)

    assert guard.is_entry_blocked()
    assert "ACUTE_OUTER_DEPTH_COLLAPSE" in guard.get_status()["last_block_reason"]


def test_wave304_fail_closed_and_reset():
    guard = Wave304LobDepthSlopeGradientGuard(cooldown_seconds=45.0)

    # Corrupted inputs: non-list, None, negative, NaN
    for bad_depths in [None, "invalid", [1.0, float("nan")], [1.0, -0.5], [1.0]]:
        guard.record_lob_depths(bad_depths, [1.0, 1.0])
        assert guard.is_entry_blocked()
        assert "CORRUPTED_LOB_DEPTH_INPUT" in guard.get_status()["last_block_reason"]
        guard.reset()
        assert not guard.is_entry_blocked()

    # Update alias check
    guard.update([2.0, 3.0], [2.0, 3.0], spread_bps=1.0)
    assert not guard.is_entry_blocked()


# ----------------------------------------------------------------------
# Wave 305 Tests: Trade Arrival Burstiness Parameter Guard
# ----------------------------------------------------------------------

def test_wave305_poisson_memoryless_arrivals_no_block():
    guard = Wave305TradeArrivalBurstinessGuard(
        max_burstiness=0.65,
        min_samples=15,
    )

    # Moderate exponential/Poisson-like inter-arrival durations with CV ~ 1.0 (B ~ 0.0)
    poisson_durations = [
        0.50, 0.20, 0.80, 0.40, 0.60, 0.30, 0.70, 0.50,
        0.25, 0.65, 0.45, 0.55, 0.35, 0.75, 0.40, 0.50
    ]
    for tau in poisson_durations:
        guard.record_duration(tau)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_burstiness_metrics()
    assert metrics["burstiness_parameter"] < 0.60
    assert not metrics["is_blocked"]


def test_wave305_burstiness_parameter_surge_blocks():
    guard = Wave305TradeArrivalBurstinessGuard(
        max_burstiness=0.65,
        min_samples=15,
        max_mean_duration_sec=0.25,
        cooldown_seconds=45.0,
    )

    # Directly inject precomputed burstiness metrics representing severe clustering
    guard.record_burstiness_metrics(b_score=0.72, mean_duration=0.15, sample_count=16)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    status = guard.get_status()
    assert status["is_blocked"]
    assert "BURSTINESS_PARAMETER_SURGE" in status["last_block_reason"]


def test_wave305_acute_micro_barrage_streak_blocks():
    guard = Wave305TradeArrivalBurstinessGuard(
        acute_micro_streak=6,
        acute_micro_duration_sec=0.010,
        cooldown_seconds=45.0,
    )

    # 5 micro trades (tau = 0.005s) -> not yet 6
    for _ in range(5):
        guard.record_duration(0.005)
        assert not guard.is_entry_blocked()

    # 6th micro trade -> trips streak
    guard.record_duration(0.005)
    assert guard.is_entry_blocked()
    assert "ACUTE_MICRO_BARRAGE_STREAK" in guard.get_status()["last_block_reason"]


def test_wave305_acute_hyper_burst_blocks():
    guard = Wave305TradeArrivalBurstinessGuard(
        acute_burstiness=0.85,
        cooldown_seconds=45.0,
    )

    # Precomputed extreme burstiness metrics (B = 0.90)
    guard.record_burstiness_metrics(b_score=0.90, mean_duration=0.05, sample_count=10)

    assert guard.is_entry_blocked()
    metrics = guard.get_burstiness_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_HYPER_BURST_SHOCK" in metrics["last_block_reason"]


def test_wave305_fail_closed_and_reset():
    guard = Wave305TradeArrivalBurstinessGuard(cooldown_seconds=45.0)

    # Corrupted inputs: None, bool, NaN, Inf, zero, negative
    for bad_val in [None, True, False, float("nan"), float("inf"), 0.0, -1.0]:
        guard.record_duration(bad_val)
        assert guard.is_entry_blocked()
        assert "CORRUPTED_DURATION_INPUT" in guard.get_status()["last_block_reason"]
        guard.reset()
        assert not guard.is_entry_blocked()

    # Update alias check
    guard.update(0.10)
    assert not guard.is_entry_blocked()
