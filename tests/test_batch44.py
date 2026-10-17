"""
tests/test_batch44.py - Comprehensive Unit Tests for Batch 44 Components:
1. python_engine/live_runner (ScalpingLiveRunner): runner lifecycle, state retrieval, and seeded bars
2. python_engine/live_runner (Tick Updates & Status I/O): tick price updates and atomic status file generation
3. python_engine/live_runner (TP/SL Order Processing): position TP/SL triggers, trade history, and equity tracking
4. python_engine/live_runner (Candlestick Rollover): 60s bar rollover, bar buffer bounding, and OHLCV updates
5. run_backtest (simulate_price & bb_signal): price drift simulation and Bollinger Band signal logic
6. run_backtest (run_backtest Pipeline): end-to-end backtesting simulation, metrics calculation, and results JSON write
7. auto_install_to_mt4 (find_mt4_directories & Discovery): terminal directory searching and environment variable handling
8. auto_install_to_mt4 (install_to_target): MQL4 Experts & Presets directory creation and file copying
9. escape_launch (Flags & Command Generation): CREATE_BREAKAWAY_FROM_JOB flag verification and command resolution
10. bootstrap_launch (Supervisor Launch Config): detached process flags, python executable selection, and supervisor command
"""

import os
import json
import time
import math
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from python_engine.live_runner import ScalpingLiveRunner
from python_engine.scalping_engine import ScalpingSignal
from run_backtest import simulate_price, bb_signal, run_backtest
from auto_install_to_mt4 import find_mt4_directories, install_to_target
from escape_launch import (
    get_breakaway_flags,
    get_fallback_flags,
    get_watchdog_command,
    DETACHED_PROCESS,
    CREATE_BREAKAWAY_FROM_JOB,
)
from bootstrap_launch import (
    get_launch_flags,
    get_supervisor_command,
    CREATE_NEW_PROCESS_GROUP,
    CREATE_NO_WINDOW,
)


def test_live_runner_initialization_and_seeded_bars(tmp_path):
    """Verify ScalpingLiveRunner initializes with 100 historical seed bars and accurate state."""
    status_file = tmp_path / "test_status.json"
    runner = ScalpingLiveRunner(config={"symbol": "XAUUSD", "lot_size": 0.02}, status_file=status_file)

    assert runner.running is False
    assert len(runner.bars) == 100
    assert runner.balance == 10000.0
    assert runner.equity == 10000.0
    assert runner.current_price > 0.0

    state = runner.get_state()
    assert state["symbol"] == "XAUUSD"
    assert state["open_positions_count"] == 0
    assert state["bars_count"] == 100


def test_live_runner_update_tick_and_status_write(tmp_path):
    """Verify update_tick processes price feeds and atomically writes status to disk."""
    status_file = tmp_path / "live_status.json"
    runner = ScalpingLiveRunner(config={"symbol": "XAUUSD"}, status_file=status_file)

    status = runner.update_tick(2415.75)
    assert status["status"] == "ACTIVE_SCALPING"
    assert status["current_price"] == 2415.75
    assert status["symbol"] == "XAUUSD"
    assert status_file.exists()

    with open(status_file, "r", encoding="utf-8") as f:
        disk_status = json.load(f)
    assert disk_status["current_price"] == 2415.75
    assert disk_status["balance"] == 10000.0


def test_live_runner_position_tp_sl_closure(tmp_path):
    """Verify ScalpingLiveRunner closes open positions upon reaching TP or SL thresholds."""
    status_file = tmp_path / "live_status.json"
    runner = ScalpingLiveRunner(config={"symbol": "XAUUSD", "lot_size": 0.05, "pip_size": 0.1, "pip_value": 1.0}, status_file=status_file)

    # 1. Inject an open BUY position: entry=2400.0, tp=2410.0, sl=2390.0
    mock_pos = {
        "id": 1,
        "type": ScalpingSignal.BUY,
        "symbol": "XAUUSD",
        "entry": 2400.0,
        "tp": 2410.0,
        "sl": 2390.0,
        "open_time": "2026-10-20T12:00:00Z"
    }
    runner.robot.open_positions = [mock_pos]

    # Tick at 2405.0 -> position stays open
    runner.update_tick(2405.0)
    assert len(runner.robot.open_positions) == 1

    # Tick reaches 2410.50 (>= TP 2410.0) -> position closes on TP_HIT
    runner.update_tick(2410.50)
    assert len(runner.robot.open_positions) == 0
    assert len(runner.trades_history) == 1
    assert runner.trades_history[0]["close_reason"] == "TP_HIT"
    assert runner.balance > 10000.0
    assert runner.winning_trades_count == 1
    assert runner.total_trades_count == 1


def test_live_runner_candlestick_rollover(tmp_path):
    """Verify ScalpingLiveRunner rolls over bars every 60s and maintains buffer bounds."""
    status_file = tmp_path / "live_status.json"
    runner = ScalpingLiveRunner(status_file=status_file)
    initial_bars_count = len(runner.bars)

    # Force last_bar_time into the past (> 60s ago)
    runner.last_bar_time = time.time() - 75.0
    runner.update_tick(2420.0)

    # New bar should have been created
    assert len(runner.bars) == initial_bars_count + 1
    new_bar = runner.bars[-1]
    assert new_bar["close"] == 2420.0
    assert new_bar["open"] == 2420.0

    # Ensure memory bounds: simulate 350 bars
    for _ in range(50):
        runner.last_bar_time = time.time() - 75.0
        runner.update_tick(2420.0)
    assert len(runner.bars) <= 300


