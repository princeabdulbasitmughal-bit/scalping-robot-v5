"""
tests/test_batch70.py
Batch 70 Landmark Milestone Unit Tests: Universal MT4/MT5 Installer (auto_install_to_mt4.py),
Gold News Awareness Fetcher (gold_news_fetcher.py), Watchdog Exponential Backoff (watchdog_runner.py),
and Autonomous Paper/Live Scalping Runner (live_runner.py).
"""

import math
import time
import os
from pathlib import Path
import pytest
from datetime import datetime, timezone

from auto_install_to_mt4 import install_to_target
from gold_news_fetcher import check_high_impact, write_status
from watchdog_runner import calculate_backoff, log_restart
from python_engine.live_runner import ScalpingLiveRunner
from python_engine.scalping_engine import ScalpingSignal


def test_auto_install_to_mt4_file_copying_and_directory_creation(tmp_path):
    """Verify install_to_target creates MQL4 subdirectories and copies EA/Presets."""
    target_dir = tmp_path / "MetaTrader_Terminal"
    exp_src = tmp_path / "Experts_Src"
    pre_src = tmp_path / "Presets_Src"

    exp_src.mkdir(parents=True, exist_ok=True)
    pre_src.mkdir(parents=True, exist_ok=True)

    # Create dummy expert and preset files
    (exp_src / "ScalpingRobotV5.ex4").write_text("// dummy binary", encoding="utf-8")
    (exp_src / "ScalpingRobotV5.mq4").write_text("// dummy source", encoding="utf-8")
    (exp_src / "readme.txt").write_text("ignore this file", encoding="utf-8")
    (pre_src / "XAUUSD_Aggressive.set").write_text("Lot=0.02\nTP=15.0", encoding="utf-8")

    installed = install_to_target(
        target_dir=str(target_dir),
        experts_src=str(exp_src),
        presets_src=str(pre_src),
    )

    assert len(installed) == 3
    assert any("ScalpingRobotV5.ex4" in item for item in installed)
    assert any("ScalpingRobotV5.mq4" in item for item in installed)
    assert any("XAUUSD_Aggressive.set" in item for item in installed)

    # Check destinations
    assert (target_dir / "MQL4" / "Experts" / "ScalpingRobotV5.ex4").exists()
    assert (target_dir / "MQL4" / "Presets" / "XAUUSD_Aggressive.set").exists()
    assert not (target_dir / "MQL4" / "Experts" / "readme.txt").exists()


def test_auto_install_to_mt4_permission_and_error_handling(tmp_path):
    """Verify install_to_target handles nonexistent source folders safely."""
    target_dir = tmp_path / "Terminal"
    nonexistent_exp = tmp_path / "does_not_exist_exp"
    nonexistent_pre = tmp_path / "does_not_exist_pre"

    installed = install_to_target(
        target_dir=str(target_dir),
        experts_src=str(nonexistent_exp),
        presets_src=str(nonexistent_pre),
    )
    assert installed == []


def test_gold_news_fetcher_regex_keyword_matching():
    """Verify check_high_impact uses whole-word regex matching for financial terms."""
    # Match on high impact keywords
    headlines_with_impact = [
        ("federal reserve signals rate pause in upcoming fomc meeting", "2026-10-17"),
        ("gold holds steady as inflation data looms", "2026-10-17"),
    ]
    is_hi, kw = check_high_impact(headlines_with_impact)
    assert is_hi is True

    # No match on benign headlines or embedded substrings (e.g. 'forward' != 'fed')
    benign_headlines = [
        ("looking forward to strong company earnings", "2026-10-17"),
        ("tech sector shows slight daily advance", "2026-10-17"),
    ]
    is_hi2, _ = check_high_impact(benign_headlines)
    assert is_hi2 is False


