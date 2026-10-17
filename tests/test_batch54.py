"""
Test Suite: Batch 54 — Backtest Engine, RiskGuard Invariants 1, 3, 6, 7, 8 & Supervisor Circuit Breaker
========================================================================================================
Hermetic unit test suite verifying:
  1. Backtest Engine: simulate_price generation, boundary bounds, and session drift
  2. Backtest Engine: bb_signal Bollinger Band signal generation (BUY, SELL, HOLD)
  3. Backtest Engine: run_backtest end-to-end execution, metrics calculation, and trade accounting
  4. RiskGuard Invariant 1: Mandatory Stop Loss enforcement, side alignment, and min/max distance checks
  5. RiskGuard Invariant 6: Maximum concurrent positions ceiling & daily trade count limits
  6. RiskGuard Invariant 7: Live market spread gatekeeper and negative spread fail-closed handling
  7. RiskGuard Invariant 8: Stale tick timestamp detection and future timestamp rejection
  8. RiskGuard Invariant 3: Maximum dollar risk-per-trade position sizing downscale
  9. Scalping Engine: Signal generation confluence and high-spread signal suppression
 10. Supervisor Engine: Exponential backoff progression and crash circuit breaker protection
"""

import time
import math
import tempfile
from pathlib import Path
import pytest

from run_backtest import simulate_price, bb_signal, run_backtest
from python_engine.risk_guard import RiskGuard, Decision
from python_engine.scalping_engine import ScalpingRobotV5, ScalpingSignal
from supervisor import calculate_backoff, check_circuit_breaker


# ── Test 1: Backtest Engine Price Simulation ──────────────────────────────────
def test_backtest_simulate_price():
    """Verify simulate_price generates positive finite prices across trading sessions."""
    prices = simulate_price(n_ticks=100, start_price=2400.0)
    assert len(prices) == 100
    assert prices[0] == 2400.0
    assert all(math.isfinite(p) and p > 0 for p in prices)

    # Edge cases: non-finite or negative inputs fall back safely
    prices_safe = simulate_price(n_ticks=0, start_price=-500.0)
    assert len(prices_safe) >= 1
    assert prices_safe[0] == 2400.0


# ── Test 2: Backtest Engine Bollinger Band Signal ─────────────────────────────
def test_backtest_bb_signal():
    """Verify bb_signal triggers BUY at lower band, SELL at upper band, and HOLD in middle."""
    period = 20
    # Mean of 2400.0 with std around 2.0
    prices = [2400.0 + ((-1) ** i) * 2.0 for i in range(period)]

    # Middle price -> HOLD
    prices_hold = prices + [2400.0]
    assert bb_signal(prices_hold, i=period, period=period) == "HOLD"

    # Deep drop below lower band -> BUY
    prices_buy = prices + [2390.0]
    assert bb_signal(prices_buy, i=period, period=period) == "BUY"

    # Spike above upper band -> SELL
    prices_sell = prices + [2410.0]
    assert bb_signal(prices_sell, i=period, period=period) == "SELL"


# ── Test 3: Backtest Engine End-to-End Execution ──────────────────────────────
def test_backtest_run_execution():
    """Verify run_backtest executes tick simulation without disk side-effects."""
    results = run_backtest(
        n_ticks=300,
        sl_pips=20.0,
        tp_pips=30.0,
        lot=0.01,
        start_balance=10000.0,
        save_results=False,
        quiet=True,
    )
    assert isinstance(results, dict)
    assert "total_trades" in results
    assert "win_rate_pct" in results
    assert "final_balance" in results
    assert math.isfinite(results["final_balance"])


