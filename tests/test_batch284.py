"""Unit tests for Batch 284: Wave 334 and Wave 335 Risk & Microstructure Guards."""

import math
import time
import pytest

from wave334_lob_mid_price_acceleration_pressure_guard import Wave334LOBMidPriceAccelerationPressureGuard
from wave335_trade_arrival_clustering_burstiness_guard import Wave335TradeArrivalClusteringBurstinessGuard


# ==========================================
# Wave 334 Tests: LOB Acceleration & Pressure
# ==========================================

def test_wave334_steady_flow_no_block():
    """Verify steady mid-price movement and balanced book depth do not trigger blocks."""
    guard = Wave334LOBMidPriceAccelerationPressureGuard(
        window_size=15,
        acceleration_threshold_bps_s2=4.5,
        pressure_disparity_threshold=0.75,
        cooldown_seconds=30.0,
    )
    t0 = 1000.0
    for i in range(15):
        # Mid-price moves very slowly by 0.00001 (approx 0.1 bps) every 1.0s -> constant velocity, 0 accel
        bid = 1.10000 + i * 0.00001
        ask = bid + 0.00010
        b_sz = 50.0
        a_sz = 50.0  # pressure = 0.0
        blocked = guard.update(bid, ask, b_sz, a_sz, current_time=t0 + i * 1.0)
        assert not blocked
        assert not guard.is_entry_blocked(t0 + i * 1.0)

    status = guard.get_status(t0 + 15.0)
    assert not status["is_blocked"]
    assert status["total_violations"] == 0
    assert status["last_acceleration_bps_s2"] == 0.0
    assert status["last_pressure_disparity"] == 0.0


def test_wave334_acute_acceleration_pressure_disparity_blocks():
    """Verify sudden acceleration spike with high queue pressure triggers an acute block."""
    guard = Wave334LOBMidPriceAccelerationPressureGuard(
        window_size=15,
        acceleration_threshold_bps_s2=4.5,
        pressure_disparity_threshold=0.75,
        cooldown_seconds=45.0,
    )
    t0 = 2000.0
    # Step 1: Baseline flat quotes at t = 2000.0, 2001.0 (vel = 0)
    guard.update(1.1000, 1.1002, 50.0, 50.0, current_time=t0)
    guard.update(1.1000, 1.1002, 50.0, 50.0, current_time=t0 + 1.0)

    # Step 2: Sudden violent surge in price over 0.10s (jump of 10 bps) with huge bid pressure (90 vs 5)
    # Velocity goes from 0 to 10 bps / 0.10s = 100 bps/s -> Accel = 100 / 0.10 = 1000 bps/s^2!
    # Pressure = (90 - 5) / 95 = 85 / 95 = +0.895 > 0.75
    blocked = guard.update(1.1011, 1.1013, 90.0, 5.0, current_time=t0 + 1.10)
    assert blocked
    assert guard.is_entry_blocked(t0 + 1.10)

    status = guard.get_status(t0 + 1.10)
    assert status["is_blocked"]
    assert status["total_violations"] == 1
    assert "ACUTE_MID_PRICE_ACCELERATION" in status["last_block_reason"]


def test_wave334_inside_liquidity_cliff_blocks():
    """Verify sudden drop in total top-of-book depth triggers liquidity cliff block."""
    guard = Wave334LOBMidPriceAccelerationPressureGuard(
        window_size=15,
        liquidity_cliff_drop_pct=0.75,
        min_depth_sample_count=5,
        cooldown_seconds=45.0,
    )
    t0 = 3000.0
    # Populate baseline depth with 100 lots total (50 bid, 50 ask)
    for i in range(8):
        guard.update(1.1000, 1.1002, 50.0, 50.0, current_time=t0 + i * 0.5)

    assert not guard.is_blocked(t0 + 4.0)

    # Next update: inside depth collapses from 100 to 10 (drop = 90% >= 75%)
    blocked = guard.update(1.1000, 1.1002, 5.0, 5.0, current_time=t0 + 4.5)
    assert blocked
    assert guard.is_entry_blocked(t0 + 4.5)

    status = guard.get_status(t0 + 4.5)
    assert status["is_blocked"]
    assert "INSIDE_LIQUIDITY_CLIFF" in status["last_block_reason"]


def test_wave334_crossed_or_locked_book_fail_closed():
    """Verify crossed book (bid >= ask) immediately fails closed."""
    guard = Wave334LOBMidPriceAccelerationPressureGuard()
    t0 = 4000.0

    # Bid 1.1005 >= Ask 1.1002
    blocked = guard.update(1.1005, 1.1002, 20.0, 20.0, current_time=t0)
    assert blocked
    assert guard.is_blocked(t0)

    status = guard.get_status(t0)
    assert "CROSSED_OR_LOCKED_BOOK" in status["last_block_reason"]


def test_wave334_invalid_inputs_fail_closed():
    """Verify non-numeric, NaN, and non-positive inputs trip immediate fail-closed block."""
    guard = Wave334LOBMidPriceAccelerationPressureGuard()
    t0 = 5000.0

    # NaN bid
    assert guard.update(float("nan"), 1.1002, 10.0, 10.0, current_time=t0)
    assert "FAIL_CLOSED" in guard.get_status(t0)["last_block_reason"]

    guard.reset()
    # Zero size
    assert guard.update(1.1000, 1.1002, 0.0, 10.0, current_time=t0)
    assert "FAIL_CLOSED" in guard.get_status(t0)["last_block_reason"]


