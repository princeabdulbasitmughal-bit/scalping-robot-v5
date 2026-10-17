"""
tests/test_batch80.py
Batch 80 Unit Tests: Scalping Live Runner & Order Lifecycle Simulation (python_engine/live_runner.py).
Expands test baseline beyond 1,047+ passing tests.
Verifies:
1. live_runner: Initialization defaults, bar seeding (100 bars), and custom status file routing.
2. live_runner: Tick input sanitization (handling None, negative, NaN, Inf, and positive floats).
3. live_runner: Candlestick bar aggregation and 60-second rollover generation.
4. live_runner: BUY position Take-Profit closing and PnL accounting.
5. live_runner: BUY position Stop-Loss closing and loss accounting.
6. live_runner: SELL position Take-Profit and Stop-Loss executions.
7. live_runner: Mark-to-market floating equity valuation across open positions.
8. live_runner: reset() lifecycle and non-finite balance protection.
9. live_runner: Memory bounding (300-bar limit and 1000-trade history cap).
10. live_runner: Atomic status file persistence without orphaned .tmp files.
"""

import json
import math
import time
from pathlib import Path
import pytest

from python_engine.live_runner import ScalpingLiveRunner
from python_engine.scalping_engine import ScalpingSignal


def test_live_runner_initialization_and_custom_status_path(tmp_path):
    """Verify ScalpingLiveRunner initializes with seeded bars and routes to custom status file."""
    custom_status = tmp_path / "live_status.json"
    runner = ScalpingLiveRunner(status_file=custom_status)

    assert runner.status_file == custom_status
    assert runner.balance == 10000.0
    assert runner.equity == 10000.0
    assert len(runner.bars) == 100
    assert runner.total_trades_count == 0

    state = runner.get_state()
    assert state["symbol"] == "XAUUSD"
    assert state["balance"] == 10000.0
    assert state["bars_count"] == 100


def test_live_runner_tick_input_sanitization(tmp_path):
    """Verify update_tick safely accepts finite floats and falls back to drift for invalid inputs."""
    custom_status = tmp_path / "live_status.json"
    runner = ScalpingLiveRunner(status_file=custom_status)

    init_price = runner.current_price

    # 1. Valid finite price
    s1 = runner.update_tick(2650.50)
    assert runner.current_price == 2650.50
    assert s1["current_price"] == 2650.50

    # 2. None -> drift
    runner.update_tick(None)
    assert math.isfinite(runner.current_price)

    # 3. Negative float -> drift fallback
    runner.update_tick(-2500.0)
    assert runner.current_price > 0

    # 4. NaN / Inf -> drift fallback
    runner.update_tick(float("nan"))
    assert math.isfinite(runner.current_price)
    runner.update_tick(float("inf"))
    assert math.isfinite(runner.current_price)


def test_live_runner_candlestick_bar_update_and_rollover(tmp_path):
    """Verify update_tick updates active bar high/low/close and creates new bar after 60s."""
    custom_status = tmp_path / "live_status.json"
    runner = ScalpingLiveRunner(status_file=custom_status)

    init_bar_count = len(runner.bars)

    # Intra-bar price updates
    runner.update_tick(2655.0)
    last_bar = runner.bars[-1]
    assert last_bar["close"] == 2655.0
    assert last_bar["high"] >= 2655.0
    assert len(runner.bars) == init_bar_count

    # Simulate 65 seconds passing
    runner.last_bar_time = time.time() - 65.0
    runner.update_tick(2660.0)

    # New bar created
    assert len(runner.bars) == init_bar_count + 1
    assert runner.bars[-1]["open"] == 2660.0
    assert runner.bars[-1]["close"] == 2660.0


def test_live_runner_buy_take_profit_hit(tmp_path):
    """Verify BUY position closes with TP_HIT when market reaches or exceeds take-profit."""
    custom_status = tmp_path / "live_status.json"
    config = {"pip_size": 0.1, "lot_size": 0.01, "pip_value": 1.0}
    runner = ScalpingLiveRunner(config=config, status_file=custom_status)
    runner.current_price = 2650.0

    # Inject BUY position: Entry 2650.0, TP 2660.0 (+100 pips = +$100)
    runner.robot.open_positions = [{
        "id": 1,
        "type": ScalpingSignal.BUY,
        "entry": 2650.0,
        "tp": 2660.0,
        "sl": 2640.0,
        "lot": 0.01,
    }]

    # Price crosses TP
    runner.update_tick(2661.0)

    assert len(runner.robot.open_positions) == 0
    assert len(runner.trades_history) == 1
    closed_trade = runner.trades_history[0]
    assert closed_trade["close_reason"] == "TP_HIT"
    assert closed_trade["pnl"] == 100.0
    assert runner.balance == 10100.0
    assert runner.total_trades_count == 1
    assert runner.winning_trades_count == 1


def test_live_runner_buy_stop_loss_hit(tmp_path):
    """Verify BUY position closes with SL_HIT when market drops to or below stop-loss."""
    custom_status = tmp_path / "live_status.json"
    config = {"pip_size": 0.1, "lot_size": 0.01, "pip_value": 1.0}
    runner = ScalpingLiveRunner(config=config, status_file=custom_status)
    runner.current_price = 2650.0

    # Inject BUY position: Entry 2650.0, SL 2640.0 (-100 pips = -$100)
    runner.robot.open_positions = [{
        "id": 2,
        "type": ScalpingSignal.BUY,
        "entry": 2650.0,
        "tp": 2665.0,
        "sl": 2640.0,
        "lot": 0.01,
    }]

    # Price crosses SL
    runner.update_tick(2639.0)

    assert len(runner.robot.open_positions) == 0
    assert len(runner.trades_history) == 1
    closed_trade = runner.trades_history[0]
    assert closed_trade["close_reason"] == "SL_HIT"
    assert closed_trade["pnl"] == -100.0
    assert runner.balance == 9900.0
    assert runner.total_trades_count == 1
    assert runner.winning_trades_count == 0