def test_gold_news_fetcher_write_status_atomic_persistence(tmp_path, monkeypatch):
    """Verify write_status persists news avoid_trading status atomically."""
    status_file = tmp_path / "news_status.json"
    monkeypatch.setattr("gold_news_fetcher.NEWS_STATUS_FILE", str(status_file))

    sample_headlines = [
        ("us cpi surges higher than consensus expectation", "2026-10-17T12:30:00Z"),
    ]

    write_status(high_impact=True, headlines=sample_headlines, avoid_trading=True)

    assert status_file.exists()
    import json
    with open(status_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["high_impact_alert"] is True
    assert data["avoid_trading"] is True
    assert len(data["last_headlines"]) == 1
    assert "cpi surges" in data["last_headlines"][0]


def test_watchdog_runner_calculate_backoff_progression():
    """Verify calculate_backoff follows exponential ladder with 300s ceiling."""
    assert calculate_backoff(0) == 30
    assert calculate_backoff(1) == 60
    assert calculate_backoff(2) == 120
    assert calculate_backoff(3) == 240
    assert calculate_backoff(4) == 300
    assert calculate_backoff(10) == 300


def test_watchdog_runner_log_restart_formatting(tmp_path, monkeypatch):
    """Verify log_restart writes structured restart record to watchdog log."""
    log_file = tmp_path / "watchdog.log"
    monkeypatch.setattr("watchdog_runner.WATCHDOG_LOG", log_file)

    log_restart(target="trader", reason="HEARTBEAT_STALE", restart_count=2, backoff_seconds=120)

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "[RESTART] trader restart triggered" in content
    assert "reason: HEARTBEAT_STALE" in content
    assert "restart_count=2" in content
    assert "backoff_seconds=120" in content


def test_scalping_live_runner_tick_update_and_atomic_status(tmp_path):
    """Verify ScalpingLiveRunner executes tick update and writes status snapshot."""
    status_file = tmp_path / "live_status.json"
    runner = ScalpingLiveRunner(
        config={"bb_period": 10, "rsi_period": 10, "fast_ema": 5, "slow_ema": 10},
        status_file=status_file,
    )

    status = runner.update_tick(tick_price=2650.50)
    assert status["status"] == "ACTIVE_SCALPING"
    assert status["current_price"] == 2650.50
    assert status["balance"] == 10000.0
    assert status_file.exists()


def test_scalping_live_runner_candlestick_aggregation(tmp_path):
    """Verify multiple ticks in the same minute interval aggregate into the current bar."""
    status_file = tmp_path / "live_status.json"
    runner = ScalpingLiveRunner(status_file=status_file)

    runner.update_tick(tick_price=2650.00)
    runner.update_tick(tick_price=2655.00)  # new high
    runner.update_tick(tick_price=2645.00)  # new low
    runner.update_tick(tick_price=2652.00)  # close

    last_bar = runner.bars[-1]
    assert last_bar["high"] >= 2655.00
    assert last_bar["low"] <= 2645.00
    assert last_bar["close"] == 2652.00
    assert last_bar["volume"] >= 4


def test_scalping_live_runner_position_tp_sl_lifecycle(tmp_path):
    """Verify open position closes automatically when price crosses TP boundary."""
    status_file = tmp_path / "live_status.json"
    runner = ScalpingLiveRunner(
        config={"pip_size": 0.1, "lot_size": 0.02, "pip_value": 1.0},
        status_file=status_file,
    )

    # Inject an active BUY position: Entry=2650.00, TP=2655.00, SL=2640.00
    runner.robot.open_positions = [{
        "id": 1,
        "type": ScalpingSignal.BUY,
        "symbol": "XAUUSD",
        "entry": 2650.00,
        "tp": 2655.00,
        "sl": 2640.00,
        "lot": 0.02,
        "open_time": "2026-10-17T12:00:00Z",
    }]

    # Update tick at 2656.00 (crosses TP)
    status = runner.update_tick(tick_price=2656.00)

    # Position should be closed
    assert len(runner.robot.open_positions) == 0
    assert runner.total_trades_count == 1
    assert runner.winning_trades_count == 1
    assert runner.balance > 10000.0
    assert runner.daily_pnl > 0.0
    assert runner.trades_history[-1]["close_reason"] == "TP_HIT"


def test_scalping_live_runner_error_resilience(tmp_path):
    """Verify update_tick handles non-finite inputs cleanly without raising exceptions."""
    status_file = tmp_path / "live_status.json"
    runner = ScalpingLiveRunner(status_file=status_file)

    # Pass None and NaN prices
    st1 = runner.update_tick(tick_price=None)
    assert st1["status"] in ("ACTIVE_SCALPING", "ERROR_RECOVERING")

    st2 = runner.update_tick(tick_price=float("nan"))
    assert st2["status"] in ("ACTIVE_SCALPING", "ERROR_RECOVERING")
