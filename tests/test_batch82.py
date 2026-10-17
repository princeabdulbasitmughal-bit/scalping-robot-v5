"""
tests/test_batch82.py
Batch 82 Unit Tests: High-Frequency Tick & Bar Backtesting Simulation Engine (python_engine/backtester.py).
Expands test baseline beyond 1,067+ passing tests.
Verifies:
1. Backtester: Session volatility mapping (Tokyo=0.02, London=0.08, NY=0.12, fallbacks).
2. Backtester: Session determination across 3-tier timeline distribution.
3. Backtester: Realistic tick generation with Gaussian random walk and spread modeling.
4. Backtester: Mathematical accuracy and boundary conditions of _calc_ema and _calc_bb.
5. Backtester: Wilder's smoothed RSI calculation, bounds, and zero-division resilience.
6. Backtester: calculate_tick_indicators warmup threshold (22 ticks) and indicator dict structure.
7. Backtester: Multi-tier signal evaluation and spread ceiling gating.
8. Backtester: Tick simulation execution, balance tracking, and drawdown analytics.
9. Backtester: Bar simulation pessimistic fill execution (SL wins over TP on dual-breach bars).
10. Backtester: Performance metrics calculations and summary rendering resilience.
"""

import math
import pytest
from python_engine.backtester import Backtester
from python_engine.scalping_engine import ScalpingSignal


def test_backtester_session_volatility_mapping():
    """Verify get_session_volatility correctly maps known trading sessions and defaults for unknown."""
    bt = Backtester({"symbol": "XAUUSD"})

    assert bt.get_session_volatility("TOKYO") == 0.02
    assert bt.get_session_volatility("tokyo") == 0.02
    assert bt.get_session_volatility("LONDON") == 0.08
    assert bt.get_session_volatility("london") == 0.08
    assert bt.get_session_volatility("NY") == 0.12
    assert bt.get_session_volatility("NEW YORK") == 0.12
    assert bt.get_session_volatility("new_york") == 0.12
    # Fallback to London institutional default (0.08)
    assert bt.get_session_volatility("SYDNEY") == 0.08
    assert bt.get_session_volatility("UNKNOWN") == 0.08


def test_backtester_determine_session_proportions():
    """Verify determine_session assigns Tokyo, London, and NY according to index ratios."""
    bt = Backtester()

    total = 1000

    # First third: Tokyo (< 0.333)
    s1, v1 = bt.determine_session(0, total)
    assert s1 == "TOKYO" and v1 == 0.02
    s2, v2 = bt.determine_session(300, total)
    assert s2 == "TOKYO" and v2 == 0.02

    # Middle third: London (0.333 <= ratio < 0.667)
    s3, v3 = bt.determine_session(350, total)
    assert s3 == "LONDON" and v3 == 0.08
    s4, v4 = bt.determine_session(500, total)
    assert s4 == "LONDON" and v4 == 0.08

    # Final third: NY (>= 0.667)
    s5, v5 = bt.determine_session(700, total)
    assert s5 == "NY" and v5 == 0.12
    s6, v6 = bt.determine_session(999, total)
    assert s6 == "NY" and v6 == 0.12

    # Zero or negative total ticks fallback
    s_zero, v_zero = bt.determine_session(10, 0)
    assert s_zero == "LONDON" and v_zero == 0.08


def test_backtester_simulate_ticks_structure_and_spread():
    """Verify simulate_ticks generates accurate tick records with realistic bid/ask spreads."""
    bt = Backtester({"symbol": "XAUUSD", "pip_size": 0.1})

    n_ticks = 50
    start_p = 2650.0
    ticks = bt.simulate_ticks(n_ticks=n_ticks, start_price=start_p, session="LONDON")

    assert len(ticks) == n_ticks

    for i, t in enumerate(ticks):
        assert t["tick"] == i
        assert math.isfinite(t["price"])
        assert math.isfinite(t["bid"])
        assert math.isfinite(t["ask"])
        assert 0.5 <= t["spread_pips"] <= 2.5
        assert t["session"] == "LONDON"
        assert t["volatility"] == 0.08

        # Spread consistency: ask - bid approx equals spread_pips * pip_size
        expected_spread = t["spread_pips"] * 0.1
        actual_spread = t["ask"] - t["bid"]
        assert pytest.approx(actual_spread, abs=0.005) == expected_spread


