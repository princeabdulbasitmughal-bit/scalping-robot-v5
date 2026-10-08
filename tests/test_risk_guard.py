"""
Comprehensive test suite for python_engine/risk_guard.py.
Validates all 10 safety invariants, edge cases, state persistence, UTC rollover,
fail-closed behavior, and property-based fuzzing.
"""
import json
import math
import os
from pathlib import Path
import random
import time
import pytest

from python_engine.risk_guard import RiskGuard, Decision


@pytest.fixture
def base_config(tmp_path):
    return {
        "max_lot_size": 0.10,
        "min_lot_size": 0.01,
        "lot_step": 0.01,
        "risk_per_trade_pct": 1.0,
        "contract_size": 100.0,
        "max_daily_loss_usd": 200.0,
        "min_balance_usd": 9700.0,
        "max_positions_per_session": 3,
        "max_trades_per_day": 50,
        "min_time_between_trades_sec": 60.0,
        "spread_filter_pips": 3.0,
        "max_tick_age_sec": 5.0,
        "min_sl_pips": 5.0,
        "max_sl_pips": 100.0,
        "pip_size": 0.1,
        "risk_state_path": str(tmp_path / "risk_state.json"),
        "kill_switch_path": str(tmp_path / "KILL_SWITCH"),
    }


@pytest.fixture
def valid_order():
    return {
        "order_type": "BUY",
        "price": 2400.0,
        "sl": 2397.0,  # 3.0 dollars = 30 pips distance
        "tp": 2404.5,
        "lots": 0.02,
    }


@pytest.fixture
def valid_account():
    return {
        "balance": 10000.0,
        "equity": 10000.0,
        "daily_pnl": 0.0,
        "open_positions": [],
    }