def test_live_runner_sell_take_profit_and_stop_loss(tmp_path):
    """Verify SELL position closes with TP_HIT on downward move and SL_HIT on upward move."""
    custom_status = tmp_path / "live_status.json"
    config = {"pip_size": 0.1, "lot_size": 0.01, "pip_value": 1.0}
    runner = ScalpingLiveRunner(config=config, status_file=custom_status)

    # 1. SELL TP: Entry 2650.0, TP 2640.0, Price drops to 2638.0
    runner.robot.open_positions = [{
        "id": 10,
        "type": ScalpingSignal.SELL,
        "entry": 2650.0,
        "tp": 2640.0,
        "sl": 2660.0,
        "lot": 0.01,
    }]
    runner.update_tick(2638.0)
    assert len(runner.robot.open_positions) == 0
    assert runner.trades_history[-1]["close_reason"] == "TP_HIT"
    assert runner.trades_history[-1]["pnl"] == 100.0

    # 2. SELL SL: Entry 2650.0, SL 2660.0, Price rises to 2662.0
    runner.robot.open_positions = [{
        "id": 11,
        "type": ScalpingSignal.SELL,
        "entry": 2650.0,
        "tp": 2640.0,
        "sl": 2660.0,
        "lot": 0.01,
    }]
    runner.update_tick(2662.0)
    assert len(runner.robot.open_positions) == 0
    assert runner.trades_history[-1]["close_reason"] == "SL_HIT"
    assert runner.trades_history[-1]["pnl"] == -100.0


def test_live_runner_mark_to_market_floating_equity(tmp_path):
    """Verify equity reflects real-time floating PnL of open positions."""
    custom_status = tmp_path / "live_status.json"
    config = {"pip_size": 0.1, "lot_size": 0.01, "pip_value": 1.0}
    runner = ScalpingLiveRunner(config=config, status_file=custom_status)
    runner.balance = 10000.0

    # Open BUY from 2650.0 (wide SL/TP so it remains open)
    runner.robot.open_positions = [{
        "id": 5,
        "type": ScalpingSignal.BUY,
        "entry": 2650.0,
        "tp": 2700.0,
        "sl": 2600.0,
        "lot": 0.01,
    }]

    # Price at 2655.0 (+50 pips = +$50 floating profit)
    status_up = runner.update_tick(2655.0)
    assert status_up["equity"] == 10050.0
    assert runner.equity == 10050.0

    # Price at 2645.0 (-50 pips = -$50 floating loss)
    status_down = runner.update_tick(2645.0)
    assert status_down["equity"] == 9950.0
    assert runner.equity == 9950.0


def test_live_runner_reset_lifecycle(tmp_path):
    """Verify reset() restores clean state and safely handles invalid balance values."""
    custom_status = tmp_path / "live_status.json"
    runner = ScalpingLiveRunner(status_file=custom_status)

    runner.balance = 15000.0
    runner.daily_pnl = 250.0
    runner.total_trades_count = 5
    runner.robot.open_positions = [{"id": 1}]
    runner.trades_history = [{"id": 1}]

    # 1. Valid balance reset
    runner.reset(balance=12500.0)
    assert runner.balance == 12500.0
    assert runner.equity == 12500.0
    assert runner.daily_pnl == 0.0
    assert runner.total_trades_count == 0
    assert runner.robot.open_positions == []
    assert runner.trades_history == []

    # 2. Non-finite or negative balance resets safely to 10000.0 default
    runner.reset(balance=-500.0)
    assert runner.balance == 10000.0
    runner.reset(balance=float("nan"))
    assert runner.balance == 10000.0


def test_live_runner_history_and_bars_memory_bounding(tmp_path):
    """Verify bars list is capped at 300 items and trades_history at 1000 items."""
    custom_status = tmp_path / "live_status.json"
    runner = ScalpingLiveRunner(status_file=custom_status)

    # 1. Overfill bars
    for i in range(350):
        runner.bars.append({"open": 2650.0, "high": 2650.0, "low": 2650.0, "close": 2650.0, "volume": 1})
    assert len(runner.bars) > 300

    # Trigger rollover
    runner.last_bar_time = time.time() - 65.0
    runner.update_tick(2650.0)
    assert len(runner.bars) <= 300

    # 2. Overfill trades history
    config = {"pip_size": 0.1, "lot_size": 0.01, "pip_value": 1.0}
    runner.robot.config = config
    for i in range(1050):
        runner.trades_history.append({"id": i, "pnl": 10.0})

    runner.robot.open_positions = [{
        "id": 9999,
        "type": ScalpingSignal.BUY,
        "entry": 2650.0,
        "tp": 2655.0,
        "sl": 2640.0,
    }]
    # Trigger TP close
    runner.update_tick(2656.0)
    assert len(runner.trades_history) <= 1000


def test_live_runner_atomic_status_file_persistence(tmp_path):
    """Verify update_tick writes status JSON atomically without leaving temp files."""
    custom_status = tmp_path / "live_status.json"
    runner = ScalpingLiveRunner(status_file=custom_status)

    status = runner.update_tick(2652.25)

    assert custom_status.exists()
    assert not custom_status.with_suffix(".tmp").exists()

    with open(custom_status, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["status"] == "ACTIVE_SCALPING"
    assert data["current_price"] == 2652.25
    assert data["symbol"] == "XAUUSD"
    assert "updated_at" in data
