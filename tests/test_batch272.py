"""
tests/test_batch272.py
----------------------
Unit tests for Batch 272:
  - Wave 310: Wave310LobQueueHalfLifeDecayGuard [Wave 310 Milestone]
  - Wave 311: Wave311TradeFlowSignedVolumeAsymmetryGuard
"""

import math
import time
import pytest

from wave310_lob_queue_half_life_decay_guard import Wave310LobQueueHalfLifeDecayGuard
from wave311_trade_flow_signed_volume_asymmetry_guard import Wave311TradeFlowSignedVolumeAsymmetryGuard


# ----------------------------------------------------------------------
# Wave 310 Tests: LOB Queue Resting Half-Life & Stale Liquidity Decay Guard
# ----------------------------------------------------------------------

def test_wave310_healthy_queue_half_life_no_block():
    guard = Wave310LobQueueHalfLifeDecayGuard(
        min_half_life_sec=0.15,
        max_half_life_sec=35.0,
        min_samples=8,
    )

    # 10 updates of healthy liquid queue dynamics:
    # cancel_rate = 0.15 /s, fill_rate = 0.05 /s -> hazard = 0.20 /s -> half_life ~= 3.46s
    for _ in range(10):
        guard.record_queue_hazard(cancel_rate=0.15, fill_rate=0.05, spread_bps=1.0)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_half_life_metrics()
    assert 2.0 <= metrics["mean_half_life_sec"] <= 5.0
    assert not metrics["is_blocked"]


def test_wave310_toxic_quote_flickering_blocks():
    guard = Wave310LobQueueHalfLifeDecayGuard(
        min_half_life_sec=0.15,
        min_samples=8,
        cooldown_seconds=45.0,
    )

    # HFT quote flickering: cancel rate = 10.0 /s, fill_rate = 0.1 /s -> hazard = 10.1 -> half_life = 0.068s (< 0.15s)
    for _ in range(9):
        guard.record_queue_hazard(cancel_rate=10.0, fill_rate=0.1, spread_bps=1.0)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    status = guard.get_status()
    assert status["is_blocked"]
    assert "TOXIC_QUOTE_FLICKERING" in status["last_block_reason"]


def test_wave310_stale_liquidity_mirage_blocks():
    guard = Wave310LobQueueHalfLifeDecayGuard(
        max_half_life_sec=35.0,
        min_stale_spread_bps=2.50,
        min_samples=8,
        cooldown_seconds=45.0,
    )

    # Stagnant abandoned quotes: cancel rate = 0.005, fill_rate = 0.005 -> hazard = 0.01 -> half_life = 69.3s (> 35s)
    # spread = 3.50 bps (> 2.50 bps)
    for _ in range(9):
        guard.record_queue_hazard(cancel_rate=0.005, fill_rate=0.005, spread_bps=3.50)

    assert guard.is_entry_blocked()
    metrics = guard.get_half_life_metrics()
    assert metrics["is_blocked"]
    assert "STALE_LIQUIDITY_MIRAGE" in metrics["last_block_reason"]


def test_wave310_acute_phantom_cancel_burst_blocks():
    guard = Wave310LobQueueHalfLifeDecayGuard(
        acute_cancel_rate=25.0,
        acute_max_fill_rate=0.50,
        cooldown_seconds=45.0,
    )

    # Acute burst: cancel rate spikes to 30.0 cancels/s with zero fills
    guard.record_queue_hazard(cancel_rate=30.0, fill_rate=0.0, spread_bps=1.50)

    assert guard.is_entry_blocked()
    status = guard.get_status()
    assert status["is_blocked"]
    assert "ACUTE_PHANTOM_CANCEL_BURST" in status["last_block_reason"]


def test_wave310_fail_closed_and_reset():
    guard = Wave310LobQueueHalfLifeDecayGuard(cooldown_seconds=45.0)

    # Corrupted inputs: negative, NaN, Inf, bool, None
    for bad_c, bad_f in [(-1.0, 0.5), (float("nan"), 0.5), (0.5, float("inf")), (True, 0.5), (None, 0.5)]:
        guard.record_queue_hazard(bad_c, bad_f)
        assert guard.is_entry_blocked()
        assert "CORRUPTED_HAZARD_INPUT" in guard.get_status()["last_block_reason"]
        guard.reset()
        assert not guard.is_entry_blocked()

    # Update alias check
    guard.update(0.5, 0.2, spread_bps=1.0)
    assert not guard.is_entry_blocked()