@pytest.fixture
def valid_market():
    now = time.time()
    return {
        "spread_pips": 1.5,
        "tick_time": now,
        "pip_size": 0.1,
        "min_lot": 0.01,
        "max_lot": 5.0,
        "lot_step": 0.01,
        "contract_size": 100.0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# INVARIANT 1: Mandatory Stop Loss (SL Lazmi)
# ─────────────────────────────────────────────────────────────────────────────

def test_invariant1_mandatory_sl_missing_rejected(base_config, valid_order, valid_account, valid_market):
    guard = RiskGuard(base_config)
    order_no_sl = dict(valid_order)
    order_no_sl["sl"] = None
    dec = guard.check_order(order_no_sl, valid_account, valid_market)
    assert not dec.allowed
    assert "MANDATORY_SL_VIOLATION" in dec.reason

    order_zero_sl = dict(valid_order, sl=0.0)
    dec2 = guard.check_order(order_zero_sl, valid_account, valid_market)
    assert not dec2.allowed
    assert "MANDATORY_SL_VIOLATION" in dec2.reason


def test_invariant1_mandatory_sl_wrong_side_buy(base_config, valid_order, valid_account, valid_market):
    guard = RiskGuard(base_config)
    # BUY order with SL above or equal to entry price
    order_bad = dict(valid_order, order_type="BUY", price=2400.0, sl=2405.0)
    dec = guard.check_order(order_bad, valid_account, valid_market)
    assert not dec.allowed
    assert "SL_WRONG_SIDE" in dec.reason

    order_equal = dict(valid_order, order_type="BUY", price=2400.0, sl=2400.0)
    dec_equal = guard.check_order(order_equal, valid_account, valid_market)
    assert not dec_equal.allowed
    assert "SL_WRONG_SIDE" in dec_equal.reason


def test_invariant1_mandatory_sl_wrong_side_sell(base_config, valid_order, valid_account, valid_market):
    guard = RiskGuard(base_config)
    # SELL order with SL below or equal to entry price
    order_bad = dict(valid_order, order_type="SELL", price=2400.0, sl=2395.0)
    dec = guard.check_order(order_bad, valid_account, valid_market)
    assert not dec.allowed
    assert "SL_WRONG_SIDE" in dec.reason

    order_equal = dict(valid_order, order_type="SELL", price=2400.0, sl=2400.0)
    dec_equal = guard.check_order(order_equal, valid_account, valid_market)
    assert not dec_equal.allowed
    assert "SL_WRONG_SIDE" in dec_equal.reason


def test_invariant1_sl_distance_bounds(base_config, valid_order, valid_account, valid_market):
    guard = RiskGuard(base_config)
    # min_sl_pips is 5.0 (0.5 price), test with distance 2 pips (0.2 price)
    order_too_close = dict(valid_order, price=2400.0, sl=2399.8)
    dec_close = guard.check_order(order_too_close, valid_account, valid_market)
    assert not dec_close.allowed
    assert "SL_DISTANCE_TOO_SMALL" in dec_close.reason

    # max_sl_pips is 100.0 (10.0 price), test with distance 150 pips (15.0 price)
    order_too_far = dict(valid_order, price=2400.0, sl=2385.0)
    dec_far = guard.check_order(order_too_far, valid_account, valid_market)
    assert not dec_far.allowed
    assert "SL_DISTANCE_TOO_LARGE" in dec_far.reason


def test_invariant1_valid_sl_allowed(base_config, valid_order, valid_account, valid_market):
    guard = RiskGuard(base_config)
    # Valid BUY (30 pips)
    dec_buy = guard.check_order(valid_order, valid_account, valid_market)
    assert dec_buy.allowed
    assert dec_buy.lot == 0.02

    # Valid SELL (30 pips, SL above price)
    order_sell = dict(valid_order, order_type="SELL", price=2400.0, sl=2403.0)
    dec_sell = guard.check_order(order_sell, valid_account, valid_market)
    assert dec_sell.allowed
    assert dec_sell.lot == 0.02


# ─────────────────────────────────────────────────────────────────────────────
# INVARIANT 2: Lot Cap & Normalization
# ─────────────────────────────────────────────────────────────────────────────

def test_invariant2_lot_cap_enforced(base_config, valid_order, valid_account, valid_market):
    guard = RiskGuard(base_config)
    # Requested 0.50 lots, but max_lot_size is 0.10
    order_big = dict(valid_order, lots=0.50, sl=2399.0)  # 10 pips sl
    dec = guard.check_order(order_big, valid_account, valid_market)
    assert dec.allowed
    assert dec.lot <= 0.10


def test_invariant2_lot_step_quantization(base_config, valid_order, valid_account, valid_market):
    guard = RiskGuard(base_config)
    # Requested 0.028 lots with lot_step 0.01 -> floored to 0.02
    order_fraction = dict(valid_order, lots=0.028)
    dec = guard.check_order(order_fraction, valid_account, valid_market)
    assert dec.allowed
    assert dec.lot == 0.02


def test_invariant2_lot_below_broker_min_rejected(base_config, valid_order, valid_account, valid_market):
    guard = RiskGuard(base_config)
    # Requested 0.005 lots with min_lot 0.01
    order_tiny = dict(valid_order, lots=0.005)
    dec = guard.check_order(order_tiny, valid_account, valid_market)
    assert not dec.allowed
    assert "RISK_CAP_EXCEEDED" in dec.reason or "FAIL_CLOSED" in dec.reason or "INVALID_LOT" in dec.reason


# ─────────────────────────────────────────────────────────────────────────────
# INVARIANT 3: Risk Per Trade Dollar Cap
# ─────────────────────────────────────────────────────────────────────────────

def test_invariant3_risk_per_trade_lot_reduction(base_config, valid_order, valid_account, valid_market):
    guard = RiskGuard(base_config)
    # Balance $10,000, risk_per_trade_pct = 1% => $100 max risk
    # Contract size = 100, SL distance = $5.00 (50 pips)
    # Dollar risk per lot = 5.0 * 100 = $500 per lot
    # Max allowed lot = 100 / 500 = 0.20 lots.
    # If order asks for 0.08 with SL distance 20.0 (200 pips max allowed: 100 pips):
    # With SL distance $8.0 (80 pips), dollar risk per lot = $800.
    # Max safe lot = $100 / $800 = 0.125 -> capped at 0.10 (max_lot_size) -> safe lot 0.10 gives $80, asks for 0.10: allowed.
    # Now test with balance $5,000 => max risk $50.
    # SL distance $3.0 (30 pips), dollar risk per lot = $300.
    # Max safe lot = $50 / $300 = 0.166 -> asks for 0.10: dollar risk is 0.10 * 300 = $30 <= $50, allowed!
    # If balance is $2,000 => max risk $20.
    # SL distance $3.0 => risk per lot = $300.
    # Max safe lot = $20 / $300 = 0.066 -> lot reduced to 0.06!
    small_acct = dict(valid_account, balance=10000.0)  # keep above min_balance
    # To trigger lot reduction:
    # balance 10,000, risk_per_trade_pct = 0.5% => $50 max risk
    guard.config["risk_per_trade_pct"] = 0.5
    # Order asks for 0.08 lot, SL distance = 2.0 ($200 per lot).
    # Dollar risk = 0.08 * 200 = $16. But if SL distance is $4.0:
    # Dollar risk per lot = $400. Max risk = $50. Max safe lot = 50 / 400 = 0.125.
    # If SL distance is $8.0: Dollar risk per lot = $800. Max risk = $50. Max safe lot = 50 / 800 = 0.0625 -> 0.06 lot!
    order_risk = dict(valid_order, lots=0.10, sl=2392.0)  # distance 8.0
    dec = guard.check_order(order_risk, small_acct, valid_market)
    assert dec.allowed
    assert dec.lot == 0.06  # reduced from 0.10 to 0.06


def test_invariant3_risk_exceeds_cap_even_at_min_lot_rejected(base_config, valid_order, valid_account, valid_market):
    guard = RiskGuard(base_config)
    # If allowed dollar risk is $5.00, but min lot (0.01) risk is $10.00
    guard.config["risk_per_trade_pct"] = 0.05  # 0.05% of $10,000 = $5.00
    # SL distance = $8.0 (80 pips). For 0.01 lot: 0.01 * 8.0 * 100 = $8.00 > $5.00!
    order_risk = dict(valid_order, lots=0.05, sl=2392.0)
    dec = guard.check_order(order_risk, valid_account, valid_market)
    assert not dec.allowed
    assert "RISK_CAP_EXCEEDED" in dec.reason


# ─────────────────────────────────────────────────────────────────────────────
# INVARIANT 4: Kill Switch File and Config Flag
# ─────────────────────────────────────────────────────────────────────────────

def test_invariant4_kill_switch_file_blocks(base_config, valid_order, valid_account, valid_market):
    guard = RiskGuard(base_config)
    kill_path = Path(base_config["kill_switch_path"])

    # Create kill switch file
    kill_path.write_text("EMERGENCY STOP")
    dec = guard.check_order(valid_order, valid_account, valid_market)
    assert not dec.allowed
    assert "KILL_SWITCH_ACTIVE" in dec.reason

    # Remove file -> allowed again
    kill_path.unlink()
    dec_after = guard.check_order(valid_order, valid_account, valid_market)
    assert dec_after.allowed


def test_invariant4_kill_switch_config_flag_blocks(base_config, valid_order, valid_account, valid_market):
    cfg = dict(base_config, kill_switch=True)
    guard = RiskGuard(cfg)
    dec = guard.check_order(valid_order, valid_account, valid_market)
    assert not dec.allowed
    assert "KILL_SWITCH_ACTIVE" in dec.reason


# ─────────────────────────────────────────────────────────────────────────────
# INVARIANT 5: Daily Loss Halt & Balance Floor Persistence
# ─────────────────────────────────────────────────────────────────────────────

def test_invariant5_balance_floor_triggers_permanent_halt(base_config, valid_order, valid_account, valid_market):
    guard = RiskGuard(base_config)
    # min_balance_usd is 9700, balance is 9650
    low_acct = dict(valid_account, balance=9650.0)
    dec = guard.check_order(valid_order, low_acct, valid_market)
    assert not dec.allowed
    assert "BALANCE_FLOOR_HALTED" in dec.reason

    # Even if balance magically goes up, permanent halt persists until manual reset!
    recovered_acct = dict(valid_account, balance=10500.0)
    dec2 = guard.check_order(valid_order, recovered_acct, valid_market)
    assert not dec2.allowed
    assert "BALANCE_FLOOR_HALTED" in dec2.reason


def test_invariant5_balance_floor_persists_across_restart(base_config, valid_order, valid_account, valid_market):
    guard1 = RiskGuard(base_config)
    low_acct = dict(valid_account, balance=9500.0)
    guard1.check_order(valid_order, low_acct, valid_market)

    # Simulate restart with fresh RiskGuard instance reading same state_path
    guard2 = RiskGuard(base_config)
    dec = guard2.check_order(valid_order, valid_account, valid_market)
    assert not dec.allowed
    assert "BALANCE_FLOOR_HALTED" in dec.reason


def test_invariant5_balance_floor_does_not_reset_on_utc_rollover(base_config, valid_order, valid_account, valid_market):
    current_time = 1770000000.0  # arbitrary epoch
    guard = RiskGuard(base_config, clock=lambda: current_time)
    market = dict(valid_market, tick_time=current_time)
    low_acct = dict(valid_account, balance=9500.0)
    guard.check_order(valid_order, low_acct, market)

    # Advance clock by 3 days (UTC rollover)
    future_time = current_time + (3 * 86400)
    market_future = dict(valid_market, tick_time=future_time)
    guard_future = RiskGuard(base_config, clock=lambda: future_time)
    dec = guard_future.check_order(valid_order, valid_account, market_future)
    # Balance floor must remain halted!
    assert not dec.allowed
    assert "BALANCE_FLOOR_HALTED" in dec.reason

    # Manual reset allows trading again
    guard_future.reset_balance_floor()
    dec_reset = guard_future.check_order(valid_order, valid_account, market_future)
    assert dec_reset.allowed


def test_invariant5_daily_loss_halt_persists_across_restart(base_config, valid_order, valid_account, valid_market):
    guard = RiskGuard(base_config)
    # Record losses exceeding $200
    guard.record_trade(-120.0)
    guard.record_trade(-90.0)  # total -210.0 <= -200.0

    dec = guard.check_order(valid_order, valid_account, valid_market)
    assert not dec.allowed
    assert "DAILY_LOSS_HALTED" in dec.reason

    # Restart
    guard_restarted = RiskGuard(base_config)
    dec_restarted = guard_restarted.check_order(valid_order, valid_account, valid_market)
    assert not dec_restarted.allowed
    assert "DAILY_LOSS_HALTED" in dec_restarted.reason


def test_invariant5_daily_loss_resets_on_utc_day_rollover(base_config, valid_order, valid_account, valid_market):
    now = 1770000000.0
    guard1 = RiskGuard(base_config, clock=lambda: now)
    market1 = dict(valid_market, tick_time=now)
    guard1.record_trade(-250.0)
    assert not guard1.check_order(valid_order, valid_account, market1).allowed

    # Advance to next UTC day (+86400 seconds)
    tomorrow = now + 86400.0
    market2 = dict(valid_market, tick_time=tomorrow)
    guard2 = RiskGuard(base_config, clock=lambda: tomorrow)
    dec = guard2.check_order(valid_order, valid_account, market2)
    # Daily loss reset on new day!
    assert dec.allowed
    assert guard2.state["daily_pnl"] == 0.0
    assert not guard2.state["daily_loss_halted"]


# ─────────────────────────────────────────────────────────────────────────────
# INVARIANT 6: Max Open Positions, Max Trades/Day, Min Time Between Trades
# ─────────────────────────────────────────────────────────────────────────────

def test_invariant6_max_open_positions_blocks(base_config, valid_order, valid_account, valid_market):
    guard = RiskGuard(base_config)
    # max_positions_per_session is 3
    acct_3_open = dict(valid_account, open_positions=[{"id": 1}, {"id": 2}, {"id": 3}])
    dec = guard.check_order(valid_order, acct_3_open, valid_market)
    assert not dec.allowed
    assert "MAX_POSITIONS_REACHED" in dec.reason


def test_invariant6_max_trades_per_day_blocks(base_config, valid_order, valid_account, valid_market):
    guard = RiskGuard(base_config)
    guard.config["max_trades_per_day"] = 5
    for _ in range(5):
        guard.record_trade(10.0)

    dec = guard.check_order(valid_order, valid_account, valid_market)
    assert not dec.allowed
    assert "MAX_TRADES_PER_DAY_REACHED" in dec.reason


def test_invariant6_min_time_between_trades_cooldown(base_config, valid_order, valid_account, valid_market):
    now = 100000.0
    guard = RiskGuard(base_config, clock=lambda: now)
    # Record trade at t = 100000
    guard.record_trade(15.0, timestamp=now)

    # Check order at t = 100030 (30s elapsed, min cooldown is 60s)
    guard.clock = lambda: now + 30.0
    market_30 = dict(valid_market, tick_time=now + 30.0)
    dec = guard.check_order(valid_order, valid_account, market_30)
    assert not dec.allowed
    assert "COOLDOWN_ACTIVE" in dec.reason

    # Check order at t = 100065 (65s elapsed > 60s)
    guard.clock = lambda: now + 65.0
    market_65 = dict(valid_market, tick_time=now + 65.0)
    dec_allowed = guard.check_order(valid_order, valid_account, market_65)
    assert dec_allowed.allowed


# ─────────────────────────────────────────────────────────────────────────────
# INVARIANT 7: Spread Guard
# ─────────────────────────────────────────────────────────────────────────────

def test_invariant7_spread_guard(base_config, valid_order, valid_account, valid_market):
    guard = RiskGuard(base_config)
    # spread_filter_pips is 3.0
    high_spread_market = dict(valid_market, spread_pips=3.5)
    dec = guard.check_order(valid_order, valid_account, high_spread_market)
    assert not dec.allowed
    assert "SPREAD_EXCEEDED" in dec.reason

    good_spread_market = dict(valid_market, spread_pips=2.8)
    dec_good = guard.check_order(valid_order, valid_account, good_spread_market)
    assert dec_good.allowed


# ─────────────────────────────────────────────────────────────────────────────
# INVARIANT 8: Stale Tick Guard
# ─────────────────────────────────────────────────────────────────────────────

def test_invariant8_stale_tick_guard(base_config, valid_order, valid_account, valid_market):
    now = 100000.0
    guard = RiskGuard(base_config, clock=lambda: now)
    # max_tick_age_sec is 5.0
    stale_market = dict(valid_market, tick_time=now - 6.5)
    dec = guard.check_order(valid_order, valid_account, stale_market)
    assert not dec.allowed
    assert "STALE_TICK" in dec.reason

    fresh_market = dict(valid_market, tick_time=now - 1.2)
    dec_fresh = guard.check_order(valid_order, valid_account, fresh_market)
    assert dec_fresh.allowed


# ─────────────────────────────────────────────────────────────────────────────
# INVARIANT 9: Fail-Closed Architecture (Garbage Inputs & Exceptions)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad_input", [
    None,
    "garbage_string",
    12345,
    [],
])
def test_invariant9_fail_closed_on_non_dict_inputs(base_config, valid_order, valid_account, valid_market, bad_input):
    guard = RiskGuard(base_config)
    assert not guard.check_order(bad_input, valid_account, valid_market).allowed
    assert not guard.check_order(valid_order, bad_input, valid_market).allowed
    assert not guard.check_order(valid_order, valid_account, bad_input).allowed


