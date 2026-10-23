"""
tests/test_batch263.py
----------------------
Unit tests for Batch 263:
  - Wave 292: Wave292LobDepthWeightedSpreadShockGuard
  - Wave 293: Wave293TradeSizeHillTailIndexGuard
"""

import math
import time
import pytest

from wave292_lob_depth_weighted_spread_shock_guard import Wave292LobDepthWeightedSpreadShockGuard
from wave293_trade_size_hill_tail_index_guard import Wave293TradeSizeHillTailIndexGuard


# ----------------------------------------------------------------------
# Wave 292 Tests: LOB Depth-Weighted Spread & Multi-Level Squeeze Guard
# ----------------------------------------------------------------------

def test_wave292_dense_depth_no_block():
    guard = Wave292LobDepthWeightedSpreadShockGuard(
        max_mean_spread_bps=4.20,
        min_samples=8,
        acute_spread_bps=7.00,
    )

    # Multi-tier book with tight 1-2 bps spreads across levels 1-3
    bids = [(100.00, 10.0), (99.99, 15.0), (99.98, 20.0)]
    asks = [(100.01, 10.0), (100.02, 15.0), (100.03, 20.0)]

    for _ in range(10):
        guard.record_book_depth(bids, asks)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_depth_spread_metrics()
    assert metrics["mean_depth_weighted_spread_bps"] <= 3.50
    assert not metrics["is_blocked"]


def test_wave292_depth_spread_squeeze_blocks():
    guard = Wave292LobDepthWeightedSpreadShockGuard(
        max_mean_spread_bps=4.20,
        min_samples=8,
        cooldown_seconds=45.0,
    )

    # Precomputed depth spread squeeze injection (spread = 5.20 bps over 10 snapshots)
    guard.record_depth_spread_metrics(spread_bps=5.20, sample_count=10)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    metrics = guard.get_status()
    assert metrics["is_blocked"]
    assert "DEPTH_SPREAD_SQUEEZE" in metrics["last_block_reason"]


def test_wave292_acute_depth_spread_blowout_blocks():
    guard = Wave292LobDepthWeightedSpreadShockGuard(
        acute_spread_bps=7.00,
        cooldown_seconds=45.0,
    )

    # Hollow book with severe multi-level gaps: Level 1 has 0.1 lots, Level 2/3 sit at 8-10 bps gap
    bids = [(100.00, 0.1), (99.90, 10.0), (99.85, 10.0)]
    asks = [(100.01, 0.1), (100.10, 10.0), (100.15, 10.0)]
    guard.record_book_depth(bids, asks)

    assert guard.is_entry_blocked()
    metrics = guard.get_depth_spread_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_DEPTH_SPREAD_BLOWOUT" in metrics["last_block_reason"]


def test_wave292_insufficient_samples_no_block():
    guard = Wave292LobDepthWeightedSpreadShockGuard(
        max_mean_spread_bps=4.20,
        min_samples=8,
    )

    # Elevated depth spread (5.0 bps) but only 4 snapshots (< 8 min_samples)
    guard.record_depth_spread_metrics(spread_bps=5.0, sample_count=4)

    assert not guard.is_entry_blocked()


def test_wave292_input_validation_and_reset():
    guard = Wave292LobDepthWeightedSpreadShockGuard()

    # Corrupted book snapshot (not list) triggers fail-closed
    guard.record_book_depth("corrupted", [])
    assert guard.is_entry_blocked()
    assert "CORRUPTED" in guard.get_status()["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked()

    # Negative spread triggers fail-closed
    guard.update(-1.5)
    assert guard.is_entry_blocked()

    guard.reset()
    assert not guard.is_entry_blocked()


# ----------------------------------------------------------------------
# Wave 293 Tests: Trade Size Hill Tail Index Guard
# ----------------------------------------------------------------------

def test_wave293_moderate_tails_no_block():
    guard = Wave293TradeSizeHillTailIndexGuard(
        min_hill_index=1.15,
        min_top_trade=8.0,
        min_trades=15,
        acute_whale_size=18.0,
    )

    # Thin/moderate trade sizes (0.5 to 2.5 lots)
    sizes = [0.5, 1.0, 1.2, 0.8, 1.5, 2.0, 0.7, 1.1, 1.4, 0.9, 1.6, 2.2, 1.0, 1.3, 0.6, 1.8]
    for s in sizes:
        guard.record_trade_size(s)
        assert not guard.is_entry_blocked()

    metrics = guard.get_tail_metrics()
    assert metrics["hill_tail_index"] >= 1.50
    assert not metrics["is_blocked"]


def test_wave293_heavy_tail_collapse_blocks():
    guard = Wave293TradeSizeHillTailIndexGuard(
        min_hill_index=1.15,
        min_top_trade=8.0,
        min_trades=15,
        cooldown_seconds=45.0,
    )

    # Direct injection of heavy tail collapse metric (alpha = 0.95, top trade = 12.0)
    guard.record_tail_metrics(hill_index=0.95, max_size=12.0, sample_count=18)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    metrics = guard.get_status()
    assert metrics["is_blocked"]
    assert "HEAVY_TAIL_COLLAPSE" in metrics["last_block_reason"]


def test_wave293_acute_whale_print_blocks():
    guard = Wave293TradeSizeHillTailIndexGuard(
        acute_whale_size=18.0,
        cooldown_seconds=45.0,
    )

    # Single massive 25.0 lot execution
    guard.record_trade_size(25.0)

    assert guard.is_entry_blocked()
    metrics = guard.get_tail_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_WHALE_PRINT" in metrics["last_block_reason"]


def test_wave293_insufficient_samples_no_block():
    guard = Wave293TradeSizeHillTailIndexGuard(
        min_hill_index=1.15,
        min_top_trade=8.0,
        min_trades=15,
    )

    # Heavy tail metric but only 6 trades (< 15 min_trades)
    guard.record_tail_metrics(hill_index=0.90, max_size=10.0, sample_count=6)

    assert not guard.is_entry_blocked()


def test_wave293_input_validation_and_reset():
    guard = Wave293TradeSizeHillTailIndexGuard()

    # Corrupted size (NaN) triggers fail-closed
    guard.record_trade_size(float("nan"))
    assert guard.is_entry_blocked()
    assert "CORRUPTED" in guard.get_status()["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked()

    # Boolean trade size triggers fail-closed
    guard.update(True)
    assert guard.is_entry_blocked()

    guard.reset()
    assert not guard.is_entry_blocked()
