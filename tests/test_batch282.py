"""Unit tests for Batch 282: Wave 330 and Wave 331 Risk & Microstructure Guards."""

import math
import time
import pytest

from wave330_lob_inside_quote_cancellation_ratio_guard import Wave330LOBInsideQuoteCancellationRatioGuard
from wave331_trade_arrival_tail_risk_hill_guard import Wave331TradeArrivalTailRiskHillGuard


# ==========================================
# Wave 330 Tests: Quote Cancellation Ratio [Landmark Wave 330]
# ==========================================

def test_wave330_balanced_adds_and_cancels_no_block():
    """Verify balanced addition and cancellation flow does not trigger cancellation ratio blocks."""
    guard = Wave330LOBInsideQuoteCancellationRatioGuard(
        window_size=20,
        cancel_ratio_threshold=0.88,
        cooldown_seconds=30.0,
    )
    t0 = 1000.0
    # Balanced 10 adds and 10 cancels with healthy resting lifetime 1.5s
    for i in range(20):
        ev = "ADD" if i % 2 == 0 else "CANCEL"
        blocked = guard.update(
            event_type=ev,
            volume=1.0,
            resting_lifetime_s=1.5,
            current_time=t0 + i * 0.1,
        )
        assert not blocked
        assert not guard.is_entry_blocked(t0 + i * 0.1)

    status = guard.get_status(t0 + 2.0)
    assert not status["is_blocked"]
    assert status["total_violations"] == 0
    assert status["cancel_ratio"] == 0.50


def test_wave330_extreme_cancellation_ratio_blocks():
    """Verify severe cancel dominance (ratio >= 0.88 with volume >= 15 lots) triggers ratio block."""
    guard = Wave330LOBInsideQuoteCancellationRatioGuard(
        window_size=20,
        cancel_ratio_threshold=0.85,
        min_volume_threshold=15.0,
        acute_barrage_streak_threshold=50,  # avoid acute barrage
        fleeting_lifetime_threshold_s=0.01,  # avoid fleeting lifetime
        cooldown_seconds=45.0,
    )
    t0 = 2000.0
    # 2 adds of 1.0 lot, then 18 cancels of 1.0 lot (total 20 lots, cancel ratio = 18/20 = 0.90 >= 0.85)
    for i in range(20):
        ev = "ADD" if i < 2 else "CANCEL"
        blocked = guard.update(
            event_type=ev,
            volume=1.0,
            resting_lifetime_s=1.0,
            current_time=t0 + i * 0.1,
        )
        if i < 19:
            assert not blocked
        else:
            assert blocked

    assert guard.is_blocked(t0 + 2.0)
    status = guard.get_status(t0 + 2.0)
    assert "EXTREME_CANCELLATION_RATIO" in status["last_block_reason"]
    assert status["cancel_ratio"] >= 0.85


def test_wave330_fleeting_lifetime_collapse_blocks():
    """Verify sub-100ms fleeting quote cancellations trigger lifetime collapse block."""
    guard = Wave330LOBInsideQuoteCancellationRatioGuard(
        window_size=20,
        fleeting_lifetime_threshold_s=0.08,
        fleeting_min_cancel_volume=12.0,
        acute_barrage_streak_threshold=50,
        cooldown_seconds=45.0,
    )
    t0 = 3000.0
    # Add initial liquidity
    for i in range(12):
        guard.update(event_type="ADD", volume=1.0, current_time=t0 + i * 0.1)

    # Rapid cancellations with mean lifetime 0.03s (< 0.08s) totaling 15.0 lots
    for i in range(8):
        blocked = guard.update(
            event_type="CANCEL",
            volume=2.0,
            resting_lifetime_s=0.03,
            current_time=t0 + 1.2 + i * 0.1,
        )
        if i == 7:
            assert blocked

    status = guard.get_status(t0 + 2.0)
    assert "FLEETING_LIFETIME_COLLAPSE" in status["last_block_reason"]


def test_wave330_acute_cancellation_barrage_blocks():
    """Verify sudden barrage of 10 consecutive cancellations in <= 0.25s triggers acute block."""
    guard = Wave330LOBInsideQuoteCancellationRatioGuard(
        acute_barrage_streak_threshold=10,
        acute_barrage_time_window_s=0.25,
        cooldown_seconds=45.0,
    )
    t0 = 4000.0
    # 10 cancellations occurring in 0.02s intervals (total 0.18s <= 0.25s)
    for i in range(10):
        blocked = guard.update(
            event_type="CANCEL",
            volume=1.0,
            resting_lifetime_s=0.5,
            current_time=t0 + i * 0.02,
        )
        if i < 9:
            assert not blocked
        else:
            assert blocked

    assert guard.is_blocked(t0 + 0.20)
    status = guard.get_status(t0 + 0.20)
    assert "ACUTE_CANCELLATION_BARRAGE" in status["last_block_reason"]
    assert status["cancel_streak"] >= 10