@pytest.mark.parametrize("corrupted_field,value", [
    ("price", float("nan")),
    ("price", float("inf")),
    ("price", -10.0),
    ("sl", float("nan")),
    ("sl", -5.0),
    ("lots", float("nan")),
    ("lots", 0.0),
    ("order_type", "UNKNOWN_DIRECTION"),
])
def test_invariant9_fail_closed_corrupted_order_fields(base_config, valid_order, valid_account, valid_market, corrupted_field, value):
    guard = RiskGuard(base_config)
    bad_order = dict(valid_order)
    bad_order[corrupted_field] = value
    dec = guard.check_order(bad_order, valid_account, valid_market)
    assert not dec.allowed
    assert "FAIL_CLOSED" in dec.reason or "MANDATORY_SL_VIOLATION" in dec.reason or "INVALID" in dec.reason


def test_invariant9_fail_closed_nan_account_balance(base_config, valid_order, valid_account, valid_market):
    guard = RiskGuard(base_config)
    bad_acct = dict(valid_account, balance=float("nan"))
    dec = guard.check_order(valid_order, bad_acct, valid_market)
    assert not dec.allowed
    assert "FAIL_CLOSED" in dec.reason


# ─────────────────────────────────────────────────────────────────────────────
# INVARIANT 10: Tightening Only & Fuzzing Property Test
# ─────────────────────────────────────────────────────────────────────────────

