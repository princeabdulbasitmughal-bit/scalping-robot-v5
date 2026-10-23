"""
tests/test_batch276.py
----------------------
Unit tests for Batch 276:
  - Wave 318: Wave318LobQueuingFrictionDragGuard
  - Wave 319: Wave319TradeArrivalVolatilitySignatureGuard
"""

import math
import time
import pytest

from wave318_lob_queuing_friction_drag_guard import Wave318LobQueuingFrictionDragGuard
from wave319_trade_arrival_volatility_signature_guard import Wave319TradeArrivalVolatilitySignatureGuard


# ----------------------------------------------------------------------
# Wave 318 Tests: LOB Queuing Friction & Slippage Drag Guard
# ----------------------------------------------------------------------

def test_wave318_normal_queuing_friction_no_block():
    guard = Wave318LobQueuingFrictionDragGuard(
        max_friction_drag_bps=4.20,
        min_samples=10,
    )

    # 12 updates of healthy liquid quoting: bid 99.99, ask 100.01 (spread = 2.0 bps, half-spread = 1.0 bps)
    # inside depth = 2.0 + 2.0 = 4.0 lots -> penalty = 1 + 1.0 / 4.0 = 1.25 -> drag = 1.25 bps (< 4.20)
    for _ in range(12):
        guard.record_lob_friction(bid=99.99, ask=100.01, bid_depth=2.0, ask_depth=2.0)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_friction_metrics()
    assert metrics["mean_friction_drag_bps"] <= 2.00
    assert not metrics["is_blocked"]


def test_wave318_friction_drag_surge_blocks():
    guard = Wave318LobQueuingFrictionDragGuard(
        max_friction_drag_bps=4.20,
        min_spread_bps=2.20,
        min_samples=10,
        cooldown_seconds=45.0,
    )

    # Directly inject precomputed high friction drag metrics (drag = 4.85 bps, spread = 2.60 bps)
    guard.record_friction_metrics(friction_drag_bps=4.85, spread_bps=2.60, sample_count=14)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    status = guard.get_status()
    assert status["is_blocked"]
    assert "FRICTION_DRAG_SURGE" in status["last_block_reason"]


def test_wave318_acute_queuing_friction_shock_blocks():
    guard = Wave318LobQueuingFrictionDragGuard(
        acute_friction_drag_bps=7.00,
        cooldown_seconds=45.0,
    )

    # Wide spread (4.0 bps, half-spread = 2.0 bps) with thin depth (0.10 + 0.10 = 0.20 lots)
    # penalty = 1.0 + 1.0 / 0.20 = 6.0 -> drag = 2.0 * 6.0 = 12.0 bps (>= 7.00 bps)
    guard.record_lob_friction(bid=99.98, ask=100.02, bid_depth=0.10, ask_depth=0.10)

    assert guard.is_entry_blocked()
    metrics = guard.get_friction_metrics()
    assert metrics["is_blocked"]
    assert ("ACUTE_QUEUING_FRICTION_SHOCK" in metrics["last_block_reason"] or 
            "ACUTE_QUEUE_EVAPORATION" in metrics["last_block_reason"])


def test_wave318_acute_queue_evaporation_blocks():
    guard = Wave318LobQueuingFrictionDragGuard(
        acute_min_depth_lots=0.15,
        acute_min_spread_bps=3.00,
        cooldown_seconds=45.0,
    )

    # Depth is completely evaporated (0.05 + 0.05 = 0.10 lots <= 0.15 lots) with spread 3.50 bps
    guard.record_lob_friction(bid=99.98, ask=100.015, bid_depth=0.05, ask_depth=0.05)

    assert guard.is_entry_blocked()
    status = guard.get_status()
    assert status["is_blocked"]
    assert ("ACUTE_QUEUE_EVAPORATION" in status["last_block_reason"] or 
            "ACUTE_QUEUING_FRICTION_SHOCK" in status["last_block_reason"])