# ── Test 4: RiskGuard Invariant 1 - Mandatory Stop Loss ────────────────────────
def test_risk_guard_mandatory_sl():
    """Verify Invariant 1 enforces mandatory SL, directional alignment, and distance limits."""
    with tempfile.TemporaryDirectory() as tmpdir:
        guard = RiskGuard(
            config={"min_balance_usd": 1000.0, "min_sl_pips": 5.0, "max_sl_pips": 100.0},
            state_path=Path(tmpdir) / "state.json",
        )
        account = {"balance": 10000.0, "equity": 10000.0, "open_positions": 0}
        market = {"spread_pips": 1.5, "tick_time": time.time(), "pip_size": 0.1, "min_lot": 0.01}

        # 1. Missing SL
        dec_no_sl = guard.check_order(
            order={"type": "BUY", "price": 2400.0, "lots": 0.01},
            account=account,
            market=market,
        )
        assert dec_no_sl.allowed is False
        assert "MANDATORY_SL" in dec_no_sl.reason

        # 2. BUY with SL above price (wrong side)
        dec_wrong_buy = guard.check_order(
            order={"type": "BUY", "price": 2400.0, "sl": 2405.0, "lots": 0.01},
            account=account,
            market=market,
        )
        assert dec_wrong_buy.allowed is False
        assert "SL_WRONG_SIDE" in dec_wrong_buy.reason

        # 3. SELL with SL below price (wrong side)
        dec_wrong_sell = guard.check_order(
            order={"type": "SELL", "price": 2400.0, "sl": 2395.0, "lots": 0.01},
            account=account,
            market=market,
        )
        assert dec_wrong_sell.allowed is False
        assert "SL_WRONG_SIDE" in dec_wrong_sell.reason

        # 4. SL distance too small (0.2 points = 2 pips < 5 pips)
        dec_small = guard.check_order(
            order={"type": "BUY", "price": 2400.0, "sl": 2399.8, "lots": 0.01},
            account=account,
            market=market,
        )
        assert dec_small.allowed is False
        assert "SL_DISTANCE_TOO_SMALL" in dec_small.reason

        # 5. SL distance too large (15 points = 150 pips > 100 pips)
        dec_large = guard.check_order(
            order={"type": "BUY", "price": 2400.0, "sl": 2385.0, "lots": 0.01},
            account=account,
            market=market,
        )
        assert dec_large.allowed is False
        assert "SL_DISTANCE_TOO_LARGE" in dec_large.reason


# ── Test 5: RiskGuard Invariant 6 - Max Positions & Daily Trades ───────────────
def test_risk_guard_position_and_trade_limits():
    """Verify Invariant 6 blocks orders when open positions or daily trade limits are hit."""
    with tempfile.TemporaryDirectory() as tmpdir:
        guard = RiskGuard(
            config={"min_balance_usd": 1000.0, "max_positions_per_session": 2, "max_trades_per_day": 5},
            state_path=Path(tmpdir) / "state.json",
        )
        market = {"spread_pips": 1.5, "tick_time": time.time(), "pip_size": 0.1, "min_lot": 0.01}
        order = {"type": "BUY", "price": 2400.0, "sl": 2395.0, "lots": 0.01}

        # Open positions equal to limit (2 positions >= max 2)
        acct_full_pos = {"balance": 10000.0, "equity": 10000.0, "open_positions": 2}
        dec_pos = guard.check_order(order=order, account=acct_full_pos, market=market)
        assert dec_pos.allowed is False
        assert "MAX_POSITIONS_REACHED" in dec_pos.reason

        # Daily trades count limit
        guard.state["trade_count_today"] = 5
        acct_ok = {"balance": 10000.0, "equity": 10000.0, "open_positions": 0}
        dec_daily = guard.check_order(order=order, account=acct_ok, market=market)
        assert dec_daily.allowed is False
        assert "MAX_TRADES_PER_DAY_REACHED" in dec_daily.reason


# ── Test 6: RiskGuard Invariant 7 - Spread Gatekeeper ──────────────────────────
def test_risk_guard_spread_filter():
    """Verify Invariant 7 blocks orders when spread is excessive or negative."""
    with tempfile.TemporaryDirectory() as tmpdir:
        guard = RiskGuard(
            config={"min_balance_usd": 1000.0, "spread_filter_pips": 2.5},
            state_path=Path(tmpdir) / "state.json",
        )
        account = {"balance": 10000.0, "equity": 10000.0, "open_positions": 0}
        order = {"type": "BUY", "price": 2400.0, "sl": 2395.0, "lots": 0.01}

        # Spread exceeds limit (3.5 pips > 2.5 pips)
        market_wide = {"spread_pips": 3.5, "tick_time": time.time(), "pip_size": 0.1, "min_lot": 0.01}
        dec_wide = guard.check_order(order=order, account=account, market=market_wide)
        assert dec_wide.allowed is False
        assert "SPREAD_EXCEEDED" in dec_wide.reason

        # Negative spread is invalid
        market_neg = {"spread_pips": -0.5, "tick_time": time.time(), "pip_size": 0.1, "min_lot": 0.01}
        dec_neg = guard.check_order(order=order, account=account, market=market_neg)
        assert dec_neg.allowed is False
        assert "FAIL_CLOSED" in dec_neg.reason