def test_invariant10_guard_tightens_limits_only(base_config, valid_order, valid_account, valid_market):
    # If config max_lot is 0.08 and broker max_lot is 0.15, effective max is 0.08
    base_config["max_lot_size"] = 0.08
    valid_market["max_lot"] = 0.15
    guard = RiskGuard(base_config)

    order = dict(valid_order, lots=0.10, sl=2399.0)  # low sl distance
    dec = guard.check_order(order, valid_account, valid_market)
    assert dec.allowed
    assert dec.lot <= 0.08

    # If broker max_lot is 0.05 and config is 0.08, effective max is 0.05
    valid_market["max_lot"] = 0.05
    dec2 = guard.check_order(order, valid_account, valid_market)
    assert dec2.allowed
    assert dec2.lot <= 0.05


def test_fuzzing_random_inputs_never_exceeds_max_lot(base_config, valid_account, valid_market):
    """
    Monte Carlo fuzzing with fixed seed: In all cases, guard never allows lot > max_lot_size,
    never crashes unhandled, and fails-closed on garbage.
    """
    random.seed(42)
    guard = RiskGuard(base_config)
    max_lot_size = base_config["max_lot_size"]

    for _ in range(200):
        rand_price = random.uniform(2000.0, 2600.0)
        rand_sl_offset = random.choice([
            random.uniform(-10.0, 10.0),
            0.0,
            float("nan"),
            float("inf"),
            -999.0,
        ])
        rand_lot = random.choice([
            random.uniform(0.001, 10.0),
            0.0,
            -1.0,
            float("nan"),
            0.05,
            0.15,
        ])
        rand_direction = random.choice(["BUY", "SELL", "HOLD", "INVALID", 0, 1, None])

        fuzz_order = {
            "order_type": rand_direction,
            "price": rand_price,
            "sl": rand_price + rand_sl_offset if not math.isnan(rand_sl_offset) else rand_sl_offset,
            "lots": rand_lot,
        }

        fuzz_market = dict(valid_market, spread_pips=random.uniform(0.1, 10.0))
        dec = guard.check_order(fuzz_order, valid_account, fuzz_market)

        if dec.allowed:
            # If allowed, MUST strictly respect all invariants
            assert dec.lot <= max_lot_size, f"Allowed lot {dec.lot} exceeded max {max_lot_size}"
            assert dec.lot >= base_config["min_lot_size"]
            assert dec.reason == "ORDER_APPROVED"
        else:
            assert isinstance(dec.reason, str)
            assert len(dec.reason) > 0


