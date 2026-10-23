"""Unit tests for Batch 278: Wave 322 and Wave 323 Risk & Microstructure Guards."""

import math
import time
import pytest

from wave322_lob_spread_step_quantization_guard import Wave322LOBSpreadStepQuantizationGuard
from wave323_trade_arrival_self_similarity_hurst_guard import Wave323TradeArrivalSelfSimilarityHurstGuard


# ==========================================
# Wave 322 Tests: Spread Step Quantization
# ==========================================

def test_wave322_normal_tick_quantization_no_block():
    """Verify clean integer tick multiples do not trip the guard."""
    guard = Wave322LOBSpreadStepQuantizationGuard(
        tick_size=0.0001,
        window_size=10,
        max_fractional_residual=0.05,
        min_tick_ratio=0.95,
        cooldown_seconds=30.0,
    )
    t0 = 1000.0
    # Clean 1-tick and 2-tick spreads
    for i in range(15):
        bid = 1.1000 + i * 0.0001
        ask = bid + (0.0001 if i % 2 == 0 else 0.0002)
        blocked = guard.update(bid, ask, current_time=t0 + i)
        assert not blocked
        assert not guard.is_entry_blocked(t0 + i)

    status = guard.get_status(t0 + 15)
    assert not status["is_blocked"]
    assert status["total_violations"] == 0
    assert status["buffer_fill"] == 10


def test_wave322_fractional_residual_violation_blocks():
    """Verify synthetic sub-penny quotes with non-integer tick steps trigger immediate block."""
    guard = Wave322LOBSpreadStepQuantizationGuard(
        tick_size=0.0001,
        max_fractional_residual=0.05,
        acute_step_threshold=10.0,
        cooldown_seconds=45.0,
    )
    t0 = 2000.0
    # Clean tick
    assert not guard.update(1.1000, 1.1001, current_time=t0)

    # Fractional sub-penny quote: spread = 0.000135 (1.35 ticks, residual 0.35 > 0.05)
    blocked = guard.update(1.1000, 1.100135, current_time=t0 + 0.1)
    assert blocked
    assert guard.is_blocked(t0 + 0.1)

    status = guard.get_status(t0 + 0.1)
    assert status["is_blocked"]
    assert "QUANTIZATION_RESIDUAL_VIOLATION" in status["last_block_reason"]
    assert status["total_violations"] == 1


def test_wave322_crossed_book_and_sub_tick_blocks():
    """Verify crossed book (spread <= 0) and sub-tick spread (< 0.95 tick) trigger immediate blocks."""
    guard = Wave322LOBSpreadStepQuantizationGuard(
        tick_size=0.0001,
        min_tick_ratio=0.95,
        cooldown_seconds=45.0,
    )
    t0 = 3000.0
    # Crossed book: ask < bid
    assert guard.update(1.1005, 1.1000, current_time=t0)
    status = guard.get_status(t0)
    assert "LOB_CROSSED_OR_LOCKED" in status["last_block_reason"]

    guard.reset()
    # Locked book: ask == bid
    assert guard.update(1.1000, 1.1000, current_time=t0 + 1.0)
    assert "LOB_CROSSED_OR_LOCKED" in guard.get_status(t0 + 1.0)["last_block_reason"]

    guard.reset()
    # Sub-tick spread: spread = 0.00005 (0.50 ticks < 0.95)
    assert guard.update(1.1000, 1.10005, current_time=t0 + 2.0)
    assert "SUB_TICK_ANOMALY" in guard.get_status(t0 + 2.0)["last_block_reason"]


def test_wave322_acute_blowout_and_pinning_blocks():
    """Verify acute step blowout and rigid quantization pinning grid lock trigger blocks."""
    # 1. Acute step blowout: spread = 0.00090 (9.0 ticks >= 8.0)
    guard_acute = Wave322LOBSpreadStepQuantizationGuard(
        tick_size=0.0001,
        acute_step_threshold=8.0,
        cooldown_seconds=30.0,
    )
    t0 = 4000.0
    assert guard_acute.update(1.1000, 1.1009, current_time=t0)
    assert "ACUTE_SPREAD_STEP_BLOWOUT" in guard_acute.get_status(t0)["last_block_reason"]

    # 2. Pinning grid lock: spread pinned rigidly at 5.0 ticks across 10 ticks
    guard_pin = Wave322LOBSpreadStepQuantizationGuard(
        tick_size=0.0001,
        window_size=10,
        pinning_step_threshold=4.5,
        pinning_std_max=0.05,
        acute_step_threshold=10.0,
        cooldown_seconds=30.0,
    )
    for i in range(10):
        # 5.0 ticks spread exactly
        blocked = guard_pin.update(1.1000, 1.1005, current_time=t0 + i)
        if i < 9:
            assert not blocked
        else:
            assert blocked

    assert "SPREAD_QUANTIZATION_PINNING" in guard_pin.get_status(t0 + 10)["last_block_reason"]


def test_wave322_fail_closed_and_reset():
    """Verify non-numeric/bool/NaN inputs fail closed and reset restores pristine state."""
    guard = Wave322LOBSpreadStepQuantizationGuard(cooldown_seconds=20.0)
    t0 = 5000.0

    assert guard.update(True, 1.1001, current_time=t0)
    assert "FAIL_CLOSED" in guard.get_status(t0)["last_block_reason"]

    guard.reset()
    assert guard.update(float("nan"), 1.1001, current_time=t0)
    assert "FAIL_CLOSED" in guard.get_status(t0)["last_block_reason"]

    guard.reset()
    assert guard.update(1.1000, float("inf"), current_time=t0)
    assert "FAIL_CLOSED" in guard.get_status(t0)["last_block_reason"]

    guard.reset()
    assert not guard.is_blocked(t0)
    assert guard.get_status(t0)["total_violations"] == 0


