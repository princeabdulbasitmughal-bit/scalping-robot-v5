"""
tests/test_batch271.py
----------------------
Unit tests for Batch 271:
  - Wave 308: Wave308LobPriceImpactPowerLawGuard
  - Wave 309: Wave309TradeVolumeZipfTailGuard
"""

import math
import time
import pytest

from wave308_lob_price_impact_power_law_guard import Wave308LobPriceImpactPowerLawGuard
from wave309_trade_volume_zipf_tail_guard import Wave309TradeVolumeZipfTailGuard


# ----------------------------------------------------------------------
# Wave 308 Tests: LOB Price Impact Power-Law Exponent Guard
# ----------------------------------------------------------------------

def test_wave308_sublinear_concave_impact_no_block():
    guard = Wave308LobPriceImpactPowerLawGuard(
        max_impact_exponent=1.15,
        min_samples=10,
    )

    # Square-root concave price impact: Delta p ~= 1.5 * sqrt(V)
    # delta ~= 0.50
    volumes = [0.2, 0.5, 1.0, 2.0, 3.0, 0.4, 0.8, 1.5, 2.5, 4.0, 1.2, 0.6]
    for v in volumes:
        imp = 1.2 * math.sqrt(v)
        guard.record_trade_impact(volume_lots=v, impact_bps=imp)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_impact_metrics()
    assert 0.35 <= metrics["exponent_delta"] <= 0.70
    assert not metrics["is_blocked"]


def test_wave308_superlinear_impact_surge_blocks():
    guard = Wave308LobPriceImpactPowerLawGuard(
        max_impact_exponent=1.15,
        min_samples=10,
        min_mean_impact_bps=2.50,
        cooldown_seconds=45.0,
    )

    # Directly inject precomputed super-linear exponent (delta = 1.35, mean impact = 3.5 bps)
    guard.record_impact_metrics(exponent_delta=1.35, mean_impact_bps=3.50, sample_count=12)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    status = guard.get_status()
    assert status["is_blocked"]
    assert "SUPER_LINEAR_IMPACT_SURGE" in status["last_block_reason"]


def test_wave308_acute_impact_blowout_blocks():
    guard = Wave308LobPriceImpactPowerLawGuard(
        acute_impact_bps=4.50,
        acute_max_volume_lots=2.00,
        cooldown_seconds=45.0,
    )

    # Small trade of 0.5 lots causes blowout price gap of 5.50 bps
    guard.record_trade_impact(volume_lots=0.50, impact_bps=5.50)

    assert guard.is_entry_blocked()
    metrics = guard.get_impact_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_IMPACT_BLOWOUT" in metrics["last_block_reason"]


def test_wave308_direct_impact_metrics():
    guard = Wave308LobPriceImpactPowerLawGuard(
        max_impact_exponent=1.15,
        cooldown_seconds=45.0,
    )

    # Below threshold (delta = 0.60)
    guard.record_impact_metrics(exponent_delta=0.60, mean_impact_bps=1.5, sample_count=12)
    assert not guard.is_entry_blocked()

    # Above threshold (delta = 1.40)
    guard.record_impact_metrics(exponent_delta=1.40, mean_impact_bps=3.0, sample_count=12)
    assert guard.is_entry_blocked()
    assert "SUPER_LINEAR_IMPACT_SURGE" in guard.get_status()["last_block_reason"]


def test_wave308_fail_closed_and_reset():
    guard = Wave308LobPriceImpactPowerLawGuard(cooldown_seconds=45.0)

    # Corrupted inputs: zero/negative volume, negative impact, NaN, Inf, bool
    for bad_v, bad_imp in [(0.0, 1.0), (-1.0, 1.0), (1.0, -0.5), (float("nan"), 1.0), (1.0, float("inf")), (True, 1.0)]:
        guard.record_trade_impact(bad_v, bad_imp)
        assert guard.is_entry_blocked()
        assert "CORRUPTED_IMPACT_INPUT" in guard.get_status()["last_block_reason"]
        guard.reset()
        assert not guard.is_entry_blocked()

    # Update alias check
    guard.update(1.0, 0.5)
    assert not guard.is_entry_blocked()


# ----------------------------------------------------------------------
# Wave 309 Tests: Trade Volume Zipf / Pareto Tail Exponent Guard
# ----------------------------------------------------------------------

def test_wave309_thin_moderate_pareto_tail_no_block():
    guard = Wave309TradeVolumeZipfTailGuard(
        min_pareto_index=0.95,
        min_samples=15,
    )

    # Moderately thin Pareto / log-normal trade sizes with zeta around 1.5 - 2.0
    normal_trades = [
        0.5, 0.8, 1.2, 0.3, 0.6, 1.5, 0.4, 2.0, 0.9, 1.1,
        0.7, 1.8, 0.5, 1.0, 0.8, 1.4, 0.6, 2.2, 1.3
    ]
    for s in normal_trades:
        guard.record_trade_size(s)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_tail_metrics()
    assert metrics["tail_index_zeta"] >= 1.0
    assert not metrics["is_blocked"]


def test_wave309_heavy_tail_whale_regime_blocks():
    guard = Wave309TradeVolumeZipfTailGuard(
        min_pareto_index=0.95,
        min_samples=15,
        cooldown_seconds=45.0,
    )

    # Direct injection of heavy-tail regime with zeta = 0.75 (< 0.95)
    guard.record_tail_metrics(tail_index_zeta=0.75, median_size=1.0, sample_count=18)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    status = guard.get_status()
    assert status["is_blocked"]
    assert "HEAVY_TAIL_WHALE_REGIME" in status["last_block_reason"]


def test_wave309_acute_whale_infiltration_blocks():
    guard = Wave309TradeVolumeZipfTailGuard(
        acute_whale_lots=18.0,
        acute_whale_ratio=15.0,
        cooldown_seconds=45.0,
    )

    # Baseline moderate trades with median = 0.80
    for s in [0.5, 0.8, 1.0, 0.7, 0.9]:
        guard.record_trade_size(s)
        assert not guard.is_entry_blocked()

    # Acute whale dump of 25.0 lots (31x median size)
    guard.record_trade_size(25.0)

    assert guard.is_entry_blocked()
    metrics = guard.get_tail_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_WHALE_INFILTRATION" in metrics["last_block_reason"]


def test_wave309_direct_tail_metrics():
    guard = Wave309TradeVolumeZipfTailGuard(
        min_pareto_index=0.95,
        cooldown_seconds=45.0,
    )

    # Below threshold (safe tail index zeta = 1.65)
    guard.record_tail_metrics(tail_index_zeta=1.65, median_size=0.8, sample_count=16)
    assert not guard.is_entry_blocked()

    # Above threshold (dangerous tail index zeta = 0.80)
    guard.record_tail_metrics(tail_index_zeta=0.80, median_size=0.8, sample_count=16)
    assert guard.is_entry_blocked()
    assert "HEAVY_TAIL_WHALE_REGIME" in guard.get_status()["last_block_reason"]


def test_wave309_fail_closed_and_reset():
    guard = Wave309TradeVolumeZipfTailGuard(cooldown_seconds=45.0)

    # Corrupted inputs: None, bool, NaN, Inf, zero, negative
    for bad_s in [None, True, False, float("nan"), float("inf"), 0.0, -5.0]:
        guard.record_trade_size(bad_s)
        assert guard.is_entry_blocked()
        assert "CORRUPTED_TRADE_SIZE_INPUT" in guard.get_status()["last_block_reason"]
        guard.reset()
        assert not guard.is_entry_blocked()

    # Update alias check
    guard.update(1.2)
    assert not guard.is_entry_blocked()
