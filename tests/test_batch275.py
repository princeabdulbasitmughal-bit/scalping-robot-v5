"""
tests/test_batch275.py
----------------------
Unit tests for Batch 275:
  - Wave 316: Wave316LobSpreadElasticityGuard [Wave 316 - 3,000 Tests Milestone]
  - Wave 317: Wave317TradeVolumeSynchronicityGuard [Wave 317 - 3,000 Tests Milestone]
"""

import math
import time
import pytest

from wave316_lob_spread_elasticity_guard import Wave316LobSpreadElasticityGuard
from wave317_trade_volume_synchronicity_guard import Wave317TradeVolumeSynchronicityGuard


# ----------------------------------------------------------------------
# Wave 316 Tests: LOB Spread Depth-Elasticity & Brittle Liquidity Guard
# ----------------------------------------------------------------------

def test_wave316_resilient_spread_elasticity_no_block():
    guard = Wave316LobSpreadElasticityGuard(
        max_spread_elasticity=3.20,
        min_samples=10,
    )

    # 12 updates of resilient quoting: depth drops 1.0 lot from 50.0, spread widens only 0.02 bps (low elasticity)
    spread = 1.0
    depth = 50.0
    for _ in range(12):
        spread += 0.02
        depth -= 1.0
        guard.record_book_state(spread_bps=spread, inside_depth_lots=depth)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_elasticity_metrics()
    assert metrics["mean_elasticity"] < 2.0
    assert not metrics["is_blocked"]


def test_wave316_brittle_spread_elasticity_blocks():
    guard = Wave316LobSpreadElasticityGuard(
        max_spread_elasticity=3.20,
        min_elevated_spread_bps=2.20,
        min_samples=10,
        cooldown_seconds=45.0,
    )

    # Directly inject precomputed brittle elasticity metrics (elasticity = 3.85, mean_spread = 2.80 bps)
    guard.record_elasticity_metrics(spread_elasticity=3.85, mean_spread_bps=2.80, sample_count=14)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    status = guard.get_status()
    assert status["is_blocked"]
    assert "BRITTLE_SPREAD_ELASTICITY_SURGE" in status["last_block_reason"]


def test_wave316_acute_brittle_spread_blowout_blocks():
    guard = Wave316LobSpreadElasticityGuard(
        acute_elasticity=4.50,
        acute_spread_jump_bps=3.00,
        acute_max_sweep_lots=1.50,
        cooldown_seconds=45.0,
    )

    # Baseline book: spread = 1.0 bps, depth = 5.0 lots
    guard.record_book_state(spread_bps=1.0, inside_depth_lots=5.0)
    assert not guard.is_entry_blocked()

    # Small sweep of 0.5 lots causes massive spread gap from 1.0 to 4.5 bps (+3.5 bps)
    guard.record_book_state(spread_bps=4.5, inside_depth_lots=4.5)

    assert guard.is_entry_blocked()
    metrics = guard.get_elasticity_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_BRITTLE_SPREAD_BLOWOUT" in metrics["last_block_reason"]


def test_wave316_direct_elasticity_metrics():
    guard = Wave316LobSpreadElasticityGuard(
        max_spread_elasticity=3.20,
        cooldown_seconds=45.0,
    )

    # Below threshold (elasticity = 1.80)
    guard.record_elasticity_metrics(spread_elasticity=1.80, mean_spread_bps=2.0, sample_count=12)
    assert not guard.is_entry_blocked()

    # Above threshold (elasticity = 4.00)
    guard.record_elasticity_metrics(spread_elasticity=4.00, mean_spread_bps=2.5, sample_count=12)
    assert guard.is_entry_blocked()
    assert "BRITTLE_SPREAD_ELASTICITY_SURGE" in guard.get_status()["last_block_reason"]


def test_wave316_fail_closed_and_reset():
    guard = Wave316LobSpreadElasticityGuard(cooldown_seconds=45.0)

    # Corrupted inputs: zero/negative spread, negative depth, NaN, Inf, bool, None
    for bad_s, bad_d in [(0.0, 5.0), (-1.0, 5.0), (1.0, -1.0), (float("nan"), 5.0), (1.0, float("inf")), (True, 5.0), (None, 5.0)]:
        guard.record_book_state(bad_s, bad_d)
        assert guard.is_entry_blocked()
        assert "CORRUPTED_BOOK_STATE_INPUT" in guard.get_status()["last_block_reason"]
        guard.reset()
        assert not guard.is_entry_blocked()

    # Update alias check
    guard.update(1.2, 5.0)
    assert not guard.is_entry_blocked()


