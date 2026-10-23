"""Unit tests for Batch 279: Wave 324 and Wave 325 Risk & Microstructure Guards."""

import math
import time
import pytest

from wave324_lob_micro_price_lead_lag_asynchrony_guard import Wave324LOBMicroPriceLeadLagAsynchronyGuard
from wave325_trade_flow_signed_run_length_burst_guard import Wave325TradeFlowSignedRunLengthBurstGuard


# ==========================================
# Wave 324 Tests: Micro-Price Lead-Lag
# ==========================================

def test_wave324_balanced_micro_price_no_block():
    """Verify balanced order book does not trigger displacement blocks."""
    guard = Wave324LOBMicroPriceLeadLagAsynchronyGuard(
        window_size=10,
        max_displacement_ratio=0.42,
        cooldown_seconds=30.0,
    )
    t0 = 1000.0
    for i in range(15):
        # Balanced queues: 2.0 vs 2.1 lots
        blocked = guard.update(
            bid_price=1.1000,
            ask_price=1.1002,
            bid_depth=2.0,
            ask_depth=2.1,
            current_time=t0 + i * 0.5,
        )
        assert not blocked
        assert not guard.is_entry_blocked(t0 + i * 0.5)

    status = guard.get_status(t0 + 15)
    assert not status["is_blocked"]
    assert status["total_violations"] == 0
    assert status["buffer_fill"] == 10


def test_wave324_predictive_displacement_surge_blocks():
    """Verify persistent extreme queue imbalance driving micro-price displacement triggers block."""
    guard = Wave324LOBMicroPriceLeadLagAsynchronyGuard(
        window_size=10,
        max_displacement_ratio=0.40,
        cooldown_seconds=45.0,
    )
    t0 = 2000.0
    # Extreme bid-heavy queue: Q_bid = 20.0, Q_ask = 1.0 (disp ratio = 19/21 * 0.5 ~= 0.452 > 0.40)
    for i in range(12):
        blocked = guard.update(
            bid_price=1.1000,
            ask_price=1.1002,
            bid_depth=20.0,
            ask_depth=1.0,
            current_time=t0 + i * 0.5,
        )
        if i < 9:
            assert not blocked
        else:
            assert blocked

    assert guard.is_blocked(t0 + 12)
    status = guard.get_status(t0 + 12)
    assert "PREDICTIVE_DISPLACEMENT_SURGE" in status["last_block_reason"]
    assert status["rolling_mean_displacement_ratio"] >= 0.40


def test_wave324_acute_micro_price_lead_shock_blocks():
    """Verify rapid acute shift in micro-price displacement triggers lead shock block."""
    guard = Wave324LOBMicroPriceLeadLagAsynchronyGuard(
        acute_displacement_bps=3.0,
        acute_time_window_s=0.10,
        cooldown_seconds=45.0,
    )
    t0 = 3000.0
    # Tick 1: balanced book at mid 1.0000
    assert not guard.update(
        bid_price=0.9990,
        ask_price=1.0010,
        bid_depth=10.0,
        ask_depth=10.0,
        current_time=t0,
    )

    # Tick 2: 0.05s later, sudden massive bid wall (Q_bid = 100, Q_ask = 0.5)
    # Delta micro jumps by ~0.00095 on 1.0000 price (~9.5 bps > 3.0 bps)
    blocked = guard.update(
        bid_price=0.9990,
        ask_price=1.0010,
        bid_depth=100.0,
        ask_depth=0.5,
        current_time=t0 + 0.05,
    )
    assert blocked
    assert guard.is_blocked(t0 + 0.05)
    status = guard.get_status(t0 + 0.05)
    assert "ACUTE_MICRO_PRICE_LEAD_SHOCK" in status["last_block_reason"]


def test_wave324_boundary_crossing_and_crossed_book_blocks():
    """Verify crossed book and invalid depth inputs fail closed immediately."""
    guard = Wave324LOBMicroPriceLeadLagAsynchronyGuard(cooldown_seconds=30.0)
    t0 = 4000.0

    # Crossed book
    assert guard.update(1.1005, 1.1000, 5.0, 5.0, current_time=t0)
    assert "FAIL_CLOSED" in guard.get_status(t0)["last_block_reason"]

    guard.reset()
    # Non-positive depth
    assert guard.update(1.1000, 1.1002, 0.0, 5.0, current_time=t0 + 1.0)
    assert "FAIL_CLOSED" in guard.get_status(t0 + 1.0)["last_block_reason"]


def test_wave324_fail_closed_and_reset():
    """Verify non-numeric/bool/NaN inputs fail closed and reset restores pristine state."""
    guard = Wave324LOBMicroPriceLeadLagAsynchronyGuard(cooldown_seconds=20.0)
    t0 = 5000.0

    assert guard.update(True, 1.1002, 1.0, 1.0, current_time=t0)
    assert "FAIL_CLOSED" in guard.get_status(t0)["last_block_reason"]

    guard.reset()
    assert guard.update(1.1000, float("nan"), 1.0, 1.0, current_time=t0)
    assert "FAIL_CLOSED" in guard.get_status(t0)["last_block_reason"]

    guard.reset()
    assert guard.update(1.1000, 1.1002, float("inf"), 1.0, current_time=t0)
    assert "FAIL_CLOSED" in guard.get_status(t0)["last_block_reason"]

    guard.reset()
    assert not guard.is_blocked(t0)
    assert guard.get_status(t0)["total_violations"] == 0