def test_invariant1_bool_values_rejected(base_config, valid_order, valid_account, valid_market):
    """Ensure Python bool-as-int inheritance does not bypass validation."""
    guard = RiskGuard(base_config)
    assert not guard.check_order(dict(valid_order, sl=True), valid_account, valid_market).allowed
    assert not guard.check_order(dict(valid_order, sl=False), valid_account, valid_market).allowed
    assert not guard.check_order(dict(valid_order, price=True), valid_account, valid_market).allowed
    assert not guard.check_order(dict(valid_order, lots=True), valid_account, valid_market).allowed
    assert not guard.check_order(valid_order, dict(valid_account, balance=True), valid_market).allowed


def test_invariant5_corrupted_state_file_fails_closed(base_config, valid_order, valid_account, valid_market):
    """If state file exists but is corrupted, guard fails-closed to prevent accidental un-halting."""
    state_file = Path(base_config["risk_state_path"])
    state_file.write_text("{{corrupted json invalid syntax")

    guard = RiskGuard(base_config)
    dec = guard.check_order(valid_order, valid_account, valid_market)
    assert not dec.allowed
    assert "HALTED" in dec.reason or "FAIL_CLOSED" in dec.reason


def test_integration_mt5_live_trader_has_risk_guard():
    """Verify MT5LiveTrader integrates RiskGuard in its pipeline."""
    from python_engine.mt5_live_trader import MT5LiveTrader
    trader = MT5LiveTrader({"symbol": "XAUUSD", "trading_mode": "paper"})
    assert trader.risk_guard is not None
    assert isinstance(trader.risk_guard, RiskGuard)