# ── Test 7: RiskGuard Invariant 8 - Stale Tick Guard ───────────────────────────
def test_risk_guard_stale_ticks():
    """Verify Invariant 8 blocks execution on stale or future-dated tick data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        guard = RiskGuard(
            config={"min_balance_usd": 1000.0, "max_tick_age_sec": 5.0},
            state_path=Path(tmpdir) / "state.json",
        )
        account = {"balance": 10000.0, "equity": 10000.0, "open_positions": 0}
        order = {"type": "BUY", "price": 2400.0, "sl": 2395.0, "lots": 0.01}

        # Stale tick (15s ago > 5s max age)
        market_stale = {"spread_pips": 1.5, "tick_time": time.time() - 15.0, "pip_size": 0.1, "min_lot": 0.01}
        dec_stale = guard.check_order(order=order, account=account, market=market_stale)
        assert dec_stale.allowed is False
        assert "STALE_TICK" in dec_stale.reason

        # Tick from the future (> 10s ahead)
        market_future = {"spread_pips": 1.5, "tick_time": time.time() + 30.0, "pip_size": 0.1, "min_lot": 0.01}
        dec_future = guard.check_order(order=order, account=account, market=market_future)
        assert dec_future.allowed is False
        assert "FAIL_CLOSED" in dec_future.reason


# ── Test 8: RiskGuard Invariant 3 - Dollar Risk Per Trade Cap ──────────────────
def test_risk_guard_dollar_risk_cap():
    """Verify Invariant 3 automatically reduces lot size if dollar risk exceeds limit."""
    with tempfile.TemporaryDirectory() as tmpdir:
        guard = RiskGuard(
            config={
                "min_balance_usd": 1000.0,
                "risk_per_trade_pct": 1.0,  # 1% of $10,000 = $100 max dollar risk
                "contract_size": 100.0,
                "max_lot_size": 1.0,
            },
            state_path=Path(tmpdir) / "state.json",
        )
        account = {"balance": 10000.0, "equity": 10000.0, "open_positions": 0}
        market = {"spread_pips": 1.5, "tick_time": time.time(), "pip_size": 0.1, "min_lot": 0.01, "lot_step": 0.01}

        # SL distance = 2400.0 - 2380.0 = 20.0 points.
        # Requested lots = 0.20 -> Dollar risk = 0.20 * 20.0 * 100 = $400 > $100 limit.
        # Required safe lot: $100 / (20.0 * 100) = 0.05 lots.
        order_risky = {"type": "BUY", "price": 2400.0, "sl": 2380.0, "lots": 0.20}
        dec = guard.check_order(order=order_risky, account=account, market=market)
        assert dec.allowed is True
        assert dec.lot == 0.05  # downscaled automatically


# ── Test 9: Scalping Engine Spread Suppression ─────────────────────────────────
def test_scalping_engine_spread_suppression():
    """Verify ScalpingRobotV5 suppresses signal to HOLD when spread is excessive."""
    robot = ScalpingRobotV5(config={"max_spread_pips": 2.5})

    # Prepare standard bullish indicator set
    indicators = {
        "bb_upper": 2410.0,
        "bb_middle": 2405.0,
        "bb_lower": 2400.0,
        "bb_width": 10.0,
        "rsi": 28.0,  # oversold
        "atr": 2.5,
        "ema_fast": 2406.0,
        "ema_slow": 2404.0,
        "spread_pips": 3.8,  # Excessive spread (> 2.5 pips)
    }

    sig = robot.evaluate_entry(indicators, current_spread_pips=3.8)
    assert sig == ScalpingSignal.HOLD
    assert "spread" in robot.shield_status["reason"].lower()


# ── Test 10: Supervisor Backoff Progression & Circuit Breaker ──────────────────
def test_supervisor_backoff_and_circuit_breaker():
    """Verify supervisor exponential backoff progression and circuit breaker threshold."""
    # Backoff progression: min(120, 8 * (2 ** (n - 1)))
    assert calculate_backoff(0) == 0
    assert calculate_backoff(1) == 8
    assert calculate_backoff(2) == 16
    assert calculate_backoff(3) == 32
    assert calculate_backoff(4) == 64
    assert calculate_backoff(5) == 120
    assert calculate_backoff(10) == 120

    # Circuit breaker trips at 20 consecutive failures
    assert check_circuit_breaker(10) is False
    assert check_circuit_breaker(19) is False
    assert check_circuit_breaker(20) is True
    assert check_circuit_breaker(25) is True
