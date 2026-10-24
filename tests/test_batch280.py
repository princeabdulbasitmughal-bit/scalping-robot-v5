"""Unit tests for Batch 280: Wave 326 and Wave 327 Risk & Microstructure Guards."""

import math
import time
import pytest

from wave326_lob_depth_asymmetry_acceleration_guard import Wave326LOBDepthAsymmetryAccelerationGuard
from wave327_trade_arrival_poisson_overdispersion_guard import Wave327TradeArrivalPoissonOverdispersionGuard


# ==========================================
# Wave 326 Tests: Depth Asymmetry Accel
# ==========================================

def test_wave326_smooth_depth_transitions_no_block():
    """Verify smooth continuous depth changes do not trigger acceleration blocks."""
    guard = Wave326LOBDepthAsymmetryAccelerationGuard(
        window_size=10,
        acute_accel_threshold=40.0,
        rms_accel_threshold=15.0,
        cooldown_seconds=30.0,
    )
    t0 = 1000.0
    # Gentle breathing depth: 5.0 to 6.0 lots over 1.0s intervals
    for i in range(15):
        q_bid = 5.0 + 0.1 * (i % 5)
        q_ask = 5.0 - 0.1 * (i % 5)
        blocked = guard.update(
            bid_price=1.1000,
            ask_price=1.1001,
            bid_depth=q_bid,
            ask_depth=q_ask,
            current_time=t0 + i * 1.0,
        )
        assert not blocked
        assert not guard.is_entry_blocked(t0 + i * 1.0)

    status = guard.get_status(t0 + 15)
    assert not status["is_blocked"]
    assert status["total_violations"] == 0


def test_wave326_acute_imbalance_acceleration_shock_blocks():
    """Verify sudden violent flip in depth causing acceleration |a| >= 40/s^2 triggers shock block."""
    guard = Wave326LOBDepthAsymmetryAccelerationGuard(
        acute_accel_threshold=40.0,
        cooldown_seconds=45.0,
    )
    t0 = 2000.0
    # Tick 1: balanced book (imbalance 0.0)
    assert not guard.update(1.1000, 1.1002, 5.0, 5.0, current_time=t0)
    # Tick 2: 0.05s later, small shift (imbalance = (6-4)/10 = 0.20, v = 0.2/0.05 = 4.0/s)
    assert not guard.update(1.1000, 1.1002, 6.0, 4.0, current_time=t0 + 0.05)
    # Tick 3: 0.05s later, violent inverse flip: bid 0.5, ask 20.0 (imbalance ~= -0.95, v = -1.15/0.05 = -23.0/s)
    # Acceleration = (-23.0 - 4.0) / 0.05 = -540 /s^2 (|a| >> 40)
    blocked = guard.update(1.1000, 1.1002, 0.5, 20.0, current_time=t0 + 0.10)
    assert blocked

    status = guard.get_status(t0 + 0.10)
    assert status["is_blocked"]
    assert "ACUTE_IMBALANCE_ACCELERATION_SHOCK" in status["last_block_reason"]


def test_wave326_unilateral_depth_collapse_blocks():
    """Verify instantaneous >85% collapse of one queue triggers depth collapse block."""
    guard = Wave326LOBDepthAsymmetryAccelerationGuard(
        collapse_ratio=0.15,
        collapse_min_prior_depth=2.0,
        collapse_time_window_s=0.15,
        cooldown_seconds=45.0,
    )
    t0 = 3000.0
    # Initial healthy book
    assert not guard.update(1.1000, 1.1002, 10.0, 10.0, current_time=t0)
    # 0.08s later, bid queue evaporates to 0.5 lots (95% drop with prior 10.0 >= 2.0)
    blocked = guard.update(1.1000, 1.1002, 0.5, 10.0, current_time=t0 + 0.08)
    assert blocked

    status = guard.get_status(t0 + 0.08)
    assert "UNILATERAL_DEPTH_COLLAPSE" in status["last_block_reason"]