def test_invariant7_edge_cases_negative_and_invalid_spread(base_config, valid_order, valid_account, valid_market):
    """Verify spread guard rejects negative, boolean, NaN, inf, and missing spread."""
    guard = RiskGuard(base_config)
    # Negative spread
    dec_neg = guard.check_order(valid_order, valid_account, dict(valid_market, spread_pips=-1.0))
    assert not dec_neg.allowed
    assert "FAIL_CLOSED" in dec_neg.reason

    # Boolean spread
    dec_bool = guard.check_order(valid_order, valid_account, dict(valid_market, spread_pips=True))
    assert not dec_bool.allowed
    assert "FAIL_CLOSED" in dec_bool.reason

    # Missing spread
    mkt_no_spread = {k: v for k, v in valid_market.items() if "spread" not in k}
    dec_missing = guard.check_order(valid_order, valid_account, mkt_no_spread)
    assert not dec_missing.allowed
    assert "FAIL_CLOSED" in dec_missing.reason

    # NaN / Inf spread
    dec_nan = guard.check_order(valid_order, valid_account, dict(valid_market, spread_pips=float("nan")))
    assert not dec_nan.allowed
    assert "FAIL_CLOSED" in dec_nan.reason

    dec_inf = guard.check_order(valid_order, valid_account, dict(valid_market, spread_pips=float("inf")))
    assert not dec_inf.allowed
    assert "FAIL_CLOSED" in dec_inf.reason


