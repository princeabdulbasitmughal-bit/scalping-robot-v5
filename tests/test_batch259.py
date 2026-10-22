"""
tests/test_batch259.py
----------------------
Unit tests for Batch 259:
  - Wave 284: Wave284LobQueueExhaustionDepletionGuard
  - Wave 285: Wave285TradeFlowSignedVolumeMomentumGuard
"""

import math
import time
import pytest

from wave284_lob_queue_exhaustion_depletion_guard import Wave284LobQueueExhaustionDepletionGuard
from wave285_trade_flow_signed_volume_momentum_guard import Wave285TradeFlowSignedVolumeMomentumGuard


# ----------------------------------------------------------------------
# Wave 284 Tests: LOB Inside-Queue Cumulative Depletion Guard
# ----------------------------------------------------------------------

def test_wave284_healthy_depth_no_block():
    guard = Wave284LobQueueExhaustionDepletionGuard(
        max_depletion_ratio=0.80,
        min_spread_bps=2.00,
        min_samples=8,
        acute_depletion_velocity=12.0,
    )

    # Stable depth around 10 lots with tight spread 1.0 bps
    for _ in range(12):
        guard.record_queue_state(bid_depth=10.0, ask_depth=9.5, spread_bps=1.0)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_depletion_metrics()
    assert metrics["mean_depletion_ratio"] < 0.20
    assert not metrics["is_blocked"]


def test_wave284_persistent_depletion_blocks():
    guard = Wave284LobQueueExhaustionDepletionGuard(
        max_depletion_ratio=0.80,
        min_spread_bps=2.00,
        min_samples=8,
        cooldown_seconds=45.0,
    )

    # Direct ingestion of 9 high depletion events (0.85 depletion ratio, 2.5 bps spread)
    for _ in range(9):
        guard.record_depletion_metrics(depletion_ratio=0.85, spread_bps=2.50)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    metrics = guard.get_status()
    assert metrics["is_blocked"]
    assert "PERSISTENT_QUEUE_DEPLETION" in metrics["last_block_reason"]


def test_wave284_acute_queue_evaporation_blocks():
    guard = Wave284LobQueueExhaustionDepletionGuard(
        acute_depletion_velocity=12.0,
        acute_remaining_queue=0.50,
        cooldown_seconds=45.0,
    )

    # 1. Depth at t=10.00 is 10.0 lots
    guard.record_queue_state(bid_depth=10.0, ask_depth=10.0, ts=10.00)
    # 2. Flash sweep at t=10.05: depth drops to 0.20 lots (depletion vel = 9.8 / 0.05 = 196 lots/s)
    guard.record_queue_state(bid_depth=0.20, ask_depth=0.20, ts=10.05)

    assert guard.is_entry_blocked()
    metrics = guard.get_depletion_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_QUEUE_EVAPORATION" in metrics["last_block_reason"]


def test_wave284_insufficient_samples_no_block():
    guard = Wave284LobQueueExhaustionDepletionGuard(
        max_depletion_ratio=0.80,
        min_spread_bps=2.00,
        min_samples=8,
    )

    # High depletion but only 4 samples (< 8 min_samples)
    for _ in range(4):
        guard.record_depletion_metrics(depletion_ratio=0.90, spread_bps=3.0, sample_count=4)

    assert not guard.is_entry_blocked()


def test_wave284_input_validation_and_reset():
    guard = Wave284LobQueueExhaustionDepletionGuard()

    # Boolean depth triggers fail-closed
    guard.record_queue_state(True, 5.0)
    assert guard.is_entry_blocked()
    assert "CORRUPTED" in guard.get_status()["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked()

    # Negative depth triggers fail-closed
    guard.update(-1.0, 5.0)
    assert guard.is_entry_blocked()

    guard.reset()
    assert not guard.is_entry_blocked()


# ----------------------------------------------------------------------
# Wave 285 Tests: Trade Flow Signed Volume Momentum Guard
# ----------------------------------------------------------------------

def test_wave285_balanced_flow_no_block():
    guard = Wave285TradeFlowSignedVolumeMomentumGuard(
        max_signed_ratio=0.80,
        min_total_volume=15.0,
        min_trades=15,
    )

    # Balanced back-and-forth trades (1 buy of 1.0, 1 sell of 1.0)
    for _ in range(10):
        guard.record_signed_trade(trade_sign=1, volume_lots=1.0)
        guard.record_signed_trade(trade_sign=-1, volume_lots=1.0)
        assert not guard.is_entry_blocked()

    metrics = guard.get_flow_momentum_metrics()
    assert metrics["signed_volume_ratio"] <= 0.20
    assert not metrics["is_blocked"]


def test_wave285_directional_imbalance_blocks():
    guard = Wave285TradeFlowSignedVolumeMomentumGuard(
        max_signed_ratio=0.80,
        min_total_volume=15.0,
        min_trades=15,
        cooldown_seconds=45.0,
    )

    # Directly inject precomputed directional flow metrics (ratio = 0.88, total volume = 22.0)
    guard.record_flow_metrics(signed_ratio=0.88, total_volume=22.0, sample_count=16)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    metrics = guard.get_status()
    assert metrics["is_blocked"]
    assert "DIRECTIONAL_SIGNED_IMBALANCE" in metrics["last_block_reason"]


def test_wave285_acute_volume_avalanche_blocks():
    guard = Wave285TradeFlowSignedVolumeMomentumGuard(
        acute_streak_volume=12.0,
        acute_streak_len=6,
        cooldown_seconds=45.0,
    )

    # 6 consecutive buy trades of 2.50 lots each (total streak volume = 15.0 lots)
    for _ in range(6):
        guard.record_signed_trade(trade_sign=1, volume_lots=2.50)

    assert guard.is_entry_blocked()
    metrics = guard.get_flow_momentum_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_VOLUME_AVALANCHE" in metrics["last_block_reason"]


def test_wave285_insufficient_samples_no_block():
    guard = Wave285TradeFlowSignedVolumeMomentumGuard(
        max_signed_ratio=0.80,
        min_total_volume=15.0,
        min_trades=15,
    )

    # High ratio (1.00) but total volume only 8.0 (< 15.0 min_total_volume)
    for _ in range(8):
        guard.record_signed_trade(trade_sign=1, volume_lots=1.0)

    assert not guard.is_entry_blocked()


def test_wave285_input_validation_and_reset():
    guard = Wave285TradeFlowSignedVolumeMomentumGuard()

    # Invalid trade sign (e.g. 0 or 2) triggers fail-closed
    guard.record_signed_trade(trade_sign=0, volume_lots=1.0)
    assert guard.is_entry_blocked()
    assert "CORRUPTED" in guard.get_status()["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked()

    # Boolean trade sign triggers fail-closed
    guard.record_signed_trade(True, 1.0)
    assert guard.is_entry_blocked()

    guard.reset()
    assert not guard.is_entry_blocked()
