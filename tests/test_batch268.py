"""
tests/test_batch268.py
----------------------
Unit tests for Batch 268:
  - Wave 302: Wave302LobSpreadJumpIntensityGuard
  - Wave 303: Wave303TradeSizeDispersionRatioGuard
"""

import math
import time
import pytest

from wave302_lob_spread_jump_intensity_guard import Wave302LobSpreadJumpIntensityGuard
from wave303_trade_size_dispersion_ratio_guard import Wave303TradeSizeDispersionRatioGuard


# ----------------------------------------------------------------------
# Wave 302 Tests: LOB Spread Jump Intensity & Poisson Discontinuity Guard
# ----------------------------------------------------------------------

def test_wave302_smooth_continuous_spread_no_block():
    guard = Wave302LobSpreadJumpIntensityGuard(
        jump_threshold_bps=2.20,
        max_jump_count=5,
        window_sec=30.0,
    )

    t0 = 1000.0
    # Feed 10 spread updates with minor fluctuations (< 0.50 bps)
    spread = 1.50
    for i in range(10):
        spread += 0.10 * (1 if i % 2 == 0 else -1)
        guard.record_spread(spread_bps=spread, ts=t0 + i * 2.0)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_jump_metrics()
    assert metrics["jump_count"] == 0
    assert metrics["jump_intensity"] == 0.0
    assert not metrics["is_blocked"]


def test_wave302_jump_intensity_surge_blocks():
    guard = Wave302LobSpreadJumpIntensityGuard(
        jump_threshold_bps=2.00,
        max_jump_count=5,
        window_sec=30.0,
        cooldown_seconds=45.0,
    )

    t0 = 1000.0
    base = 1.0
    # Produce 5 jumps >= 2.00 bps within 20s
    for i in range(5):
        guard.record_spread(spread_bps=base, ts=t0 + i * 3.0)
        base += 2.50
        guard.record_spread(spread_bps=base, ts=t0 + i * 3.0 + 1.0)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    status = guard.get_status()
    assert status["is_blocked"]
    assert "SPREAD_JUMP_INTENSITY_SURGE" in status["last_block_reason"]


def test_wave302_acute_double_jump_blocks():
    guard = Wave302LobSpreadJumpIntensityGuard(
        acute_jump_size_bps=3.00,
        acute_double_jump_window_sec=2.0,
        cooldown_seconds=45.0,
    )

    t0 = 1000.0
    # Baseline
    guard.record_spread(spread_bps=1.0, ts=t0)
    # Jump 1 (+3.50 bps)
    guard.record_spread(spread_bps=4.50, ts=t0 + 0.5)
    assert not guard.is_entry_blocked()

    # Jump 2 (+3.20 bps) within 1.0s of Jump 1
    guard.record_spread(spread_bps=7.70, ts=t0 + 1.2)

    assert guard.is_entry_blocked()
    metrics = guard.get_jump_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_SPREAD_DOUBLE_JUMP" in metrics["last_block_reason"]


def test_wave302_direct_jump_metrics_and_insufficient_samples():
    guard = Wave302LobSpreadJumpIntensityGuard(
        max_jump_count=5,
        cooldown_seconds=45.0,
    )

    # 3 jumps (below threshold 5)
    guard.record_jump_metrics(jump_count=3, jump_intensity=0.10)
    assert not guard.is_entry_blocked()

    # 6 jumps (exceeds threshold 5)
    guard.record_jump_metrics(jump_count=6, jump_intensity=0.20)
    assert guard.is_entry_blocked()
    assert "SPREAD_JUMP_INTENSITY_SURGE" in guard.get_status()["last_block_reason"]


def test_wave302_fail_closed_and_reset():
    guard = Wave302LobSpreadJumpIntensityGuard(cooldown_seconds=45.0)

    # Corrupted inputs: None, bool, NaN, Inf, negative
    for bad_val in [None, True, False, float("nan"), float("inf"), -1.5]:
        guard.record_spread(bad_val)
        assert guard.is_entry_blocked()
        assert "CORRUPTED_SPREAD_INPUT" in guard.get_status()["last_block_reason"]
        guard.reset()
        assert not guard.is_entry_blocked()

    # Update alias check
    guard.update(1.2)
    assert not guard.is_entry_blocked()