def test_wave318_fail_closed_and_reset():
    guard = Wave318LobQueuingFrictionDragGuard(cooldown_seconds=45.0)

    # Corrupted inputs: inverted quotes, non-positive bid, negative depth, NaN, Inf, bool
    for bad_args in [
        (100.05, 100.0, 1.0, 1.0),
        (-10.0, 100.0, 1.0, 1.0),
        (99.0, 100.0, -0.5, 1.0),
        (float("nan"), 100.0, 1.0, 1.0),
        (99.0, float("inf"), 1.0, 1.0),
        (True, 100.0, 1.0, 1.0),
    ]:
        guard.record_lob_friction(*bad_args)
        assert guard.is_entry_blocked()
        assert "CORRUPTED_LOB_FRICTION_INPUT" in guard.get_status()["last_block_reason"]
        guard.reset()
        assert not guard.is_entry_blocked()

    # Update alias check
    guard.update(99.99, 100.01, 2.0, 2.0)
    assert not guard.is_entry_blocked()


# ----------------------------------------------------------------------
# Wave 319 Tests: Trade Arrival Volatility Signature Guard
# ----------------------------------------------------------------------

def test_wave319_calm_tick_volatility_no_block():
    guard = Wave319TradeArrivalVolatilitySignatureGuard(
        max_tick_volatility_bps=2.80,
        min_samples=15,
    )

    # 18 returns of calm trading with small fluctuations (< 1.0 bps)
    for i in range(18):
        ret = 0.50 * (1 if i % 2 == 0 else -1)
        guard.record_return(ret)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_volatility_metrics()
    assert metrics["tick_volatility_bps"] < 1.00
    assert not metrics["is_blocked"]


def test_wave319_tick_volatility_surge_blocks():
    guard = Wave319TradeArrivalVolatilitySignatureGuard(
        max_tick_volatility_bps=2.80,
        min_samples=15,
        cooldown_seconds=45.0,
    )

    # Directly inject precomputed high volatility metrics (RV = 3.50 bps/trade)
    guard.record_volatility_metrics(tick_volatility_bps=3.50, max_jump_bps=2.0, sample_count=18)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    status = guard.get_status()
    assert status["is_blocked"]
    assert "TICK_VOLATILITY_SURGE" in status["last_block_reason"]


def test_wave319_acute_price_dislocation_jump_blocks():
    guard = Wave319TradeArrivalVolatilitySignatureGuard(
        acute_price_jump_bps=4.50,
        cooldown_seconds=45.0,
    )

    # Moderate trades
    for r in [0.5, -0.4, 0.6, -0.2]:
        guard.record_return(r)
        assert not guard.is_entry_blocked()

    # Acute flash leap of 5.80 bps
    guard.record_return(5.80)

    assert guard.is_entry_blocked()
    metrics = guard.get_volatility_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_PRICE_DISLOCATION_JUMP" in metrics["last_block_reason"]


def test_wave319_direct_volatility_metrics():
    guard = Wave319TradeArrivalVolatilitySignatureGuard(
        max_tick_volatility_bps=2.80,
        cooldown_seconds=45.0,
    )

    # Below threshold (RV = 1.20)
    guard.record_volatility_metrics(tick_volatility_bps=1.20, max_jump_bps=1.5, sample_count=16)
    assert not guard.is_entry_blocked()

    # Above threshold (RV = 3.20)
    guard.record_volatility_metrics(tick_volatility_bps=3.20, max_jump_bps=2.0, sample_count=16)
    assert guard.is_entry_blocked()
    assert "TICK_VOLATILITY_SURGE" in guard.get_status()["last_block_reason"]


def test_wave319_fail_closed_and_reset():
    guard = Wave319TradeArrivalVolatilitySignatureGuard(cooldown_seconds=45.0)

    # Corrupted inputs: zero/negative price, NaN, Inf, bool
    for bad_p in [0.0, -10.0, float("nan"), float("inf"), True]:
        guard.record_trade_price(bad_p)
        assert guard.is_entry_blocked()
        assert "CORRUPTED_PRICE_INPUT" in guard.get_status()["last_block_reason"]
        guard.reset()
        assert not guard.is_entry_blocked()

    # Price return derivation check
    guard.record_trade_price(100.0)
    guard.record_trade_price(100.01)  # +1.0 bps return
    assert not guard.is_entry_blocked()

    # Update alias check
    guard.update(100.02)
    assert not guard.is_entry_blocked()
