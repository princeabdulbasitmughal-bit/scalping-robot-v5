"""
tests/test_batch84.py
Batch 84 Unit Tests: Institutional RiskGuard Defense-in-Depth & 10 Safety Invariants (python_engine/risk_guard.py).
Expands test baseline beyond 1,087+ passing tests.
Verifies:
1. Decision: Subclass duality (dict indexing vs attribute access) and truthiness.
2. _is_valid_num: Helper validation across integers, floats, booleans, NaN, and Inf.
3. RiskGuard: State persistence, atomic swap, and fail-closed recovery on corrupted state.
4. RiskGuard: UTC day rollover and permanent balance-floor halt retention.
5. RiskGuard: record_trade PnL aggregation, tripwire trigger, and manual reset functions.
6. RiskGuard: Invariant 4 Kill switch via config flag and file sentinel.
7. RiskGuard: Invariant 5 Balance floor and cumulative daily loss order blocking.
8. RiskGuard: Invariant 6 Max open positions, max trades/day, and minimum trade cooldown.
9. RiskGuard: Invariants 7 & 8 Spread guard, millisecond timestamp normalization, and stale tick rejection.
10. RiskGuard: Invariants 1, 2, 3 & 10 Mandatory Stop-Loss, directional alignment, and lot quantization.
"""

import math
import time
from pathlib import Path
import pytest

from python_engine.risk_guard import RiskGuard, Decision, _is_valid_num


def test_risk_guard_decision_object_duality():
    """Verify Decision allows both dict indexing and attribute access with proper boolean evaluation."""
    d_true = Decision(allowed=True, reason="ORDER_APPROVED", lot=0.05)
    assert d_true.allowed is True
    assert d_true["allowed"] is True
    assert d_true.reason == "ORDER_APPROVED"
    assert d_true["reason"] == "ORDER_APPROVED"
    assert d_true.lot == 0.05
    assert d_true["lot"] == 0.05
    assert bool(d_true) is True
    assert "Decision(allowed=True" in repr(d_true)

    d_false = Decision(allowed=False, reason="KILL_SWITCH_ACTIVE", lot=0.0)
    assert d_false.allowed is False
    assert d_false["allowed"] is False
    assert bool(d_false) is False


def test_risk_guard_is_valid_num_validation():
    """Verify _is_valid_num correctly accepts valid finite numbers and rejects invalid types."""
    # Valid numbers
    assert _is_valid_num(10) is True
    assert _is_valid_num(-5.5) is True
    assert _is_valid_num(0.0) is True

    # Invalid types and non-finite numbers
    assert _is_valid_num(True) is False   # bool is subclass of int in Python
    assert _is_valid_num(False) is False
    assert _is_valid_num(None) is False
    assert _is_valid_num("100.0") is False
    assert _is_valid_num(float("nan")) is False
    assert _is_valid_num(float("inf")) is False
    assert _is_valid_num(float("-inf")) is False
    assert _is_valid_num([]) is False


def test_risk_guard_state_persistence_and_atomic_save(tmp_path):
    """Verify RiskGuard initializes, atomically writes state, and fails closed on corrupt state."""
    state_file = tmp_path / "risk_state.json"
    rg = RiskGuard(config={}, state_path=state_file)

    assert state_file.exists()
    assert rg.state["daily_pnl"] == 0.0
    assert rg.state["daily_loss_halted"] is False
    assert rg.state["balance_floor_halted"] is False

    # Corrupt state file and reload
    state_file.write_text("{CORRUPTED_JSON", encoding="utf-8")
    rg_corrupt = RiskGuard(config={}, state_path=state_file)
    assert rg_corrupt.state["daily_loss_halted"] is True
    assert rg_corrupt.state["balance_floor_halted"] is True
    assert rg_corrupt.state["daily_pnl"] == -999999.0


