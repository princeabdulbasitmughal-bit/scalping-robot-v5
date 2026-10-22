"""
tests/test_batch258.py
----------------------
Unit tests for Batch 258:
  - Wave 282: Wave282LobImbalanceAccelerationGuard
  - Wave 283: Wave283TradeVolumeVarianceBurstGuard
"""

import math
import time
import pytest

from wave282_lob_imbalance_acceleration_guard import Wave282LobImbalanceAccelerationGuard
from wave283_trade_volume_variance_burst_guard import Wave283TradeVolumeVarianceBurstGuard


# ----------------------------------------------------------------------
# Wave 282 Tests: LOB Inside-Queue Imbalance Acceleration Guard
# ----------------------------------------------------------------------

def test_wave282_smooth_imbalance_no_block():
    guard = Wave282LobImbalanceAccelerationGuard(
        max_mean_acceleration=4.50,
        min_imbalance_level=0.50,
        min_samples=6,
        acute_jolt_acceleration=8.00,
    )

    # Balanced book with smooth slow drift: 10 vs 10 lots drifting to 10 vs 9 lots over 1s intervals
    t = 100.0
    for i in range(10):
        guard.record_queue_depth(bid_depth=10.0, ask_depth=10.0 - (i * 0.1), ts=t)
        t += 1.0
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_acceleration_metrics()
    assert abs(metrics["mean_acceleration"]) < 2.0
    assert not metrics["is_blocked"]


def test_wave282_acceleration_surge_blocks():
    guard = Wave282LobImbalanceAccelerationGuard(
        max_mean_acceleration=4.50,
        min_imbalance_level=0.50,
        min_samples=6,
        cooldown_seconds=45.0,
    )

    # Direct ingestion of 7 surge acceleration events
    for _ in range(7):
        guard.record_acceleration(accel_units_per_sec2=5.20, imbalance=0.65)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    metrics = guard.get_status()
    assert metrics["is_blocked"]
    assert "IMBALANCE_ACCELERATION_SURGE" in metrics["last_block_reason"]


def test_wave282_acute_imbalance_jolt_blocks():
    guard = Wave282LobImbalanceAccelerationGuard(
        acute_jolt_acceleration=8.00,
        acute_swing=0.70,
        cooldown_seconds=45.0,
    )

    # 1. Balanced book at t=10.00
    guard.record_queue_depth(bid_depth=10.0, ask_depth=10.0, ts=10.00)
    # 2. Slight shift at t=10.05
    guard.record_queue_depth(bid_depth=10.0, ask_depth=9.0, ts=10.05)
    # 3. Violent ask sweep: ask drops to 0.50 lots at t=10.10 (severe acceleration & swing > 0.70 in dt <= 0.20s)
    guard.record_queue_depth(bid_depth=15.0, ask_depth=0.5, ts=10.10)

    assert guard.is_entry_blocked()
    metrics = guard.get_acceleration_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_IMBALANCE_JOLT" in metrics["last_block_reason"]


def test_wave282_insufficient_samples_no_block():
    guard = Wave282LobImbalanceAccelerationGuard(
        max_mean_acceleration=4.50,
        min_imbalance_level=0.50,
        min_samples=6,
    )

    # Only 3 acceleration events (< 6 min_samples)
    for _ in range(3):
        guard.record_acceleration(accel_units_per_sec2=5.00, imbalance=0.70, sample_count=3)

    assert not guard.is_entry_blocked()


def test_wave282_input_validation_and_reset():
    guard = Wave282LobImbalanceAccelerationGuard()

    # Boolean depth triggers fail-closed
    guard.record_queue_depth(True, 10.0)
    assert guard.is_entry_blocked()
    assert "CORRUPTED" in guard.get_status()["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked()

    # Negative depth triggers fail-closed
    guard.update(-5.0, 10.0)
    assert guard.is_entry_blocked()

    guard.reset()
    assert not guard.is_entry_blocked()


# ----------------------------------------------------------------------
# Wave 283 Tests: Trade Volume Variance Burst Guard
# ----------------------------------------------------------------------

def test_wave283_stationary_volume_no_block():
    guard = Wave283TradeVolumeVarianceBurstGuard(
        max_variance_ratio=4.50,
        acute_vol_std=6.50,
        min_trades=15,
    )

    # Stable, stationary trades of around 1.0 - 2.0 lots
    volumes = [1.0, 1.2, 0.9, 1.5, 1.1, 1.3, 1.0, 1.4, 0.8, 1.2] * 2
    for v in volumes:
        guard.record_trade_volume(v)
        assert not guard.is_entry_blocked()

    metrics = guard.get_variance_metrics()
    assert metrics["variance_ratio"] < 3.0
    assert not metrics["is_blocked"]


def test_wave283_variance_ratio_surge_blocks():
    guard = Wave283TradeVolumeVarianceBurstGuard(
        max_variance_ratio=4.50,
        min_mean_volume=2.50,
        min_trades=15,
        cooldown_seconds=45.0,
    )

    # Directly inject precomputed variance ratio surge
    guard.record_variance_metrics(variance_ratio=5.80, short_std=3.20, sample_count=18)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    metrics = guard.get_status()
    assert metrics["is_blocked"]
    assert "VOLUME_VARIANCE_RATIO_SURGE" in metrics["last_block_reason"]


def test_wave283_acute_volume_shock_blocks():
    guard = Wave283TradeVolumeVarianceBurstGuard(
        acute_vol_std=6.50,
        acute_min_trades=8,
        cooldown_seconds=45.0,
    )

    # Alternating tiny and massive prints: 0.1, 20.0, 0.1, 20.0 lots producing std dev > 6.50 lots
    for _ in range(5):
        guard.record_trade_volume(0.1)
        guard.record_trade_volume(20.0)

    assert guard.is_entry_blocked()
    metrics = guard.get_variance_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_VOLUME_VARIANCE_SHOCK" in metrics["last_block_reason"]


def test_wave283_insufficient_samples_no_block():
    guard = Wave283TradeVolumeVarianceBurstGuard(
        acute_vol_std=6.50,
        acute_min_trades=8,
    )

    # Only 4 samples (< 8 acute_min_trades)
    for _ in range(2):
        guard.record_trade_volume(0.1)
        guard.record_trade_volume(20.0)

    assert not guard.is_entry_blocked()


def test_wave283_input_validation_and_reset():
    guard = Wave283TradeVolumeVarianceBurstGuard()

    # Corrupted volume (NaN) triggers fail-closed
    guard.record_trade_volume(float("nan"))
    assert guard.is_entry_blocked()
    assert "CORRUPTED" in guard.get_status()["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked()

    # Zero/negative volume triggers fail-closed
    guard.update(0.0)
    assert guard.is_entry_blocked()

    guard.reset()
    assert not guard.is_entry_blocked()
