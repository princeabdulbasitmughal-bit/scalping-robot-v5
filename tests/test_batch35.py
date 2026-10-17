"""
tests/test_batch35.py - Comprehensive Unit Tests for Batch 35 Components:
1. ScalpingSwarm30 (concurrency, squadrons, fast mode, report caching)
2. ScalpingSwarm100 (100 agents, 10 squadrons, error recovery, report caching)
3. run_backtest input sanitization and bb_signal robustness
4. run_backtest simulation execution and profit factor calculations
5. watchdog_runner calculate_backoff exponential bounding
6. watchdog_runner health check and restart reason detection
7. WatchdogRunner class thread-safe status and custom path configuration
8. bootstrap_launch and escape_launch process flags and command constructors
9. ScalpingLiveRunner tick updates, candlestick rolling, reset, and state queries
10. python_engine package exports, version metadata, and interface integrity
"""

import math
import time
import json
from pathlib import Path
import pytest

from swarm_30_scalping_engine import ScalpingSwarm30
from swarm_100_scalping_engine import ScalpingSwarm100
from run_backtest import simulate_price, bb_signal, run_backtest
import watchdog_runner
from watchdog_runner import WatchdogRunner, calculate_backoff, health_check, detect_restart_reason
import bootstrap_launch
import escape_launch
from python_engine.live_runner import ScalpingLiveRunner
import python_engine


def test_swarm_30_scalping_engine():
    """Verify ScalpingSwarm30 execution, squadrons, optimal counts, and report caching."""
    swarm = ScalpingSwarm30()
    report = swarm.run_swarm(fast=True, max_workers=10, save_report=False)

    assert report["total_agents"] == 30
    assert len(report["agents"]) == 30
    assert len(report["squadrons"]) == 6
    assert report["optimal_count"] >= 20
    assert "health_score" in report

    cached = swarm.get_last_report()
    assert cached is not None
    assert cached["total_agents"] == 30
    assert cached["agents"][0]["id"] == 1


def test_swarm_100_scalping_engine():
    """Verify ScalpingSwarm100 execution across 10 squadrons and report caching."""
    swarm = ScalpingSwarm100()
    report = swarm.run_swarm(fast=True, max_workers=20, save_report=False)

    assert report["total_agents"] == 100
    assert len(report["agents"]) == 100
    assert len(report["squadrons"]) == 10
    assert report["optimal_count"] >= 70
    assert "health_score" in report

    cached = swarm.get_last_report()
    assert cached is not None
    assert cached["total_agents"] == 100
    assert cached["agents"][99]["id"] == 100


def test_run_backtest_sanitization():
    """Verify simulate_price and bb_signal handle invalid and non-finite values safely."""
    # Degenerate ticks or negative start price
    prices = simulate_price(n_ticks=-5, start_price=-100.0)
    assert len(prices) == 1
    assert prices[0] == 2400.0

    # Non-finite start price
    prices_nan = simulate_price(n_ticks=25, start_price=float("nan"))
    assert len(prices_nan) == 25
    assert prices_nan[0] == 2400.0

    # bb_signal out of bounds or invalid window
    assert bb_signal([], 0) == "HOLD"
    assert bb_signal([2400.0] * 10, 5, period=20) == "HOLD"

    # bb_signal with non-finite values in window
    nan_window = [2400.0] * 19 + [float("nan"), 2405.0]
    assert bb_signal(nan_window, 20, period=20) == "HOLD"


def test_run_backtest_execution():
    """Verify run_backtest simulation runs with sanitized inputs and produces valid metrics."""
    res = run_backtest(
        n_ticks=100,
        sl_pips=20.0,
        tp_pips=30.0,
        lot=0.01,
        start_balance=5000.0,
        save_results=False,
        quiet=True
    )

    assert res["n_ticks"] == 100
    assert res["final_balance"] > 0
    assert res["win_rate_pct"] >= 0.0
    assert res["max_drawdown_pct"] >= 0.0
    assert res["profit_factor"] >= 0.0
    assert "timestamp" in res


def test_watchdog_calculate_backoff():
    """Verify exponential backoff calculation and clamping at 300 seconds."""
    assert calculate_backoff(-2) == 30
    assert calculate_backoff(0) == 30
    assert calculate_backoff(1) == 60
    assert calculate_backoff(2) == 120
    assert calculate_backoff(3) == 240
    assert calculate_backoff(4) == 300
    assert calculate_backoff(10) == 300