def test_risk_guard_day_rollover_and_balance_floor_permanence(tmp_path):
    """Verify UTC day rollover resets daily metrics while permanently preserving balance_floor_halted."""
    state_file = tmp_path / "risk_state.json"

    # Simulated clock starting at day 1
    current_time = 1750000000.0  # Epoch timestamp
    rg = RiskGuard(config={}, state_path=state_file, clock=lambda: current_time)

    # Trip both daily loss and balance floor
    rg.state["daily_loss_halted"] = True
    rg.state["daily_pnl"] = -250.0
    rg.state["balance_floor_halted"] = True
    rg.state["trade_count_today"] = 10
    rg._save_state()

    # Advance clock by 24 hours (86,400s) to next UTC day
    current_time += 86400.0
    rg._check_day_rollover()

    # Daily counters reset, but balance_floor_halted MUST remain True!
    assert rg.state["daily_pnl"] == 0.0
    assert rg.state["daily_loss_halted"] is False
    assert rg.state["trade_count_today"] == 0
    assert rg.state["balance_floor_halted"] is True


def test_risk_guard_record_trade_and_fail_closed_on_error(tmp_path):
    """Verify record_trade aggregates PnL, triggers daily loss halt, and fails closed on exception."""
    state_file = tmp_path / "risk_state.json"
    rg = RiskGuard(config={"max_daily_loss_usd": 100.0}, state_path=state_file)

    # First trade: loss of $40 (total -$40) -> not halted
    rg.record_trade(-40.0)
    assert rg.state["daily_pnl"] == -40.0
    assert rg.state["daily_loss_halted"] is False
    assert rg.state["trade_count_today"] == 1

    # Second trade: loss of $70 (total -$110 <= -$100) -> tripped daily_loss_halted
    rg.record_trade(-70.0)
    assert rg.state["daily_pnl"] == -110.0
    assert rg.state["daily_loss_halted"] is True
    assert rg.state["trade_count_today"] == 2

    # Reset daily loss
    rg.reset_daily_loss()
    assert rg.state["daily_loss_halted"] is False
    assert rg.state["daily_pnl"] == 0.0

    # Test fail-closed on unhandled error during record_trade
    rg.record_trade("INVALID_PNL")  # type: ignore
    assert rg.state["daily_loss_halted"] is True


def test_risk_guard_kill_switch_sentinel_and_config(tmp_path):
    """Verify Invariant 4: Kill switch blocks orders via config flag or physical sentinel file."""
    kill_file = tmp_path / "KILL_SWITCH"
    state_file = tmp_path / "risk_state.json"

    # 1. Config kill_switch = True
    rg_cfg = RiskGuard(config={"kill_switch": True}, state_path=state_file)
    dec1 = rg_cfg.check_order({"type": "BUY"}, {"balance": 10000.0}, {"spread": 1.0})
    assert not dec1.allowed
    assert "KILL_SWITCH_ACTIVE" in dec1.reason

    # 2. File sentinel kill switch
    rg_file = RiskGuard(config={"kill_switch_path": kill_file}, state_path=state_file)
    kill_file.write_text("HALT ALL TRADING", encoding="utf-8")
    dec2 = rg_file.check_order({"type": "BUY"}, {"balance": 10000.0}, {"spread": 1.0})
    assert not dec2.allowed
    assert "KILL_SWITCH_ACTIVE" in dec2.reason

    # Remove sentinel file -> allowed to proceed
    kill_file.unlink()
    # Check that without kill switch, it proceeds past Invariant 4
    dec3 = rg_file.check_order({"type": "BUY"}, {"balance": 10000.0}, {"spread": 1.0})
    assert "KILL_SWITCH" not in dec3.reason


