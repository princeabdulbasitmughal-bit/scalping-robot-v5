import os
import json
import tempfile
import math
from pathlib import Path
from unittest.mock import MagicMock

from python_engine.backtester import Backtester
import python_engine.backtester as backtester
from python_engine.scalping_engine import ScalpingSignal
import run_backtest
from run_backtest import simulate_price, bb_signal


def test_backtester_session_volatilities():
    bt = Backtester()
    assert bt.get_session_volatility("TOKYO") == 0.02
    assert bt.get_session_volatility("tokyo") == 0.02
    assert bt.get_session_volatility("LONDON") == 0.08
    assert bt.get_session_volatility("NY") == 0.12
    assert bt.get_session_volatility("NEW_YORK") == 0.12
    # Unknown defaults to 0.08
    assert bt.get_session_volatility("SYDNEY") == 0.08


def test_backtester_determine_session():
    bt = Backtester()
    sess, vol = bt.determine_session(10, 100)  # ratio = 0.1 -> TOKYO
    assert sess == "TOKYO"
    assert vol == 0.02

    sess, vol = bt.determine_session(50, 100)  # ratio = 0.5 -> LONDON
    assert sess == "LONDON"
    assert vol == 0.08

    sess, vol = bt.determine_session(85, 100)  # ratio = 0.85 -> NY
    assert sess == "NY"
    assert vol == 0.12

    sess, vol = bt.determine_session(0, 0)
    assert sess == "LONDON"
    assert vol == 0.08


def test_backtester_simulate_ticks():
    bt = Backtester({"pip_size": 0.1})
    ticks = bt.simulate_ticks(n_ticks=50, start_price=2650.0, session="LONDON")
    assert len(ticks) == 50
    first = ticks[0]
    assert first["tick"] == 0
    assert first["ask"] > first["bid"]
    assert first["spread_pips"] > 0
    assert first["session"] == "LONDON"
    assert first["volatility"] == 0.08


def test_backtester_tick_indicators_and_signal_evaluation():
    bt = Backtester({"fast_ema": 5, "slow_ema": 10, "bb_period": 10, "max_spread_pips": 3.0})
    prices = [2650.0 + (i * 0.2) for i in range(25)]

    ind = bt.calculate_tick_indicators(prices)
    assert ind["close"] == prices[-1]
    assert ind["bb_upper"] > ind["bb_lower"]
    assert ind["trend"] == "BULLISH"

    # Spread protection: excessive spread forces HOLD
    sig_spread_blocked = bt.evaluate_signal(ind, current_spread_pips=5.0)
    assert sig_spread_blocked == ScalpingSignal.HOLD

    # Valid spread evaluates to standard signal
    sig_valid = bt.evaluate_signal(ind, current_spread_pips=1.0)
    assert sig_valid in (ScalpingSignal.BUY, ScalpingSignal.SELL, ScalpingSignal.HOLD)


def test_backtester_run_backtest_ticks():
    bt = Backtester({"max_orders": 1, "tp_pips": 10.0, "sl_pips": 15.0})
    res = bt.run_backtest_ticks(n_ticks=100, initial_balance=10000.0, print_summary=False)
    assert "total_trades" in res
    assert "wins" in res
    assert "losses" in res
    assert "total_pnl" in res
    assert "max_drawdown" in res
    assert "win_rate" in res
    assert "final_balance" in res
    assert res["initial_balance"] == 10000.0


def test_backtester_unified_risk_aliases():
    bt = Backtester()
    assert bt.is_entry_blocked() is False
    assert bt.is_blocked() is False
    assert backtester.is_entry_blocked() is False
    assert backtester.is_blocked() is False


def test_run_backtest_simulate_price():
    prices = simulate_price(n_ticks=100, start_price=2600.0)
    assert len(prices) == 100
    assert prices[0] == 2600.0
    assert all(math.isfinite(p) and p >= 100.0 for p in prices)

    # Boolean guards
    prices_bool = simulate_price(n_ticks=True, start_price=False)
    assert len(prices_bool) == 2000
    assert prices_bool[0] == 2400.0


def test_run_backtest_bb_signal():
    prices = [100.0] * 30
    assert bb_signal(prices, 25, period=20) == "HOLD"

    # Window with realistic variance (mean ~ 101.0, std ~ 1.0, lower ~ 99.0, upper ~ 103.0)
    base_window = [100.0 if j % 2 == 0 else 102.0 for j in range(20)]
    prices_dip = base_window + [80.0]
    assert bb_signal(prices_dip, 20, period=20) == "BUY"

    prices_spike = base_window + [120.0]
    assert bb_signal(prices_spike, 20, period=20) == "SELL"

    # Edge cases
    assert bb_signal(prices, 5, period=20) == "HOLD"
    assert bb_signal(prices, 50, period=20) == "HOLD"
    assert bb_signal([], 0, period=20) == "HOLD"



def test_run_backtest_execution_and_file_saving():
    with tempfile.TemporaryDirectory() as tmpdir:
        res_file = os.path.join(tmpdir, "backtest_results.json")
        res = run_backtest.run_backtest(
            n_ticks=60,
            sl_pips=20.0,
            tp_pips=30.0,
            lot=0.01,
            start_balance=5000.0,
            save_results=True,
            quiet=True,
            results_file=res_file,
        )

        assert os.path.exists(res_file)
        assert res["n_ticks"] == 60
        assert "win_rate_pct" in res
        assert "total_pnl" in res
        assert "max_drawdown_pct" in res
        assert "profit_factor" in res

        with open(res_file, "r", encoding="utf-8") as f:
            disk_data = json.load(f)
        assert disk_data["n_ticks"] == 60


def test_run_backtest_risk_aliases_and_guards():
    assert run_backtest.is_entry_blocked() is False
    assert run_backtest.is_blocked() is False

    # Boolean inputs to run_backtest should not crash
    res = run_backtest.run_backtest(n_ticks=True, sl_pips=False, tp_pips=True, save_results=False, quiet=True)
    assert res is not None
    assert "total_trades" in res