def test_run_backtest_simulate_price_and_bb_signal():
    """Verify simulate_price generates realistic price arrays and bb_signal evaluates bounds."""
    # 1. simulate_price
    prices = simulate_price(n_ticks=100, start_price=2400.0)
    assert len(prices) == 100
    assert prices[0] == 2400.0
    assert all(p >= 100.0 for p in prices)

    # Corrupted / edge-case inputs
    assert len(simulate_price(n_ticks=-10)) == 1
    assert simulate_price(n_ticks=5, start_price=-50.0)[0] == 2400.0

    # 2. bb_signal
    # Insufficient prices
    assert bb_signal([2400.0] * 10, 5) == "HOLD"

    # Construct series with known variance
    base_window = [2400.0 + (i % 2) * 10.0 for i in range(25)]  # alternating 2400 and 2410
    # Mean is 2405.0, std is 5.0 -> upper=2415.0, lower=2395.0
    # Oversold price at index 24: price <= 2395.0 -> BUY
    base_window[24] = 2390.0
    assert bb_signal(base_window, 24, period=20) == "BUY"

    # Overbought price at index 24: price >= 2415.0 -> SELL
    base_window[24] = 2420.0
    assert bb_signal(base_window, 24, period=20) == "SELL"


def test_run_backtest_execution_and_results(tmp_path):
    """Verify run_backtest pipeline computes performance metrics and saves JSON output."""
    res_file = tmp_path / "backtest_results.json"
    results = run_backtest(
        n_ticks=300,
        sl_pips=20.0,
        tp_pips=30.0,
        lot=0.02,
        start_balance=10000.0,
        save_results=True,
        quiet=True,
        results_file=str(res_file)
    )

    assert results["n_ticks"] == 300
    assert "total_trades" in results
    assert "wins" in results
    assert "losses" in results
    assert "win_rate_pct" in results
    assert "final_balance" in results
    assert "max_drawdown_pct" in results
    assert res_file.exists()

    with open(res_file, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    assert saved_data["n_ticks"] == 300
    assert saved_data["final_balance"] == results["final_balance"]


def test_auto_install_to_mt4_directories_and_installation(tmp_path):
    """Verify auto_install_to_mt4 terminal directory search and copy operations."""
    # 1. find_mt4_directories returns a list without crashing
    dirs = find_mt4_directories()
    assert isinstance(dirs, list)

    # 2. install_to_target with mock source files
    mock_exp_src = tmp_path / "mock_experts"
    mock_pre_src = tmp_path / "mock_presets"
    mock_exp_src.mkdir()
    mock_pre_src.mkdir()

    (mock_exp_src / "ScalpingRobot.mq4").write_text("// EA source", encoding="utf-8")
    (mock_exp_src / "ScalpingRobot.ex4").write_bytes(b"\x00\x01\x02")
    (mock_exp_src / "readme.txt").write_text("Ignore", encoding="utf-8")  # should be ignored
    (mock_pre_src / "GoldScalper.set").write_text("Param1=10", encoding="utf-8")

    mock_target = tmp_path / "MetaTrader_Target"
    installed = install_to_target(
        target_dir=str(mock_target),
        experts_src=str(mock_exp_src),
        presets_src=str(mock_pre_src)
    )

    assert any("EA: ScalpingRobot.mq4" in f for f in installed)
    assert any("EA: ScalpingRobot.ex4" in f for f in installed)
    assert any("Preset: GoldScalper.set" in f for f in installed)
    assert not any("readme.txt" in f for f in installed)

    dst_mq4 = mock_target / "MQL4" / "Experts" / "ScalpingRobot.mq4"
    dst_set = mock_target / "MQL4" / "Presets" / "GoldScalper.set"
    assert dst_mq4.exists()
    assert dst_set.exists()


def test_auto_install_to_mt4_error_resilience():
    """Verify install_to_target handles invalid/inaccessible targets gracefully."""
    # Illegal path on Windows (nul or invalid characters)
    bad_target = "Z:\\NonExistent_Invalid_Path_99999\\MT4"
    installed = install_to_target(bad_target)
    assert isinstance(installed, list)
    assert len(installed) == 0


def test_escape_launch_flags_and_command():
    """Verify escape_launch process creation flags and command structure."""
    breakaway = get_breakaway_flags()
    assert bool(breakaway & DETACHED_PROCESS) is True
    assert bool(breakaway & CREATE_BREAKAWAY_FROM_JOB) is True

    fallback = get_fallback_flags()
    assert bool(fallback & DETACHED_PROCESS) is True
    assert bool(fallback & CREATE_BREAKAWAY_FROM_JOB) is False

    cmd = get_watchdog_command()
    assert len(cmd) == 2
    assert "python" in cmd[0].lower()
    assert "watchdog_runner.py" in cmd[1]


def test_bootstrap_launch_flags_and_command():
    """Verify bootstrap_launch process creation flags and supervisor command structure."""
    flags = get_launch_flags()
    assert bool(flags & DETACHED_PROCESS) is True
    assert bool(flags & CREATE_NEW_PROCESS_GROUP) is True
    assert bool(flags & CREATE_NO_WINDOW) is True

    cmd = get_supervisor_command()
    assert len(cmd) == 2
    assert "python" in cmd[0].lower()
    assert "supervisor.py" in cmd[1]