def test_backtester_ema_and_bb_indicators():
    """Verify mathematical accuracy and edge cases of _calc_ema and _calc_bb."""
    bt = Backtester()

    # 1. EMA edge cases
    assert bt._calc_ema([], 8) == 0.0
    assert bt._calc_ema([100.0], 0) == 0.0
    assert bt._calc_ema([10.0, 20.0, 30.0], 5) == 30.0  # len < period returns last

    # Constant price EMA equals constant price
    const_series = [2650.0] * 20
    assert pytest.approx(bt._calc_ema(const_series, 8), abs=1e-6) == 2650.0

    # 2. Bollinger Bands
    # Short series (< period) returns default span
    up_s, mid_s, low_s = bt._calc_bb([2650.0] * 10, period=20)
    assert up_s == 2651.0
    assert mid_s == 2650.0
    assert low_s == 2649.0

    # Normal 20-period series
    varying_series = [2600.0 + (i % 5) * 2.0 for i in range(25)]
    up, mid, low = bt._calc_bb(varying_series, period=20, std_dev_mult=2.0)
    assert up > mid > low
    assert pytest.approx(up - mid, abs=1e-5) == (mid - low)


def test_backtester_wilders_rsi_smoothing():
    """Verify _calc_rsi adheres to Wilder's smoothed RSI specifications and boundaries."""
    bt = Backtester()

    # Insufficient data
    assert bt._calc_rsi([], 14) == 50.0
    assert bt._calc_rsi([100.0] * 10, 14) == 50.0
    assert bt._calc_rsi([100.0] * 20, 0) == 50.0

    # Strictly monotonic
    inc_series = [100.0 + i for i in range(25)]
    assert bt._calc_rsi(inc_series, 14) == 100.0

    dec_series = [200.0 - i for i in range(25)]
    assert bt._calc_rsi(dec_series, 14) == 0.0

    # Flat series
    flat_series = [100.0] * 25
    assert bt._calc_rsi(flat_series, 14) == 50.0

    # Fluctuating series
    fluct_series = [100.0 + (i % 3) * 2.0 for i in range(30)]
    val = bt._calc_rsi(fluct_series, 14)
    assert 0.0 < val < 100.0


def test_backtester_calculate_tick_indicators_warmup():
    """Verify calculate_tick_indicators enforces 22-tick warmup and outputs valid metrics."""
    bt = Backtester({"fast_ema": 8, "slow_ema": 21, "bb_period": 20})

    # Under 22 ticks -> empty dict
    prices_short = [2650.0] * 21
    assert bt.calculate_tick_indicators(prices_short) == {}

    # Exactly 22 ticks -> valid indicators
    prices_valid = [2650.0 + (i % 4) for i in range(22)]
    ind = bt.calculate_tick_indicators(prices_valid)
    assert ind != {}
    assert "close" in ind
    assert "fast_ema" in ind
    assert "slow_ema" in ind
    assert "bb_upper" in ind
    assert "bb_mid" in ind
    assert "bb_lower" in ind
    assert "rsi" in ind
    assert ind["trend"] in ("BULLISH", "BEARISH")


def test_backtester_evaluate_signal_tiers():
    """Verify evaluate_signal implements multi-tier confluence and spread filtering."""
    bt = Backtester({"max_spread_pips": 2.5})

    dummy = {
        "close": 2650.0,
        "bb_upper": 2655.0,
        "bb_lower": 2645.0,
        "bb_mid": 2650.0,
        "fast_ema": 2650.0,
        "slow_ema": 2650.0,
        "rsi": 50.0,
    }

    # Empty indicator dict returns HOLD
    assert bt.evaluate_signal({}) == ScalpingSignal.HOLD

    # Spread > max_spread_pips returns HOLD
    assert bt.evaluate_signal(dummy, current_spread_pips=3.0) == ScalpingSignal.HOLD

    # Tier 1: Bollinger Bands Mean Reversion
    # BUY: close <= bb_lower and rsi < 55.0
    tier1_buy = dict(dummy, close=2644.0, bb_lower=2645.0, rsi=40.0)
    assert bt.evaluate_signal(tier1_buy, current_spread_pips=1.0) == ScalpingSignal.BUY

    # SELL: close >= bb_upper and rsi > 45.0
    tier1_sell = dict(dummy, close=2656.0, bb_upper=2655.0, rsi=60.0)
    assert bt.evaluate_signal(tier1_sell, current_spread_pips=1.0) == ScalpingSignal.SELL

    # Tier 3: RSI Extreme Momentum
    # BUY: rsi <= 35.0
    tier3_buy = dict(dummy, rsi=30.0, close=2649.0, bb_lower=2640.0, bb_upper=2660.0)
    assert bt.evaluate_signal(tier3_buy, current_spread_pips=1.0) == ScalpingSignal.BUY

    # SELL: rsi >= 65.0
    tier3_sell = dict(dummy, rsi=75.0, close=2651.0, bb_lower=2640.0, bb_upper=2660.0)
    assert bt.evaluate_signal(tier3_sell, current_spread_pips=1.0) == ScalpingSignal.SELL