# ==========================================
# Wave 323 Tests: Self-Similarity & Hurst
# ==========================================

def test_wave323_normal_arrivals_no_block():
    """Verify regular dispersed trade arrivals do not trip the guard."""
    guard = Wave323TradeArrivalSelfSimilarityHurstGuard(
        window_size=15,
        h_low_threshold=0.15,
        h_high_threshold=0.65,
        cooldown_seconds=30.0,
    )
    t0 = 6000.0
    cur_t = t0
    intervals = [0.42, 0.68, 0.35, 0.81, 0.45, 0.55, 0.39, 0.72, 0.48, 0.63, 0.41, 0.58, 0.36, 0.69, 0.44]
    for dt in intervals:
        cur_t += dt
        blocked = guard.update(trade_volume=1.5, trade_timestamp=cur_t, current_time=cur_t)
        assert not blocked

    status = guard.get_status(cur_t)
    assert not status["is_blocked"]
    assert status["total_violations"] == 0
    assert 0.20 <= status["hurst_exponent"] <= 0.60


def test_wave323_antipersistent_machine_pinging_blocks():
    """Verify extreme antipersistence (rapid alternating intervals) triggers machine pinging block."""
    guard = Wave323TradeArrivalSelfSimilarityHurstGuard(
        window_size=16,
        h_low_threshold=0.15,
        rapid_arrival_threshold_s=0.15,
        identical_streak_threshold=20,  # avoid triggering identical streak
        cooldown_seconds=45.0,
    )
    t0 = 7000.0
    cur_t = t0
    # High-frequency alternating pinging: 0.02s then 0.12s
    for i in range(25):
        dt = 0.02 if i % 2 == 0 else 0.12
        cur_t += dt
        blocked = guard.update(trade_volume=0.5, trade_timestamp=cur_t, current_time=cur_t)
        if blocked:
            break

    assert guard.is_blocked(cur_t)
    status = guard.get_status(cur_t)
    assert "ANTIPERSISTENT_MACHINE_PINGING" in status["last_block_reason"]
    assert status["hurst_exponent"] <= 0.15


def test_wave323_deterministic_slicing_streak_blocks():
    """Verify consecutive trades with identical intervals trigger deterministic slicing streak block."""
    guard = Wave323TradeArrivalSelfSimilarityHurstGuard(
        identical_streak_threshold=6,
        identical_interval_tolerance_s=0.001,
        cooldown_seconds=45.0,
    )
    t0 = 8000.0
    cur_t = t0
    # First trade sets timestamp baseline
    assert not guard.update(trade_volume=1.0, trade_timestamp=cur_t, current_time=cur_t)

    # 6 trades spaced exactly 0.050s apart
    for i in range(1, 7):
        cur_t += 0.050
        blocked = guard.update(trade_volume=1.0, trade_timestamp=cur_t, current_time=cur_t)
        if i < 6:
            assert not blocked
        else:
            assert blocked

    assert guard.is_blocked(cur_t)
    status = guard.get_status(cur_t)
    assert "DETERMINISTIC_SLICING_STREAK" in status["last_block_reason"]
    assert status["identical_interval_streak"] >= 6


def test_wave323_hyper_persistent_cascade_blocks():
    """Verify hyper-persistent runaway cascade triggers block."""
    guard = Wave323TradeArrivalSelfSimilarityHurstGuard(
        window_size=15,
        h_high_threshold=0.65,
        cascade_arrival_threshold_s=0.20,
        identical_streak_threshold=20,
        cooldown_seconds=45.0,
    )
    t0 = 9000.0
    cur_t = t0
    # Initial trade baseline
    guard.update(trade_volume=2.0, trade_timestamp=cur_t, current_time=cur_t)

    # Monotonically accelerating cascade: intervals decreasing steadily with low variance
    intervals = [0.18, 0.17, 0.16, 0.15, 0.14, 0.13, 0.12, 0.11, 0.10, 0.09, 0.08, 0.07, 0.06, 0.05, 0.04, 0.03]
    for dt in intervals:
        cur_t += dt
        blocked = guard.update(trade_volume=2.0, trade_timestamp=cur_t, current_time=cur_t)
        if blocked:
            break

    assert guard.is_blocked(cur_t)
    status = guard.get_status(cur_t)
    assert "HYPER_PERSISTENT_RUNAWAY_CASCADE" in status["last_block_reason"]
    assert status["hurst_exponent"] >= 0.65


def test_wave323_fail_closed_and_reset():
    """Verify timestamp inversion, non-numeric/bool inputs trip block and reset restores clean state."""
    guard = Wave323TradeArrivalSelfSimilarityHurstGuard(cooldown_seconds=20.0)
    t0 = 10000.0

    # Clean first trade
    assert not guard.update(1.0, t0, current_time=t0)

    # Timestamp inversion: t0 - 1.0 < t0
    assert guard.update(1.0, t0 - 1.0, current_time=t0 + 0.1)
    assert "TIMESTAMP_INVERSION" in guard.get_status(t0 + 0.1)["last_block_reason"]

    guard.reset()
    # Non-numeric input
    assert guard.update(True, t0 + 1.0, current_time=t0 + 1.0)
    assert "FAIL_CLOSED" in guard.get_status(t0 + 1.0)["last_block_reason"]

    guard.reset()
    assert guard.update(1.0, float("nan"), current_time=t0 + 2.0)
    assert "FAIL_CLOSED" in guard.get_status(t0 + 2.0)["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked(t0 + 3.0)
    assert guard.get_status(t0 + 3.0)["total_violations"] == 0