# ----------------------------------------------------------------------
# Wave 317 Tests: Trade Volume Synchronicity Guard
# ----------------------------------------------------------------------

def test_wave317_noisy_volume_flow_no_block():
    guard = Wave317TradeVolumeSynchronicityGuard(
        max_synchronicity_r2=0.82,
        min_samples=12,
    )

    # Heterogeneous noisy trading with modest correlation (R^2 ~ 0.25)
    events = [
        (1, 1.0, 0.2), (-1, 1.2, 0.1), (1, 1.5, 0.8), (-1, 0.8, -0.4),
        (1, 0.5, -0.1), (-1, 1.1, -0.3), (1, 1.3, 0.4), (-1, 1.4, -0.2),
        (1, 0.9, 0.3), (-1, 1.0, 0.0), (1, 1.2, 0.5), (-1, 0.7, -0.6)
    ]
    for s, v, d in events:
        guard.record_trade_dislocation(sign=s, volume_lots=v, price_dislocation_bps=d)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_synchronicity_metrics()
    assert metrics["synchronicity_r2"] < 0.75
    assert not metrics["is_blocked"]


def test_wave317_hyper_synchronous_impact_blocks():
    guard = Wave317TradeVolumeSynchronicityGuard(
        max_synchronicity_r2=0.82,
        min_samples=12,
        min_total_volume=15.0,
        cooldown_seconds=45.0,
    )

    # Directly inject precomputed hyper-synchronous metrics (R^2 = 0.92 >= 0.82, vol = 25.0)
    guard.record_synchronicity_metrics(r_squared=0.92, total_volume=25.0, sample_count=15)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    status = guard.get_status()
    assert status["is_blocked"]
    assert "HYPER_SYNCHRONOUS_IMPACT" in status["last_block_reason"]


def test_wave317_acute_synchronized_whale_blocks():
    guard = Wave317TradeVolumeSynchronicityGuard(
        acute_whale_volume=15.0,
        acute_price_dislocation_bps=4.00,
        cooldown_seconds=45.0,
    )

    # Acute massive whale sweep of 20.0 lots moving price 5.5 bps
    guard.record_trade_dislocation(sign=1, volume_lots=20.0, price_dislocation_bps=5.50)

    assert guard.is_entry_blocked()
    metrics = guard.get_synchronicity_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_SYNCHRONIZED_WHALE" in metrics["last_block_reason"]


def test_wave317_direct_synchronicity_metrics():
    guard = Wave317TradeVolumeSynchronicityGuard(
        max_synchronicity_r2=0.82,
        cooldown_seconds=45.0,
    )

    # Below threshold (R^2 = 0.50)
    guard.record_synchronicity_metrics(r_squared=0.50, total_volume=20.0, sample_count=14)
    assert not guard.is_entry_blocked()

    # Above threshold (R^2 = 0.88)
    guard.record_synchronicity_metrics(r_squared=0.88, total_volume=20.0, sample_count=14)
    assert guard.is_entry_blocked()
    assert "HYPER_SYNCHRONOUS_IMPACT" in guard.get_status()["last_block_reason"]


def test_wave317_fail_closed_and_reset():
    guard = Wave317TradeVolumeSynchronicityGuard(cooldown_seconds=45.0)

    # String parsing
    guard.record_trade_dislocation("BUY", 1.0, 0.5)
    assert not guard.is_entry_blocked()
    guard.record_trade_dislocation("SELL", 1.0, -0.5)
    assert not guard.is_entry_blocked()

    # Corrupted inputs: zero/negative volume, NaN, Inf, None
    for bad_s, bad_v, bad_d in [(1, 0.0, 0.5), (1, -1.0, 0.5), (1, float("nan"), 0.5), (None, 1.0, 0.5)]:
        guard.record_trade_dislocation(bad_s, bad_v, bad_d)
        assert guard.is_entry_blocked()
        assert ("CORRUPTED_DISLOCATION_INPUT" in guard.get_status()["last_block_reason"] or 
                "CORRUPTED_SIGN_INPUT" in guard.get_status()["last_block_reason"])
        guard.reset()
        assert not guard.is_entry_blocked()

    # Update alias check
    guard.update(1, 1.0, 0.2)
    assert not guard.is_entry_blocked()
