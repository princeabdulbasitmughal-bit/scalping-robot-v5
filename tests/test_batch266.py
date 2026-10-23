"""
tests/test_batch266.py
----------------------
Unit tests for Batch 266:
  - Wave 298: Wave298LobOrderFlowToxicityMomentumGuard
  - Wave 299: Wave299TradeVolumeParetoRatioGuard
"""

import math
import time
import pytest

from wave298_lob_order_flow_toxicity_momentum_guard import Wave298LobOrderFlowToxicityMomentumGuard
from wave299_trade_volume_pareto_ratio_guard import Wave299TradeVolumeParetoRatioGuard


# ----------------------------------------------------------------------
# Wave 298 Tests: LOB Net OFI Momentum & Toxic Adverse Selection Guard
# ----------------------------------------------------------------------

def test_wave298_balanced_ofi_no_block():
    guard = Wave298LobOrderFlowToxicityMomentumGuard(
        max_ofi_momentum=0.80,
        min_total_flow=12.0,
        min_samples=12,
        acute_surge_flow=15.0,
    )

    # Balanced alternating order flow: +1.0, -1.0, +1.0, -1.0 lots
    t = 100.0
    for _ in range(15):
        guard.record_ofi(1.0, ts=t)
        t += 1.0
        guard.record_ofi(-1.0, ts=t)
        t += 1.0
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_ofi_metrics()
    assert abs(metrics["ofi_momentum"]) <= 0.20
    assert not metrics["is_blocked"]


def test_wave298_ofi_momentum_bias_blocks():
    guard = Wave298LobOrderFlowToxicityMomentumGuard(
        max_ofi_momentum=0.80,
        min_total_flow=12.0,
        min_samples=12,
        cooldown_seconds=45.0,
    )

    # Directly inject precomputed persistent OFI momentum metric
    guard.record_ofi_metrics(ofi_momentum=0.88, total_flow=18.0, sample_count=14)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    metrics = guard.get_status()
    assert metrics["is_blocked"]
    assert "OFI_MOMENTUM_BIAS" in metrics["last_block_reason"]


def test_wave298_acute_surge_burst_blocks():
    guard = Wave298LobOrderFlowToxicityMomentumGuard(
        acute_surge_flow=15.0,
        acute_surge_window_sec=0.50,
        cooldown_seconds=45.0,
    )

    # Single massive 18.0 lot net sweep in 0.10s
    guard.record_ofi(18.0, ts=10.0)

    assert guard.is_entry_blocked()
    metrics = guard.get_ofi_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_OFI_SURGE_BURST" in metrics["last_block_reason"]


def test_wave298_insufficient_samples_no_block():
    guard = Wave298LobOrderFlowToxicityMomentumGuard(
        max_ofi_momentum=0.80,
        min_total_flow=12.0,
        min_samples=12,
    )

    # High momentum (1.00) but total flow only 5.0 lots (< 12.0 min_total_flow)
    guard.record_ofi_metrics(ofi_momentum=1.00, total_flow=5.0, sample_count=5)

    assert not guard.is_entry_blocked()


def test_wave298_input_validation_and_reset():
    guard = Wave298LobOrderFlowToxicityMomentumGuard()

    # Boolean OFI triggers fail-closed
    guard.record_ofi(True)
    assert guard.is_entry_blocked()
    assert "CORRUPTED" in guard.get_status()["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked()

    # NaN momentum triggers fail-closed
    guard.record_ofi_metrics(float("nan"))
    assert guard.is_entry_blocked()

    guard.reset()
    assert not guard.is_entry_blocked()


# ----------------------------------------------------------------------
# Wave 299 Tests: Trade Volume 80/20 Pareto Concentration Ratio Guard
# ----------------------------------------------------------------------

def test_wave299_distributed_volume_no_block():
    guard = Wave299TradeVolumeParetoRatioGuard(
        max_pareto_ratio=0.82,
        min_total_volume=20.0,
        min_trades=15,
        acute_block_share=0.50,
    )

    # Well distributed trade sizes (1.0, 1.2, 1.5, 0.8, 1.3 lots)
    volumes = [1.0, 1.2, 1.5, 0.8, 1.3, 1.1, 1.4, 0.9, 1.6, 1.0] * 2
    for v in volumes:
        guard.record_trade_volume(v)
        assert not guard.is_entry_blocked()

    metrics = guard.get_pareto_metrics()
    assert metrics["pareto_ratio"] <= 0.50
    assert not metrics["is_blocked"]


def test_wave299_pareto_concentration_blocks():
    guard = Wave299TradeVolumeParetoRatioGuard(
        max_pareto_ratio=0.82,
        min_total_volume=20.0,
        min_trades=15,
        cooldown_seconds=45.0,
    )

    # Directly inject precomputed Pareto concentration metric
    guard.record_pareto_metrics(pareto_ratio=0.88, total_volume=35.0, sample_count=18)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    metrics = guard.get_status()
    assert metrics["is_blocked"]
    assert "PARETO_VOLUME_CONCENTRATION" in metrics["last_block_reason"]


def test_wave299_acute_whale_dominance_blocks():
    guard = Wave299TradeVolumeParetoRatioGuard(
        acute_block_share=0.50,
        acute_min_block_size=15.0,
        acute_min_trades=10,
        cooldown_seconds=45.0,
    )

    # 9 trades of 0.50 lots followed by a massive 20.0 lot whale block (20 / 24.5 = 81.6% share)
    for _ in range(9):
        guard.record_trade_volume(0.50)
    guard.record_trade_volume(20.0)

    assert guard.is_entry_blocked()
    metrics = guard.get_pareto_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_WHALE_DOMINANCE" in metrics["last_block_reason"]


def test_wave299_insufficient_samples_no_block():
    guard = Wave299TradeVolumeParetoRatioGuard(
        max_pareto_ratio=0.82,
        min_total_volume=20.0,
        min_trades=15,
    )

    # High Pareto ratio but total volume only 10.0 lots (< 20.0 min_total_volume)
    guard.record_pareto_metrics(pareto_ratio=0.90, total_volume=10.0, sample_count=8)

    assert not guard.is_entry_blocked()


def test_wave299_input_validation_and_reset():
    guard = Wave299TradeVolumeParetoRatioGuard()

    # Corrupted volume (NaN) triggers fail-closed
    guard.record_trade_volume(float("nan"))
    assert guard.is_entry_blocked()
    assert "CORRUPTED" in guard.get_status()["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked()

    # Negative volume triggers fail-closed
    guard.update(-5.0)
    assert guard.is_entry_blocked()

    guard.reset()
    assert not guard.is_entry_blocked()