# ----------------------------------------------------------------------
# Wave 303 Tests: Trade Size Robust Dispersion Ratio Guard
# ----------------------------------------------------------------------

def test_wave303_normal_heterogeneous_trade_sizes_no_block():
    guard = Wave303TradeSizeDispersionRatioGuard(
        min_dispersion_ratio=0.10,
        max_dispersion_ratio=3.50,
        min_samples=12,
    )

    # Natural heterogeneous order flow: mixture of retail and mid-sized trades
    heterogeneous_trades = [0.2, 0.5, 1.0, 0.3, 0.8, 1.5, 0.4, 2.0, 0.6, 1.2, 0.5, 1.8, 0.7, 1.1, 0.9]
    for size in heterogeneous_trades:
        guard.record_trade_size(size)
        assert not guard.is_entry_blocked()
        assert not guard.is_blocked()

    metrics = guard.get_dispersion_metrics()
    assert 0.15 <= metrics["dispersion_ratio"] <= 3.0
    assert not metrics["is_blocked"]


def test_wave303_algorithmic_slicing_degeneracy_blocks():
    guard = Wave303TradeSizeDispersionRatioGuard(
        min_dispersion_ratio=0.10,
        min_samples=12,
        cooldown_seconds=45.0,
    )

    # TWAP/VWAP algo slicing 0.50 lots repeatedly with zero or trivial deviation
    for _ in range(14):
        guard.record_trade_size(0.50)

    assert guard.is_entry_blocked()
    assert guard.is_blocked()
    status = guard.get_status()
    assert status["is_blocked"]
    # Triggers either identical slicing streak or slicing degeneracy
    assert ("SLICING_DEGENERACY" in status["last_block_reason"] or 
            "ACUTE_IDENTICAL_SLICING_STREAK" in status["last_block_reason"])


def test_wave303_acute_whale_print_blocks():
    guard = Wave303TradeSizeDispersionRatioGuard(
        acute_whale_lots=15.0,
        cooldown_seconds=45.0,
    )

    # Baseline moderate trades
    for size in [0.5, 0.8, 0.6, 1.0, 0.7]:
        guard.record_trade_size(size)
        assert not guard.is_entry_blocked()

    # Acute massive whale print of 25.0 lots
    guard.record_trade_size(25.0)

    assert guard.is_entry_blocked()
    metrics = guard.get_dispersion_metrics()
    assert metrics["is_blocked"]
    assert "ACUTE_OUTLIER_WHALE" in metrics["last_block_reason"]


def test_wave303_identical_slicing_streak_blocks():
    guard = Wave303TradeSizeDispersionRatioGuard(
        acute_identical_streak=8,
        min_samples=15,  # Min samples for dispersion ratio not reached yet
        cooldown_seconds=45.0,
    )

    # 7 identical trades -> not yet 8
    for _ in range(7):
        guard.record_trade_size(1.25)
        assert not guard.is_entry_blocked()

    # 8th identical trade -> trips acute slicing streak
    guard.record_trade_size(1.25)
    assert guard.is_entry_blocked()
    assert "ACUTE_IDENTICAL_SLICING_STREAK" in guard.get_status()["last_block_reason"]


def test_wave303_fail_closed_and_reset():
    guard = Wave303TradeSizeDispersionRatioGuard(cooldown_seconds=45.0)

    # Corrupted inputs: None, bool, NaN, Inf, zero, negative
    for bad_val in [None, True, False, float("nan"), float("inf"), 0.0, -2.5]:
        guard.record_trade_size(bad_val)
        assert guard.is_entry_blocked()
        assert "CORRUPTED_TRADE_SIZE_INPUT" in guard.get_status()["last_block_reason"]
        guard.reset()
        assert not guard.is_entry_blocked()

    # Update alias check
    guard.update(1.0)
    assert not guard.is_entry_blocked()
    assert guard.get_dispersion_metrics()["mean_size"] == 1.0