# ----------------------------------------------------------------------
# Wave 311 Tests: Trade Flow Signed Volume Asymmetry Guard
# ----------------------------------------------------------------------

def test_wave311_balanced_volume_flow_no_block():
    guard = Wave311TradeFlowSignedVolumeAsymmetryGuard(
        max_volume_asymmetry=0.78,
        min_samples=12,
        min_total_volume=15.0,
    )

    # 14 balanced buy and sell trades of 1.0 - 2.0 lots
    balanced_trades = [
        (1, 1.2), (-1, 1.0), (1, 1.5), (-1, 1.4), (1, 1.1),
        (-1, 1.3), (1, 1.0), (-1, 1.2), (1, 1.4), (-1, 1.1),
        (1, 1.3), (-1, 1.5), (1, 1.2), (-1, 1.0)
    ]
    for sign, vol in balanced_trades:
        guard.record_signed_trade(sign=sign, volume_lots=vol)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_asymmetry_metrics()
    assert abs(metrics["volume_asymmetry"]) < 0.35
    assert not metrics["is_blocked"]


def test_wave311_directional_volume_avalanche_blocks():
    guard = Wave311TradeFlowSignedVolumeAsymmetryGuard(
        max_volume_asymmetry=0.78,
        min_samples=12,
        min_total_volume=15.0,
        cooldown_seconds=45.0,
    )

    # Overwhelming buying avalanche: 13 buys of 2.0 lots (26.0 lots total) and 1 sell of 0.2 lots
    # Asymmetry = (26.0 - 0.2) / 26.2 = 0.985 (> 0.78)
    for _ in range(12):
        guard.record_signed_trade(sign=1, volume_lots=2.0)
    guard.record_signed_trade(sign=-1, volume_lots=0.2)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    status = guard.get_status()
    assert status["is_blocked"]
    assert "DIRECTIONAL_VOLUME_AVALANCHE" in status["last_block_reason"]


def test_wave311_acute_volume_surge_blocks():
    guard = Wave311TradeFlowSignedVolumeAsymmetryGuard(
        acute_surge_volume=12.0,
        cooldown_seconds=45.0,
    )

    # Unilateral massive block dump of 15.0 lots
    guard.record_signed_trade(sign=-1, volume_lots=15.0)

    assert guard.is_entry_blocked()
    metrics = guard.get_asymmetry_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_VOLUME_SURGE" in metrics["last_block_reason"]


def test_wave311_direct_asymmetry_metrics():
    guard = Wave311TradeFlowSignedVolumeAsymmetryGuard(
        max_volume_asymmetry=0.78,
        cooldown_seconds=45.0,
    )

    # Below threshold (asym = 0.50)
    guard.record_asymmetry_metrics(volume_asymmetry=0.50, total_volume=20.0, sample_count=14)
    assert not guard.is_entry_blocked()

    # Above threshold (asym = -0.85)
    guard.record_asymmetry_metrics(volume_asymmetry=-0.85, total_volume=22.0, sample_count=14)
    assert guard.is_entry_blocked()
    assert "DIRECTIONAL_VOLUME_AVALANCHE" in guard.get_status()["last_block_reason"]


def test_wave311_fail_closed_and_reset():
    guard = Wave311TradeFlowSignedVolumeAsymmetryGuard(cooldown_seconds=45.0)

    # String parsing
    guard.record_signed_trade("BUY", 1.0)
    assert not guard.is_entry_blocked()
    guard.record_signed_trade("SELL", 1.0)
    assert not guard.is_entry_blocked()

    # Corrupted inputs: zero/negative volume, NaN, Inf, None
    for bad_s, bad_v in [(1, 0.0), (1, -2.0), (1, float("nan")), (1, float("inf")), (None, 1.0)]:
        guard.record_signed_trade(bad_s, bad_v)
        assert guard.is_entry_blocked()
        assert ("CORRUPTED_VOLUME_INPUT" in guard.get_status()["last_block_reason"] or 
                "CORRUPTED_SIGN_INPUT" in guard.get_status()["last_block_reason"])
        guard.reset()
        assert not guard.is_entry_blocked()

    # Update alias check
    guard.update(1, 1.0)
    assert not guard.is_entry_blocked()