# ==========================================
# Wave 325 Tests: Signed Run-Length Burst
# ==========================================

def test_wave325_alternating_trade_flow_no_block():
    """Verify balanced alternating order flow does not trigger run-length blocks."""
    guard = Wave325TradeFlowSignedRunLengthBurstGuard(
        max_run_length=8,
        max_run_volume=12.0,
        cooldown_seconds=30.0,
    )
    t0 = 6000.0
    # Natural alternating trades: buy, sell, buy, sell
    for i in range(20):
        sign = 1 if i % 2 == 0 else -1
        blocked = guard.update(trade_volume=1.0, trade_sign=sign, current_time=t0 + i)
        assert not blocked

    status = guard.get_status(t0 + 20)
    assert not status["is_blocked"]
    assert status["total_violations"] == 0


def test_wave325_toxic_run_length_sweep_blocks():
    """Verify prolonged monotonic run with heavy volume triggers sweep block."""
    guard = Wave325TradeFlowSignedRunLengthBurstGuard(
        max_run_length=8,
        max_run_volume=12.0,
        cooldown_seconds=45.0,
    )
    t0 = 7000.0
    # 8 consecutive buy trades of 1.75 lots (total = 14.0 lots >= 12.0)
    for i in range(8):
        blocked = guard.update(trade_volume=1.75, trade_sign=1, current_time=t0 + i)
        if i < 7:
            assert not blocked
        else:
            assert blocked

    assert guard.is_blocked(t0 + 8)
    status = guard.get_status(t0 + 8)
    assert "TOXIC_RUN_LENGTH_SWEEP" in status["last_block_reason"]
    assert status["current_run_length"] == 8
    assert status["current_run_volume"] >= 12.0


def test_wave325_acute_in_run_volume_acceleration_blocks():
    """Verify sudden explosive volume ramp within an active run triggers acceleration block."""
    guard = Wave325TradeFlowSignedRunLengthBurstGuard(
        acceleration_factor=2.5,
        acceleration_min_volume=5.0,
        cooldown_seconds=45.0,
    )
    t0 = 8000.0
    # Trade 1: normal buy 1.5 lots
    assert not guard.update(trade_volume=1.5, trade_sign=1, current_time=t0)
    # Trade 2: buy 1.8 lots
    assert not guard.update(trade_volume=1.8, trade_sign=1, current_time=t0 + 0.1)
    # Trade 3: sudden whale sweep of 6.0 lots (3.33x prior >= 2.5x and >= 5.0)
    blocked = guard.update(trade_volume=6.0, trade_sign=1, current_time=t0 + 0.2)
    assert blocked

    status = guard.get_status(t0 + 0.2)
    assert "ACUTE_IN_RUN_VOLUME_ACCELERATION" in status["last_block_reason"]


def test_wave325_rolling_run_length_concentration_blocks():
    """Verify persistent long runs trigger concentration block upon run completion."""
    guard = Wave325TradeFlowSignedRunLengthBurstGuard(
        run_history_window=8,
        mean_run_length_threshold=4.0,
        max_run_length=20,  # avoid triggering sweep
        max_run_volume=100.0,
        cooldown_seconds=45.0,
    )
    t0 = 9000.0
    cur_t = t0

    # Execute 8 runs of 5 trades each (alternating sign between runs)
    current_sign = 1
    for r in range(9):
        for t in range(5):
            cur_t += 0.1
            blocked = guard.update(trade_volume=0.5, trade_sign=current_sign, current_time=cur_t)
            if r == 8 and t == 0:
                # The 8th run just completed upon first trade of 9th run!
                assert blocked
        current_sign *= -1

    status = guard.get_status(cur_t)
    assert "RUN_LENGTH_CONCENTRATION" in status["last_block_reason"]


def test_wave325_fail_closed_and_reset():
    """Verify invalid signs, non-numeric/bool inputs fail closed and reset restores pristine state."""
    guard = Wave325TradeFlowSignedRunLengthBurstGuard(cooldown_seconds=20.0)
    t0 = 10000.0

    # Non-numeric input
    assert guard.update(True, 1, current_time=t0)
    assert "FAIL_CLOSED" in guard.get_status(t0)["last_block_reason"]

    guard.reset()
    # Invalid trade sign (e.g. 0 or 2)
    assert guard.update(1.0, 0, current_time=t0 + 1.0)
    assert "FAIL_CLOSED" in guard.get_status(t0 + 1.0)["last_block_reason"]

    guard.reset()
    # Non-positive volume
    assert guard.update(-2.0, 1, current_time=t0 + 2.0)
    assert "FAIL_CLOSED" in guard.get_status(t0 + 2.0)["last_block_reason"]

    guard.reset()
    assert not guard.is_entry_blocked(t0 + 3.0)
    assert guard.get_status(t0 + 3.0)["total_violations"] == 0