def test_wave330_fail_closed_and_reset():
    """Verify invalid event types, negative volumes/lifetimes fail closed and reset restores pristine state."""
    guard = Wave330LOBInsideQuoteCancellationRatioGuard(cooldown_seconds=20.0)
    t0 = 5000.0

    # Invalid event type
    assert guard.update("MODIFY", 1.0, current_time=t0)
    assert "FAIL_CLOSED" in guard.get_status(t0)["last_block_reason"]

    guard.reset()
    # Non-positive add volume
    assert guard.update("ADD", -1.0, current_time=t0 + 1.0)
    assert "FAIL_CLOSED" in guard.get_status(t0 + 1.0)["last_block_reason"]

    guard.reset()
    # Negative lifetime
    assert guard.update("CANCEL", 1.0, resting_lifetime_s=-0.5, current_time=t0 + 2.0)
    assert "FAIL_CLOSED" in guard.get_status(t0 + 2.0)["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked(t0 + 3.0)
    assert guard.get_status(t0 + 3.0)["total_violations"] == 0


# ==========================================
# Wave 331 Tests: Heavy-Tail Hill Estimator
# ==========================================

def test_wave331_exponential_trade_sizes_no_block():
    """Verify normal moderate trade size distribution yields high tail alpha and no block."""
    guard = Wave331TradeArrivalTailRiskHillGuard(
        window_size=20,
        hill_tail_threshold=1.10,
        cooldown_seconds=30.0,
    )
    t0 = 6000.0
    # Moderate volumes: 0.5 to 2.5 lots
    vols = [0.8, 1.2, 1.5, 2.0, 0.9, 1.1, 1.4, 2.2, 0.7, 1.3, 1.6, 2.1, 1.0, 1.5, 2.4, 0.9, 1.2, 1.7, 2.3, 1.1]
    for i, v in enumerate(vols):
        blocked = guard.update(trade_volume=v, current_time=t0 + i * 0.1)
        assert not blocked

    status = guard.get_status(t0 + 2.0)
    assert not status["is_blocked"]
    assert status["total_violations"] == 0
    assert status["hill_tail_alpha"] >= 1.50


def test_wave331_infinite_variance_tail_regime_blocks():
    """Verify heavy-tail Pareto distribution yields low tail alpha <= 1.10 and triggers block."""
    guard = Wave331TradeArrivalTailRiskHillGuard(
        window_size=20,
        hill_tail_threshold=1.10,
        top3_concentration_threshold=0.95,  # avoid top-3 trigger to test Hill
        acute_outlier_volume=100.0,  # avoid acute outlier
        cooldown_seconds=45.0,
    )
    t0 = 7000.0
    # Heavy tail distribution with extreme upper dispersion
    vols = [25.0, 20.0, 15.0, 12.0] + [2.0] * 14
    for i, v in enumerate(vols):
        blocked = guard.update(trade_volume=v, current_time=t0 + i * 0.1)

    assert guard.is_blocked(t0 + 2.0)
    status = guard.get_status(t0 + 2.0)
    assert "INFINITE_VARIANCE_TAIL_REGIME" in status["last_block_reason"]
    assert status["hill_tail_alpha"] <= 1.10


def test_wave331_acute_extreme_tail_outlier_blocks():
    """Verify rogue whale print (>=20.0 lots and >=15x median) triggers acute outlier block."""
    guard = Wave331TradeArrivalTailRiskHillGuard(
        acute_outlier_volume=20.0,
        acute_outlier_median_mult=15.0,
        cooldown_seconds=45.0,
    )
    t0 = 8000.0
    # 8 retail trades around 1.0 lot (median = 1.0)
    for i in range(8):
        assert not guard.update(trade_volume=1.0 + (i % 3) * 0.1, current_time=t0 + i * 0.1)

    # Acute outlier print: 25.0 lots (25x median >= 15x and >= 20.0)
    blocked = guard.update(trade_volume=25.0, current_time=t0 + 0.9)
    assert blocked

    status = guard.get_status(t0 + 0.9)
    assert status["is_blocked"]
    assert "ACUTE_EXTREME_TAIL_OUTLIER" in status["last_block_reason"]


def test_wave331_tail_volume_concentration_blocks():
    """Verify top-3 trades commanding >=65% of total volume triggers concentration block."""
    guard = Wave331TradeArrivalTailRiskHillGuard(
        window_size=15,
        top3_concentration_threshold=0.65,
        acute_outlier_volume=100.0,
        cooldown_seconds=45.0,
    )
    t0 = 9000.0
    # 10 trades: 3 prints of 10.0 lots (30.0 lots) and 7 prints of 1.0 lot (7.0 lots)
    # Total volume = 37.0 lots, top-3 ratio = 30.0 / 37.0 = 81.08% >= 65.0%
    vols = [10.0, 10.0, 10.0] + [1.0] * 7
    for i, v in enumerate(vols):
        blocked = guard.update(trade_volume=v, current_time=t0 + i * 0.1)
        if i == 9:
            assert blocked

    assert guard.is_blocked(t0 + 1.0)
    status = guard.get_status(t0 + 1.0)
    assert "TAIL_VOLUME_CONCENTRATION" in status["last_block_reason"]


def test_wave331_fail_closed_and_reset():
    """Verify non-numeric/bool/negative volume inputs fail closed and reset restores pristine state."""
    guard = Wave331TradeArrivalTailRiskHillGuard(cooldown_seconds=20.0)
    t0 = 10000.0

    # Non-numeric input
    assert guard.update(True, current_time=t0)
    assert "FAIL_CLOSED" in guard.get_status(t0)["last_block_reason"]

    guard.reset()
    # NaN volume
    assert guard.update(float("nan"), current_time=t0 + 1.0)
    assert "FAIL_CLOSED" in guard.get_status(t0 + 1.0)["last_block_reason"]

    guard.reset()
    # Non-positive volume
    assert guard.update(0.0, current_time=t0 + 2.0)
    assert "FAIL_CLOSED" in guard.get_status(t0 + 2.0)["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked(t0 + 3.0)
    assert guard.get_status(t0 + 3.0)["total_violations"] == 0