# ==========================================
# Wave 335 Tests: Trade Arrival Clustering & Burstiness
# ==========================================

def test_wave335_regular_arrivals_no_block():
    """Verify regular/Poisson trade arrivals do not trigger burstiness blocks."""
    guard = Wave335TradeArrivalClusteringBurstinessGuard(
        window_size=20,
        burstiness_threshold=0.65,
        compressed_mean_duration_s=0.040,
        cooldown_seconds=30.0,
    )
    t0 = 6000.0
    # Regular intervals of 0.20s -> variance is 0 -> Burstiness B = -1.0
    for i in range(16):
        blocked = guard.update(trade_volume=1.5, current_time=t0 + i * 0.20)
        assert not blocked
        assert not guard.is_entry_blocked(t0 + i * 0.20)

    status = guard.get_status(t0 + 3.20)
    assert not status["is_blocked"]
    assert status["total_violations"] == 0
    assert status["last_burstiness"] <= 0.0


def test_wave335_burstiness_clustering_blocks():
    """Verify heavy-tailed clustering with compressed mean duration trips burstiness block."""
    guard = Wave335TradeArrivalClusteringBurstinessGuard(
        window_size=20,
        burstiness_threshold=0.50,
        compressed_mean_duration_s=0.040,
        cooldown_seconds=45.0,
    )
    t0 = 7000.0
    cur_t = t0

    # 15 micro-trades spaced by 0.005s (5ms > 2ms threshold to avoid sub-ms stampede) followed by one gap of 0.40s
    # Sample mean mu ~= (15 * 0.005 + 0.40) / 16 = 0.475 / 16 = 0.0297s <= 0.040s
    # Stdev sigma ~= 0.098s -> B = (0.098 - 0.030) / (0.098 + 0.030) = 0.068 / 0.128 = 0.53 >= 0.50
    blocked = False
    for cycle in range(2):
        for _ in range(12):
            cur_t += 0.005
            blocked = guard.update(trade_volume=0.2, current_time=cur_t)
            if blocked:
                break
        if blocked:
            break
        cur_t += 0.40
        blocked = guard.update(trade_volume=0.2, current_time=cur_t)
        if blocked:
            break

    assert blocked
    assert guard.is_blocked(cur_t)
    status = guard.get_status(cur_t)
    assert status["is_blocked"]
    assert "TRADE_ARRIVAL_BURSTINESS_CLUSTERING" in status["last_block_reason"]


def test_wave335_trade_train_avalanche_blocks():
    """Verify rapid succession of >= 8 trades within 100ms and >= 10 lots triggers avalanche block."""
    guard = Wave335TradeArrivalClusteringBurstinessGuard(
        window_size=20,
        train_trade_count=8,
        train_time_window_s=0.100,
        train_min_volume=10.0,
        cooldown_seconds=45.0,
    )
    t0 = 8000.0
    # 8 trades spaced by 0.010s (total time = 0.070s <= 0.100s) with 1.5 lots each (total 12.0 lots >= 10.0)
    blocked = False
    for i in range(8):
        blocked = guard.update(trade_volume=1.5, current_time=t0 + i * 0.010)

    assert blocked
    assert guard.is_entry_blocked(t0 + 0.070)
    status = guard.get_status(t0 + 0.070)
    assert status["is_blocked"]
    assert "TRADE_TRAIN_AVALANCHE" in status["last_block_reason"]


def test_wave335_sub_ms_stampede_and_non_monotonic_fail_closed():
    """Verify >= 5 consecutive sub-2ms trades or non-monotonic timestamps fail closed."""
    guard = Wave335TradeArrivalClusteringBurstinessGuard(
        sub_ms_stampede_count=5,
        sub_ms_threshold_s=0.002,
    )
    t0 = 9000.0

    # 6 trades -> 5 consecutive intervals of 1ms gap
    blocked = False
    for i in range(6):
        blocked = guard.update(trade_volume=0.2, current_time=t0 + i * 0.001)

    assert blocked
    assert "SUB_MS_STAMPEDE" in guard.get_status(t0 + 0.005)["last_block_reason"]

    # Test non-monotonic timestamp
    guard.reset()
    guard.update(trade_volume=1.0, current_time=9100.0)
    assert guard.update(trade_volume=1.0, current_time=9099.0)  # backwards time
    assert "FAIL_CLOSED" in guard.get_status(9099.0)["last_block_reason"]


def test_wave334_and_wave335_cooldown_and_reset():
    """Verify cooldown timer expiry and manual reset across Wave 334 and Wave 335."""
    g334 = Wave334LOBMidPriceAccelerationPressureGuard(cooldown_seconds=10.0)
    g335 = Wave335TradeArrivalClusteringBurstinessGuard(cooldown_seconds=10.0)
    t0 = 10000.0

    # Trip both guards with invalid inputs
    g334.update(float("nan"), 1.1000, 10.0, 10.0, current_time=t0)
    g335.update(-1.0, current_time=t0)

    assert g334.is_blocked(t0 + 5.0)
    assert g335.is_blocked(t0 + 5.0)

    # After 10s cooldown expires
    assert not g334.is_blocked(t0 + 10.1)
    assert not g335.is_blocked(t0 + 10.1)

    # Re-trip and test manual reset
    g334.update(1.1005, 1.1002, 10.0, 10.0, current_time=t0 + 11.0)  # crossed
    assert g334.is_blocked(t0 + 11.0)
    g334.reset()
    assert not g334.is_blocked(t0 + 11.0)
    assert g334.get_status(t0 + 11.0)["total_violations"] == 0
