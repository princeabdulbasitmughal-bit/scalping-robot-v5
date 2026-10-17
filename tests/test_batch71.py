"""
tests/test_batch71.py
Batch 71 Unit Tests: Institutional Backtester & Tick Walk (backtester.py),
Process Breakaway Flags & Supervisors (escape_launch.py, bootstrap_launch.py),
and Performance Monitor Evaluation Reporting (performance_monitor.py).
"""

import math
import sys
import json
import pytest
from pathlib import Path

from python_engine.backtester import Backtester
from python_engine.scalping_engine import ScalpingSignal
from escape_launch import (
    get_breakaway_flags,
    get_fallback_flags,
    get_watchdog_command,
    CREATE_BREAKAWAY_FROM_JOB,
    DETACHED_PROCESS,
)
from bootstrap_launch import get_launch_flags, get_supervisor_command
from performance_monitor import evaluate_and_report


def test_backtester_session_volatility_mapping():
    """Verify Backtester maps trading sessions to accurate institutional volatilities."""
    bt = Backtester()
    assert bt.get_session_volatility("Tokyo") == 0.02
    assert bt.get_session_volatility("London") == 0.08
    assert bt.get_session_volatility("NY") == 0.12
    assert bt.get_session_volatility("New York") == 0.12
    assert bt.get_session_volatility("UNKNOWN_SESSION") == 0.08  # Default


def test_backtester_determine_session_proportions():
    """Verify determine_session cleanly partitions the tick timeline."""
    bt = Backtester()
    total = 300

    # First third -> Tokyo
    s1, v1 = bt.determine_session(10, total)
    assert s1 == "TOKYO"
    assert v1 == 0.02

    # Middle third -> London
    s2, v2 = bt.determine_session(150, total)
    assert s2 == "LONDON"
    assert v2 == 0.08

    # Final third -> NY
    s3, v3 = bt.determine_session(280, total)
    assert s3 == "NY"
    assert v3 == 0.12


def test_backtester_simulate_ticks_structure():
    """Verify simulate_ticks outputs high-precision random-walk tick objects."""
    bt = Backtester({"pip_size": 0.1})
    ticks = bt.simulate_ticks(n_ticks=50, start_price=2650.0, session="LONDON")

    assert len(ticks) == 50
    assert ticks[0]["tick"] == 0
    assert all("price" in t and "bid" in t and "ask" in t for t in ticks)
    assert all(t["ask"] >= t["bid"] for t in ticks)
    assert all(0.5 <= t["spread_pips"] <= 2.5 for t in ticks)
    assert all(t["session"] == "LONDON" for t in ticks)


def test_backtester_tick_indicators_calculation():
    """Verify calculate_tick_indicators computes Bollinger Bands, EMAs, and RSI."""
    bt = Backtester({
        "bb_period": 10,
        "fast_ema": 5,
        "slow_ema": 10,
        "rsi_period": 10,
    })

    prices = [2650.0 + i * 0.3 for i in range(30)]
    ind = bt.calculate_tick_indicators(prices)

    assert "close" in ind
    assert "fast_ema" in ind
    assert "slow_ema" in ind
    assert "bb_upper" in ind
    assert "bb_lower" in ind
    assert "rsi" in ind
    assert ind["bb_upper"] > ind["bb_mid"] > ind["bb_lower"]
    assert ind["trend"] == "BULLISH"


def test_backtester_evaluate_signal_spread_guard_and_tiers():
    """Verify evaluate_signal enforces spread protection and BB mean-reversion."""
    bt = Backtester({"max_spread_pips": 3.0})

    ind = {
        "close": 2640.0,
        "bb_lower": 2642.0,
        "bb_upper": 2660.0,
        "bb_mid": 2651.0,
        "fast_ema": 2650.0,
        "slow_ema": 2652.0,
        "rsi": 30.0,
    }

    # Signal allowed when spread is within bounds
    sig = bt.evaluate_signal(ind, current_spread_pips=1.5)
    assert sig == ScalpingSignal.BUY

    # Signal blocked to HOLD when spread exceeds threshold
    sig_blocked = bt.evaluate_signal(ind, current_spread_pips=3.8)
    assert sig_blocked == ScalpingSignal.HOLD


def test_backtester_run_backtest_ticks_execution():
    """Verify run_backtest_ticks executes full simulation and tracks performance metrics."""
    bt = Backtester()
    results = bt.run_backtest_ticks(
        n_ticks=80,
        initial_balance=10000.0,
        start_price=2650.0,
        print_summary=False,
    )

    assert isinstance(results, dict)
    assert "total_trades" in results
    assert "wins" in results
    assert "losses" in results
    assert "total_pnl" in results
    assert "final_balance" in results
    assert "max_drawdown" in results
    assert "win_rate" in results
    assert results["initial_balance"] == 10000.0


def test_escape_launch_breakaway_and_fallback_flags():
    """Verify escape_launch provides correct process flags with and without job breakaway."""
    breakaway = get_breakaway_flags()
    fallback = get_fallback_flags()

    # Breakaway flag has CREATE_BREAKAWAY_FROM_JOB and DETACHED_PROCESS
    assert bool(breakaway & CREATE_BREAKAWAY_FROM_JOB) is True
    assert bool(breakaway & DETACHED_PROCESS) is True

    # Fallback flag omits CREATE_BREAKAWAY_FROM_JOB
    assert bool(fallback & CREATE_BREAKAWAY_FROM_JOB) is False
    assert bool(fallback & DETACHED_PROCESS) is True


def test_escape_launch_watchdog_command_structure():
    """Verify get_watchdog_command points to current python interpreter and watchdog_runner."""
    cmd = get_watchdog_command()
    assert len(cmd) == 2
    assert cmd[0] == sys.executable
    assert "watchdog_runner.py" in cmd[1]


def test_bootstrap_launch_supervisor_command_and_flags():
    """Verify bootstrap_launch defines valid flags and points to supervisor.py."""
    flags = get_launch_flags()
    assert bool(flags & DETACHED_PROCESS) is True

    cmd = get_supervisor_command()
    assert len(cmd) == 2
    assert "supervisor.py" in cmd[1]


def test_performance_monitor_file_evaluation_mock(tmp_path):
    """Verify evaluate_and_report parses live_status.json and generates performance_report.txt."""
    status_file = tmp_path / "live_status.json"
    report_file = tmp_path / "performance_report.txt"

    status_data = {
        "status": "RUNNING",
        "symbol": "XAUUSD",
        "current_price": 2650.50,
        "balance": 10500.00,
        "equity": 10520.00,
        "daily_pnl": 500.00,
        "total_trades": 25,
        "win_rate": 88.0,
        "open_positions": [],
        "updated_at": "2026-10-17T12:00:00Z",
    }
    status_file.write_text(json.dumps(status_data), encoding="utf-8")

    success = evaluate_and_report(status_file=status_file, report_file=report_file)
    assert success is True
    assert report_file.exists()

    report_content = report_file.read_text(encoding="utf-8")
    assert "PERFORMANCE REPORT" in report_content
    assert "XAUUSD" in report_content
    assert "10,500.00" in report_content or "10500.00" in report_content
    assert "88.00%" in report_content or "88.0%" in report_content or "88%" in report_content