def test_wave326_rolling_acceleration_jerk_blocks():
    """Verify oscillating rapid depth changes with wide spread trigger rolling jerk block."""
    guard = Wave326LOBDepthAsymmetryAccelerationGuard(
        window_size=8,
        acute_accel_threshold=2000.0,  # disable acute shock to test rolling RMS
        rms_accel_threshold=15.0,
        spread_threshold_bps=2.0,
        cooldown_seconds=45.0,
    )
    t0 = 4000.0
    cur_t = t0
    # Wide spread = 0.0003 on 1.1000 ~= 2.72 bps > 2.0 bps
    # High frequency oscillating depth creating high acceleration:
    # 0.05s intervals alternating between high bid and high ask
    for i in range(12):
        cur_t += 0.05
        q_bid = 8.0 if i % 2 == 0 else 2.0
        q_ask = 2.0 if i % 2 == 0 else 8.0
        blocked = guard.update(1.1000, 1.1003, q_bid, q_ask, current_time=cur_t)
        if blocked:
            break

    assert guard.is_blocked(cur_t)
    status = guard.get_status(cur_t)
    assert "ROLLING_ACCELERATION_JERK" in status["last_block_reason"]


def test_wave326_fail_closed_and_reset():
    """Verify non-numeric/bool/NaN inputs fail closed and reset restores clean state."""
    guard = Wave326LOBDepthAsymmetryAccelerationGuard(cooldown_seconds=20.0)
    t0 = 5000.0

    assert guard.update(True, 1.1002, 5.0, 5.0, current_time=t0)
    assert "FAIL_CLOSED" in guard.get_status(t0)["last_block_reason"]

    guard.reset()
    assert guard.update(1.1000, float("nan"), 5.0, 5.0, current_time=t0)
    assert "FAIL_CLOSED" in guard.get_status(t0)["last_block_reason"]

    guard.reset()
    assert guard.update(1.1000, 1.1002, -1.0, 5.0, current_time=t0)
    assert "FAIL_CLOSED" in guard.get_status(t0)["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked(t0 + 1.0)
    assert guard.get_status(t0 + 1.0)["total_violations"] == 0


# ==========================================
# Wave 327 Tests: Poisson Overdispersion
# ==========================================

def test_wave327_equidispersed_poisson_no_block():
    """Verify stable trade arrivals with Fano factor near 1.0 do not trip the guard."""
    guard = Wave327TradeArrivalPoissonOverdispersionGuard(
        bin_duration_s=0.50,
        window_size_bins=10,
        overdispersion_threshold=3.50,
        underdispersion_threshold=0.15,
        cooldown_seconds=30.0,
    )
    t0 = 6000.0
    cur_t = t0
    # Natural Poisson variance across 12 bins: counts varying around 4-6
    bin_counts = [5, 4, 6, 5, 4, 6, 5, 5, 4, 6, 5, 4]
    for count in bin_counts:
        for _ in range(count):
            cur_t += 0.08
            blocked = guard.update(trade_volume=1.0, trade_timestamp=cur_t, current_time=cur_t)
            assert not blocked
        cur_t += 0.15  # roll into next bin

    status = guard.get_status(cur_t)
    assert not status["is_blocked"]
    assert status["total_violations"] == 0
    assert 0.20 <= status["last_fano_factor"] <= 2.0


def test_wave327_overdispersion_clustering_blocks():
    """Verify extreme burst clustering producing Fano factor >= 3.50 triggers overdispersion block."""
    guard = Wave327TradeArrivalPoissonOverdispersionGuard(
        bin_duration_s=0.50,
        window_size_bins=10,
        overdispersion_threshold=3.0,
        min_rate_overdispersed=6.0,
        acute_bin_trade_count=50,  # avoid acute blast
        cooldown_seconds=45.0,
    )
    t0 = 7000.0
    cur_t = t0
    # Heavy clustering: alternating 1 trade then 15 trades per bin
    # Mean count = 8 trades per bin (rate = 16/s >= 6.0), variance = (7^2) = 49, Fano = 49/8 ~= 6.12 >= 3.0
    for b in range(12):
        count = 15 if b % 2 == 0 else 1
        for _ in range(count):
            cur_t += 0.02
            blocked = guard.update(trade_volume=0.5, trade_timestamp=cur_t, current_time=cur_t)
            if blocked:
                break
        if guard.is_blocked(cur_t):
            break
        cur_t += 0.35  # Advance past bin_duration_s (0.50s)

    assert guard.is_blocked(cur_t)
    status = guard.get_status(cur_t)
    assert "POISSON_OVERDISPERSION_SURGE" in status["last_block_reason"]
    assert status["last_fano_factor"] >= 3.0


def test_wave327_underdispersion_robotic_pacing_blocks():
    """Verify rigid robotic clock pacing (variance near 0, Fano <= 0.15) triggers underdispersion block."""
    guard = Wave327TradeArrivalPoissonOverdispersionGuard(
        bin_duration_s=0.50,
        window_size_bins=10,
        underdispersion_threshold=0.15,
        min_rate_underdispersed=4.0,
        cooldown_seconds=45.0,
    )
    t0 = 8000.0
    cur_t = t0
    # Exactly 4 trades per bin across 10 bins: mean = 4, var = 0, Fano = 0.0, rate = 8 trades/s >= 4.0
    for b in range(11):
        for _ in range(4):
            cur_t += 0.10
            blocked = guard.update(trade_volume=1.0, trade_timestamp=cur_t, current_time=cur_t)
            if blocked:
                break
        if guard.is_blocked(cur_t):
            break
        cur_t += 0.15  # Cross 0.50s bin boundary

    assert guard.is_blocked(cur_t)
    status = guard.get_status(cur_t)
    assert "ROBOTIC_UNDERDISPERSION_ANOMALY" in status["last_block_reason"]
    assert status["last_fano_factor"] <= 0.15


def test_wave327_acute_count_volume_blast_blocks():
    """Verify acute surge in trade count and volume within single bin triggers blast block."""
    guard = Wave327TradeArrivalPoissonOverdispersionGuard(
        bin_duration_s=0.50,
        acute_bin_trade_count=25,
        acute_bin_volume=15.0,
        cooldown_seconds=45.0,
    )
    t0 = 9000.0
    cur_t = t0
    # 25 trades of 0.70 lots within 0.40s (< 0.50s bin, total volume 17.5 lots >= 15.0)
    for i in range(25):
        cur_t += 0.015
        blocked = guard.update(trade_volume=0.70, trade_timestamp=cur_t, current_time=cur_t)
        if i < 24:
            assert not blocked
        else:
            assert blocked

    assert guard.is_blocked(cur_t)
    status = guard.get_status(cur_t)
    assert "ACUTE_COUNT_VOLUME_BLAST" in status["last_block_reason"]


def test_wave327_fail_closed_and_reset():
    """Verify timestamp inversion, non-numeric/bool inputs fail closed and reset restores pristine state."""
    guard = Wave327TradeArrivalPoissonOverdispersionGuard(cooldown_seconds=20.0)
    t0 = 10000.0

    # Initial valid trade
    assert not guard.update(1.0, t0, current_time=t0)

    # Timestamp inversion
    assert guard.update(1.0, t0 - 1.0, current_time=t0 + 0.1)
    assert "TIMESTAMP_INVERSION" in guard.get_status(t0 + 0.1)["last_block_reason"]

    guard.reset()
    # Non-numeric volume
    assert guard.update(True, t0 + 1.0, current_time=t0 + 1.0)
    assert "FAIL_CLOSED" in guard.get_status(t0 + 1.0)["last_block_reason"]

    guard.reset()
    # Non-positive volume
    assert guard.update(0.0, t0 + 2.0, current_time=t0 + 2.0)
    assert "FAIL_CLOSED" in guard.get_status(t0 + 2.0)["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked(t0 + 3.0)
    assert guard.get_status(t0 + 3.0)["total_violations"] == 0