def test_risk_guard_balance_floor_and_daily_loss_order_blocking(tmp_path):
    """Verify Invariant 5: Orders are blocked when balance drops below floor or daily loss exceeds limit."""
    state_file = tmp_path / "risk_state.json"
    rg = RiskGuard(
        config={"min_balance_usd": 9700.0, "max_daily_loss_usd": 200.0},
        state_path=state_file,
    )

    base_order = {"type": "BUY", "price": 2650.0, "sl": 2645.0, "lots": 0.02}
    base_market = {"spread_pips": 1.0, "tick_time": time.time(), "pip_size": 0.1}

    # 1. Balance below floor ($9650 < $9700)
    dec_floor = rg.check_order(base_order, {"balance": 9650.0}, base_market)
    assert not dec_floor.allowed
    assert "BALANCE_FLOOR_HALTED" in dec_floor.reason
    assert rg.state["balance_floor_halted"] is True

    # Reset balance floor for next test
    rg.reset_balance_floor()

    # 2. Daily loss exceeded ($250 > $200)
    rg.state["daily_pnl"] = -250.0
    rg._save_state()
    dec_loss = rg.check_order(base_order, {"balance": 10000.0}, base_market)
    assert not dec_loss.allowed
    assert "DAILY_LOSS_HALTED" in dec_loss.reason


def test_risk_guard_order_cooldown_and_capacity_limits(tmp_path):
    """Verify Invariant 6: Max open positions, max trades/day, and minimum cooldown between trades."""
    state_file = tmp_path / "risk_state.json"
    now_ts = 1750000000.0
    rg = RiskGuard(
        config={
            "max_open_positions": 2,
            "max_trades_per_day": 5,
            "min_time_between_trades_sec": 30.0,
        },
        state_path=state_file,
        clock=lambda: now_ts,
    )

    base_order = {"type": "BUY", "price": 2650.0, "sl": 2645.0, "lots": 0.02}
    base_market = {"spread_pips": 1.0, "tick_time": now_ts, "pip_size": 0.1}

    # 1. Max positions reached (2 >= 2)
    dec_pos = rg.check_order(base_order, {"balance": 10000.0, "open_positions": 2}, base_market)
    assert not dec_pos.allowed
    assert "MAX_POSITIONS_REACHED" in dec_pos.reason

    # 2. Max trades per day reached (5 >= 5)
    rg.state["trade_count_today"] = 5
    dec_trades = rg.check_order(base_order, {"balance": 10000.0, "open_positions": 0}, base_market)
    assert not dec_trades.allowed
    assert "MAX_TRADES_PER_DAY_REACHED" in dec_trades.reason
    rg.state["trade_count_today"] = 0

    # 3. Cooldown active: last trade 10s ago < min cooldown 30s
    rg.state["last_trade_time"] = now_ts - 10.0
    dec_cool = rg.check_order(base_order, {"balance": 10000.0, "open_positions": 0}, base_market)
    assert not dec_cool.allowed
    assert "COOLDOWN_ACTIVE" in dec_cool.reason


def test_risk_guard_spread_and_stale_tick_guards(tmp_path):
    """Verify Invariants 7 & 8: Excessive spread, negative spread, stale ticks, and future ticks rejection."""
    state_file = tmp_path / "risk_state.json"
    now_ts = 1750000000.0
    rg = RiskGuard(
        config={"spread_filter_pips": 2.5, "max_tick_age_sec": 3.0},
        state_path=state_file,
        clock=lambda: now_ts,
    )

    base_order = {"type": "BUY", "price": 2650.0, "sl": 2645.0, "lots": 0.02}

    # 1. Spread exceeded (3.0 > 2.5)
    m_spread = {"spread_pips": 3.0, "tick_time": now_ts}
    dec_spread = rg.check_order(base_order, {"balance": 10000.0}, m_spread)
    assert not dec_spread.allowed
    assert "SPREAD_EXCEEDED" in dec_spread.reason

    # 2. Negative spread invalid
    m_neg = {"spread_pips": -0.5, "tick_time": now_ts}
    dec_neg = rg.check_order(base_order, {"balance": 10000.0}, m_neg)
    assert not dec_neg.allowed
    assert "FAIL_CLOSED" in dec_neg.reason

    # 3. Stale tick (age 5.0s > 3.0s)
    m_stale = {"spread_pips": 1.0, "tick_time": now_ts - 5.0}
    dec_stale = rg.check_order(base_order, {"balance": 10000.0}, m_stale)
    assert not dec_stale.allowed
    assert "STALE_TICK" in dec_stale.reason

    # 4. Millisecond timestamp normalized correctly (1750000000000 ms = 1750000000.0 s)
    m_ms = {"spread_pips": 1.0, "tick_time": now_ts * 1000.0, "pip_size": 0.1}
    dec_ms = rg.check_order(base_order, {"balance": 10000.0}, m_ms)
    assert "STALE_TICK" not in dec_ms.reason

    # 5. Future tick beyond 10s rejected
    m_future = {"spread_pips": 1.0, "tick_time": now_ts + 20.0}
    dec_future = rg.check_order(base_order, {"balance": 10000.0}, m_future)
    assert not dec_future.allowed
    assert "future" in dec_future.reason.lower()