def test_invariant8_edge_cases_tick_timestamps(base_config, valid_order, valid_account, valid_market):
    """Verify stale tick guard handles future ticks, non-positive ticks, ms conversion, and bools."""
    now = 100000.0
    guard = RiskGuard(base_config, clock=lambda: now)

    # Future tick (> 10s into future)
    dec_future = guard.check_order(valid_order, valid_account, dict(valid_market, tick_time=now + 15.0))
    assert not dec_future.allowed
    assert "FAIL_CLOSED" in dec_future.reason

    # Non-positive tick timestamp
    dec_zero = guard.check_order(valid_order, valid_account, dict(valid_market, tick_time=0.0))
    assert not dec_zero.allowed
    assert "FAIL_CLOSED" in dec_zero.reason

    dec_neg_tick = guard.check_order(valid_order, valid_account, dict(valid_market, tick_time=-50.0))
    assert not dec_neg_tick.allowed
    assert "FAIL_CLOSED" in dec_neg_tick.reason

    # Millisecond epoch timestamp normalization
    dec_ms = guard.check_order(valid_order, valid_account, dict(valid_market, tick_time=(now - 1.0) * 1000.0))
    assert dec_ms.allowed

    # Boolean tick_time
    dec_bool_tick = guard.check_order(valid_order, valid_account, dict(valid_market, tick_time=True))
    assert not dec_bool_tick.allowed
    assert "FAIL_CLOSED" in dec_bool_tick.reason


def test_invariant9_fail_closed_contract_pip_and_lot_nans(base_config, valid_order, valid_account, valid_market):
    """Verify fail closed architecture triggers when market contains NaN aux parameters."""
    guard = RiskGuard(base_config)

    for field in ["pip_size", "contract_size", "min_lot", "max_lot", "lot_step"]:
        bad_mkt = dict(valid_market)
        bad_mkt[field] = float("nan")
        dec = guard.check_order(valid_order, valid_account, bad_mkt)
        assert not dec.allowed, f"Should fail closed on NaN {field}"
        assert dec.lot == 0.0
        assert "FAIL_CLOSED" in dec.reason

        # Dict indexing and attribute access must both work
        assert dec["allowed"] is False
        assert dec.allowed is False
        assert dec["lot"] == 0.0
        assert dec.lot == 0.0

