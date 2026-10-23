"""
tests/test_batch273.py
----------------------
Unit tests for Batch 273:
  - Wave 312: Wave312LobQuoteChurnVelocityGuard
  - Wave 313: Wave313TradeSizeRoundLotBiasGuard
"""

import math
import time
import pytest

from wave312_lob_quote_churn_velocity_guard import Wave312LobQuoteChurnVelocityGuard
from wave313_trade_size_round_lot_bias_guard import Wave313TradeSizeRoundLotBiasGuard


# ----------------------------------------------------------------------
# Wave 312 Tests: LOB Quote Churn Velocity & Round-Trip Guard
# ----------------------------------------------------------------------

def test_wave312_normal_quote_velocity_no_block():
    guard = Wave312LobQuoteChurnVelocityGuard(
        max_churn_velocity=35.0,
        window_sec=5.0,
    )

    t0 = 1000.0
    # 10 quote updates spread over 4 seconds (~2.5 updates/sec)
    for i in range(10):
        price = 100.0 + (i * 0.05)
        guard.record_quote(mid_price=price, ts=t0 + i * 0.4)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_churn_metrics()
    assert metrics["churn_velocity"] <= 10.0
    assert not metrics["is_blocked"]


def test_wave312_quote_churn_velocity_surge_blocks():
    guard = Wave312LobQuoteChurnVelocityGuard(
        max_churn_velocity=35.0,
        min_round_trip_ratio=0.60,
        window_sec=5.0,
        cooldown_seconds=45.0,
    )

    # Directly inject precomputed churn metrics (velocity = 45.0 updates/s, rt_ratio = 0.75)
    guard.record_churn_metrics(churn_velocity=45.0, round_trip_ratio=0.75, sample_count=50)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    status = guard.get_status()
    assert status["is_blocked"]
    assert "QUOTE_CHURN_VELOCITY_SURGE" in status["last_block_reason"]


def test_wave312_acute_flash_barrage_blocks():
    guard = Wave312LobQuoteChurnVelocityGuard(
        acute_flash_updates=25,
        acute_burst_sec=0.30,
        cooldown_seconds=45.0,
    )

    t0 = 1000.0
    # 26 rapid updates within 0.20s (dt = 0.007s per update)
    for i in range(26):
        price = 100.0 + (0.01 if i % 2 == 0 else -0.01)
        guard.record_quote(mid_price=price, ts=t0 + i * 0.007)

    assert guard.is_entry_blocked()
    metrics = guard.get_churn_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_QUOTE_FLASH_BARRAGE" in metrics["last_block_reason"]


def test_wave312_direct_churn_metrics():
    guard = Wave312LobQuoteChurnVelocityGuard(
        max_churn_velocity=35.0,
        cooldown_seconds=45.0,
    )

    # Below threshold (velocity = 15.0)
    guard.record_churn_metrics(churn_velocity=15.0, round_trip_ratio=0.30, sample_count=30)
    assert not guard.is_entry_blocked()

    # Above threshold (velocity = 40.0)
    guard.record_churn_metrics(churn_velocity=40.0, round_trip_ratio=0.70, sample_count=30)
    assert guard.is_entry_blocked()
    assert "QUOTE_CHURN_VELOCITY_SURGE" in guard.get_status()["last_block_reason"]


def test_wave312_fail_closed_and_reset():
    guard = Wave312LobQuoteChurnVelocityGuard(cooldown_seconds=45.0)

    # Corrupted inputs: zero, negative, NaN, Inf, bool, None
    for bad_p in [0.0, -10.0, float("nan"), float("inf"), True, None]:
        guard.record_quote(bad_p)
        assert guard.is_entry_blocked()
        assert "CORRUPTED_PRICE_INPUT" in guard.get_status()["last_block_reason"]
        guard.reset()
        assert not guard.is_entry_blocked()

    # Update alias check
    guard.update(100.5)
    assert not guard.is_entry_blocked()


# ----------------------------------------------------------------------
# Wave 313 Tests: Trade Size Round-Lot Modulo Bias Guard
# ----------------------------------------------------------------------

def test_wave313_natural_modulo_distribution_no_block():
    guard = Wave313TradeSizeRoundLotBiasGuard(
        min_modulo_entropy=0.15,
        min_samples=15,
    )

    # Natural heterogeneous trades with diverse fractional modulos
    diverse_trades = [
        1.10, 0.50, 2.25, 1.40, 0.70, 3.85, 1.30, 2.60,
        0.90, 1.15, 2.45, 0.35, 1.75, 2.00, 0.80, 1.65
    ]
    for sz in diverse_trades:
        guard.record_trade_size(sz)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_bias_metrics()
    assert metrics["modulo_entropy"] >= 0.40
    assert not metrics["is_blocked"]


def test_wave313_algorithmic_modulo_pinning_blocks():
    guard = Wave313TradeSizeRoundLotBiasGuard(
        min_modulo_entropy=0.15,
        min_samples=15,
        cooldown_seconds=45.0,
    )

    # Directly inject precomputed low entropy metric (H_mod = 0.05 < 0.15)
    guard.record_bias_metrics(modulo_entropy=0.05, round_fraction=0.10, sample_count=18)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    status = guard.get_status()
    assert status["is_blocked"]
    assert "ALGORITHMIC_MODULO_PINNING" in status["last_block_reason"]


def test_wave313_acute_fractional_slicing_streak_blocks():
    guard = Wave313TradeSizeRoundLotBiasGuard(
        acute_fractional_streak=8,
        cooldown_seconds=45.0,
    )

    # 7 consecutive trades with identical fraction (.137) -> not yet 8
    for i in range(7):
        guard.record_trade_size(1.137 + i * 1.0)
        assert not guard.is_entry_blocked()

    # 8th trade with same fraction (.137) -> trips acute streak
    guard.record_trade_size(8.137)
    assert guard.is_entry_blocked()
    metrics = guard.get_bias_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_FRACTIONAL_SLICING_STREAK" in metrics["last_block_reason"]


def test_wave313_direct_bias_metrics():
    guard = Wave313TradeSizeRoundLotBiasGuard(
        min_modulo_entropy=0.15,
        cooldown_seconds=45.0,
    )

    # Below threshold (safe entropy = 0.65)
    guard.record_bias_metrics(modulo_entropy=0.65, round_fraction=0.40, sample_count=16)
    assert not guard.is_entry_blocked()

    # Above threshold (dangerous low entropy = 0.08)
    guard.record_bias_metrics(modulo_entropy=0.08, round_fraction=0.10, sample_count=16)
    assert guard.is_entry_blocked()
    assert "ALGORITHMIC_MODULO_PINNING" in guard.get_status()["last_block_reason"]


def test_wave313_fail_closed_and_reset():
    guard = Wave313TradeSizeRoundLotBiasGuard(cooldown_seconds=45.0)

    # Corrupted inputs: zero, negative, NaN, Inf, bool, None
    for bad_sz in [0.0, -1.5, float("nan"), float("inf"), True, None]:
        guard.record_trade_size(bad_sz)
        assert guard.is_entry_blocked()
        assert "CORRUPTED_TRADE_SIZE_INPUT" in guard.get_status()["last_block_reason"]
        guard.reset()
        assert not guard.is_entry_blocked()

    # Update alias check
    guard.update(1.5)
    assert not guard.is_entry_blocked()