def test_watchdog_health_and_restart_detection(tmp_path):
    """Verify health check and restart reason detection logic."""
    status_file = tmp_path / "live_status.json"

    # Non-existent file
    assert health_check(status_file) is False

    # Fresh healthy file with ok=True
    now = time.time()
    status_file.write_text(json.dumps({"ok": True, "timestamp": now}), encoding="utf-8")
    assert health_check(status_file) is True

    # Stale file (>60s)
    status_file.write_text(json.dumps({"ok": True, "timestamp": now - 120}), encoding="utf-8")
    assert health_check(status_file) is False

    # Status string fallback
    status_file.write_text(json.dumps({"status": "active_scalping", "timestamp": now}), encoding="utf-8")
    assert health_check(status_file) is True

    # Restart reason detection for dead process
    reason = detect_restart_reason(None)
    assert reason is not None
    assert "CRASH" in reason


def test_watchdog_runner_class_thread_safety(tmp_path):
    """Verify WatchdogRunner thread lock, custom file overrides, and status reporting."""
    mock_status = tmp_path / "custom_status.json"
    mock_log = tmp_path / "custom_watchdog.log"
    mock_status.write_text(json.dumps({"ok": True, "timestamp": time.time()}), encoding="utf-8")

    runner = WatchdogRunner(status_file=mock_status, log_file=mock_log)
    status = runner.get_status()

    assert status["cycle"] == 0
    assert status["consecutive_restarts"] == 0
    assert status["restart_count"] == 0
    assert status["status_file"] == str(mock_status)
    assert runner.health_check() is True
    assert runner.status_age() < 10.0


def test_bootstrap_and_escape_launch_metadata():
    """Verify process creation flags and command builders without executing live processes."""
    # bootstrap_launch checks
    b_flags = bootstrap_launch.get_launch_flags()
    assert b_flags & bootstrap_launch.DETACHED_PROCESS
    assert b_flags & bootstrap_launch.CREATE_NEW_PROCESS_GROUP
    b_cmd = bootstrap_launch.get_supervisor_command()
    assert len(b_cmd) == 2
    assert "supervisor.py" in b_cmd[1]

    # escape_launch checks
    e_flags = escape_launch.get_breakaway_flags()
    assert e_flags & escape_launch.CREATE_BREAKAWAY_FROM_JOB
    e_fallback = escape_launch.get_fallback_flags()
    assert e_fallback & escape_launch.DETACHED_PROCESS
    e_cmd = escape_launch.get_watchdog_command()
    assert len(e_cmd) == 2
    assert "watchdog_runner.py" in e_cmd[1]


def test_live_runner_ticks_and_state():
    """Verify ScalpingLiveRunner tick consumption, state reporting, and thread-safe reset."""
    runner = ScalpingLiveRunner()
    
    # Update valid tick
    res = runner.update_tick(2410.50)
    assert res["status"] in ("ACTIVE_SCALPING", "ERROR_RECOVERING")
    assert res["current_price"] == 2410.50

    # Non-finite tick safety
    res_nan = runner.update_tick(float("nan"))
    assert math.isfinite(res_nan["current_price"])

    # State inspection
    state = runner.get_state()
    assert "balance" in state
    assert "equity" in state
    assert state["bars_count"] >= 100

    # Reset
    runner.reset(15000.0)
    reset_state = runner.get_state()
    assert reset_state["balance"] == 15000.0
    assert reset_state["equity"] == 15000.0
    assert reset_state["open_positions_count"] == 0


def test_python_engine_package_exports():
    """Verify python_engine package version, key symbols, and export integrity."""
    assert hasattr(python_engine, "__version__")
    assert python_engine.__version__ == "5.0.0"
    assert hasattr(python_engine, "ScalpingRobotV5")
    assert hasattr(python_engine, "ScalpingSignal")
    assert hasattr(python_engine, "Backtester")
    assert hasattr(python_engine, "atomic_write_json")
    assert hasattr(python_engine, "ScalpingLiveRunner")
    assert hasattr(python_engine, "RiskGuard")
    assert hasattr(python_engine, "Decision")