def test_risk_guard_sl_mandatory_and_lot_quantization(tmp_path):
    """Verify Invariants 1, 2, 3 & 10: Mandatory SL, side check, risk ceiling, and lot quantization."""
    state_file = tmp_path / "risk_state.json"
    now_ts = 1750000000.0
    rg = RiskGuard(
        config={
            "max_lot_size": 0.05,
            "min_lot_size": 0.01,
            "lot_step": 0.01,
            "min_sl_pips": 10.0,
            "max_sl_pips": 100.0,
            "risk_per_trade_pct": 1.0,
            "contract_size": 100.0,
            "pip_size": 0.1,
        },
        state_path=state_file,
        clock=lambda: now_ts,
    )

    base_market = {"spread_pips": 1.0, "tick_time": now_ts, "pip_size": 0.1, "ask": 2650.0, "bid": 2649.9}

    # 1. Missing SL -> MANDATORY_SL_VIOLATION
    no_sl_order = {"type": "BUY", "price": 2650.0, "lots": 0.02}
    dec_no_sl = rg.check_order(no_sl_order, {"balance": 10000.0}, base_market)
    assert not dec_no_sl.allowed
    assert "MANDATORY_SL_VIOLATION" in dec_no_sl.reason

    # 2. BUY SL on wrong side (SL >= price)
    wrong_buy = {"type": "BUY", "price": 2650.0, "sl": 2651.0, "lots": 0.02}
    dec_wrong_buy = rg.check_order(wrong_buy, {"balance": 10000.0}, base_market)
    assert not dec_wrong_buy.allowed
    assert "SL_WRONG_SIDE" in dec_wrong_buy.reason

    # 3. SELL SL on wrong side (SL <= price)
    wrong_sell = {"type": "SELL", "price": 2650.0, "sl": 2649.0, "lots": 0.02}
    dec_wrong_sell = rg.check_order(wrong_sell, {"balance": 10000.0}, base_market)
    assert not dec_wrong_sell.allowed
    assert "SL_WRONG_SIDE" in dec_wrong_sell.reason

    # 4. SL distance too small (0.5 price = 5 pips < min 10 pips)
    short_sl = {"type": "BUY", "price": 2650.0, "sl": 2649.5, "lots": 0.02}
    dec_short = rg.check_order(short_sl, {"balance": 10000.0}, base_market)
    assert not dec_short.allowed
    assert "SL_DISTANCE_TOO_SMALL" in dec_short.reason

    # 5. Valid order with lot clamped to max_lot_size (0.05) and risk budget
    # price=2650, sl=2648 (dist=2.0 = 20 pips), requested lots=0.10
    # risk_per_trade_pct=1.0% of $10,000 = $100
    # dollar_risk per lot = 2.0 * 100 = $200 -> max allowed lots = 100 / 200 = 0.50
    # config max lot = 0.05 -> clamped to 0.05
    valid_order = {"type": "BUY", "price": 2650.0, "sl": 2648.0, "lots": 0.10}
    dec_valid = rg.check_order(valid_order, {"balance": 10000.0}, base_market)
    assert dec_valid.allowed is True
    assert dec_valid.reason == "ORDER_APPROVED"
    assert dec_valid.lot == 0.05