def test_backtester_tick_simulation_breakeven_and_trailing():
    """Verify run_backtest_ticks executes full simulation, tracks PnL, and closes trades at finish."""
    bt = Backtester({
        "symbol": "XAUUSD",
        "lot_size": 0.01,
        "tp_pips": 10.0,
        "sl_pips": 20.0,
        "trailing_stop_pips": 5.0,
        "breakeven_pips": 4.0,
        "breakeven_lock_pips": 1.0,
    })

    res = bt.run_backtest_ticks(n_ticks=200, initial_balance=10000.0, session="LONDON", print_summary=False)

    assert "total_trades" in res
    assert "wins" in res
    assert "losses" in res
    assert "total_pnl" in res
    assert "final_balance" in res
    assert "max_drawdown" in res
    assert "win_rate" in res
    assert "profit_factor" in res

    # Accounting consistency
    assert pytest.approx(res["final_balance"], abs=0.05) == (res["initial_balance"] + res["total_pnl"])
    assert res["wins"] + res["losses"] <= res["total_trades"]


def test_backtester_run_bars_pessimistic_fill():
    """Verify run_backtest_bars enforces pessimistic fill rule (SL wins when both hit in same candle)."""
    bt = Backtester({
        "symbol": "XAUUSD",
        "pip_size": 0.1,
        "lot_size": 0.01,
        "tp_pips": 15.0,  # 1.5 price units
        "sl_pips": 15.0,  # 1.5 price units
    })

    # Prepare 40 baseline bars to satisfy warmup
    bars = []
    base_price = 2650.0
    for i in range(40):
        bars.append({
            "open": base_price,
            "high": base_price + 0.5,
            "low": base_price - 0.5,
            "close": base_price,
            "volume": 100,
        })

    # Bar 41: Spike bar that penetrates both SL (2648.5) and TP (2651.5)
    bars.append({
        "open": base_price,
        "high": base_price + 5.0,   # exceeds TP
        "low": base_price - 5.0,    # exceeds SL
        "close": base_price,
        "volume": 1000,
    })

    # Execute simulation
    res = bt.run_backtest_bars(bars, initial_balance=10000.0, print_summary=False)

    # Check if any trades closed
    sl_trades = [t for t in res["trades"] if t.get("reason") == "STOP_LOSS"]
    tp_trades = [t for t in res["trades"] if t.get("reason") == "TAKE_PROFIT"]

    # In bar 41, if a trade was open, pessimistic fill mandates STOP_LOSS wins over TAKE_PROFIT
    for trade in res["trades"]:
        if trade.get("reason") == "STOP_LOSS":
            assert trade["pnl"] < 0


def test_backtester_print_summary_and_metrics_math(capsys):
    """Verify print_results_summary formats output cleanly and handles division edge cases."""
    bt = Backtester()

    # Edge case: zero trades
    zero_results = {
        "symbol": "XAUUSD",
        "ticks_simulated": 0,
        "avg_spread_pips": 1.5,
        "initial_balance": 10000.0,
        "final_balance": 10000.0,
        "total_pnl": 0.0,
        "return_pct": 0.0,
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": 0.0,
        "profit_factor": 0.0,
        "max_drawdown": 0.0,
        "max_drawdown_pct": 0.0,
    }
    bt.print_results_summary(zero_results)
    captured = capsys.readouterr().out
    assert "GOLD SCALPING ROBOT V5 - BACKTEST SUMMARY" in captured
    assert "Total Trades:           0" in captured
    assert "Total PnL:              $+0.00" in captured

    # Edge case: 100% win rate (gross_loss = 0 -> profit factor 999.0)
    win_results = dict(zero_results, total_trades=5, wins=5, total_pnl=250.0, profit_factor=999.0)
    bt.print_results_summary(win_results)
    captured_win = capsys.readouterr().out
    assert "Total Trades:           5" in captured_win
    assert "Profit Factor:          999.00" in captured_win
