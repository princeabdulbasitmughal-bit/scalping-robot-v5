"""
tests/test_batch45.py - Comprehensive Unit Tests for Batch 45 Components:
1. swarm_30_scalping_engine (Squadron Mapping): agent ID to squadron index (1-6) and metadata validation
2. swarm_30_scalping_engine (Burst Execution): concurrent thread-pool execution and report JSON generation
3. swarm_100_scalping_engine (Squadron Architecture): 100-agent distribution across 10 specialized squadrons
4. swarm_100_scalping_engine (Swarm Aggregation): end-to-end parallel execution, squadron health, and persistence
5. python_engine/risk_guard (Lot Size Invariants): lot size bounding, lot step quantization, and risk calculations
6. python_engine/risk_guard (Daily Loss & Kill Switch): hard daily loss trip wire and emergency file kill switch
7. python_engine/risk_guard (Spread & Stale Tick Filters): real-time spread limits and tick staleness fail-closed gates
8. python_engine/scalping_engine (ScalpingRobotV5 Indicators): EMA, Bollinger Bands, and Wilder's RSI calculations
9. python_engine/scalping_engine (ScalpingRobotV5 Signal Confluence): entry evaluation under spread and volatility conditions
10. swarm_resilience (Exception Handling): subagent exception containment, WARN status recovery, and zero system hang
"""

import os
import json
import time
import math
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from swarm_30_scalping_engine import ScalpingSwarm30
from swarm_100_scalping_engine import ScalpingSwarm100
from python_engine.risk_guard import RiskGuard, Decision
from python_engine.scalping_engine import ScalpingRobotV5, ScalpingSignal


def test_swarm_30_agent_mapping_and_squadrons(tmp_path):
    """Verify ScalpingSwarm30 accurately maps agent IDs 1-30 to 6 distinct squadrons."""
    swarm = ScalpingSwarm30(root_dir=tmp_path, report_file=tmp_path / "rep30.json")

    # Agent 1 -> Squadron 1 (Market Feeds)
    res1 = swarm._execute_agent(1)
    assert res1["squadron_id"] == 1
    assert "Market Feeds" in res1["squadron_name"]
    assert res1["status"] in ("OPTIMAL", "WARN")

    # Agent 8 -> Squadron 2 (Technical Indicators)
    res8 = swarm._execute_agent(8)
    assert res8["squadron_id"] == 2
    assert "Technical Indicators" in res8["squadron_name"]

    # Agent 13 -> Squadron 3 (Volatility & Dynamic TP/SL)
    res13 = swarm._execute_agent(13)
    assert res13["squadron_id"] == 3
    assert "Volatility" in res13["squadron_name"]

    # Agent 18 -> Squadron 4 (Spread & Execution)
    res18 = swarm._execute_agent(18)
    assert res18["squadron_id"] == 4
    assert "Spread" in res18["squadron_name"]

    # Agent 23 -> Squadron 5 (Drawdown & Circuit Breakers)
    res23 = swarm._execute_agent(23)
    assert res23["squadron_id"] == 5
    assert "Drawdown" in res23["squadron_name"]

    # Agent 28 -> Squadron 6 (Session & Hygiene)
    res28 = swarm._execute_agent(28)
    assert res28["squadron_id"] == 6
    assert "Session" in res28["squadron_name"]


def test_swarm_30_run_swarm_aggregation_and_report_file(tmp_path):
    """Verify ScalpingSwarm30 runs parallel burst and writes reports/swarm_30_scalping_report.json."""
    rep_file = tmp_path / "swarm_30_report.json"
    swarm = ScalpingSwarm30(root_dir=tmp_path, report_file=rep_file)

    report = swarm.run_swarm(max_workers=10, save_report=True)

    assert report["total_agents"] == 30
    assert len(report["agents"]) == 30
    assert len(report["squadrons"]) == 6
    assert "health_score" in report
    assert report["total_duration_ms"] >= 0.0
    assert rep_file.exists()

    with open(rep_file, "r", encoding="utf-8") as f:
        disk_report = json.load(f)
    assert disk_report["total_agents"] == 30
    assert swarm.get_last_report() is not None


def test_swarm_100_squadron_mapping(tmp_path):
    """Verify ScalpingSwarm100 maps agent IDs 1-100 to 10 strategic squadrons."""
    swarm = ScalpingSwarm100(root_dir=tmp_path, report_file=tmp_path / "rep100.json")

    checkpoints = [
        (5, 1, "Market Feeds"),
        (15, 2, "Technical Indicators"),
        (25, 3, "Volatility"),
        (35, 4, "Spread"),
        (45, 5, "Drawdown"),
        (55, 6, "Profit Streak"),
        (65, 7, "Time"),
        (75, 8, "Candlestick"),
        (85, 9, "ML"),
        (95, 10, "Process Watchdog"),
    ]

    for aid, exp_sq_id, exp_name_part in checkpoints:
        res = swarm._execute_agent(aid)
        assert res["id"] == aid
        assert res["squadron_id"] == exp_sq_id
        assert exp_name_part in res["squadron_name"]
        assert res["status"] in ("OPTIMAL", "WARN")


def test_swarm_100_run_swarm_execution_and_resilience(tmp_path):
    """Verify ScalpingSwarm100 runs 100 concurrent subagents and aggregates squadron metrics."""
    rep_file = tmp_path / "swarm_100_report.json"
    swarm = ScalpingSwarm100(root_dir=tmp_path, report_file=rep_file)

    report = swarm.run_swarm(fast=True, max_workers=20, save_report=True)

    assert report["total_agents"] == 100
    assert len(report["agents"]) == 100
    assert len(report["squadrons"]) == 10
    assert all(s["agents_count"] == 10 for s in report["squadrons"])
    assert rep_file.exists()

    with open(rep_file, "r", encoding="utf-8") as f:
        saved_rep = json.load(f)
    assert saved_rep["total_agents"] == 100


def test_risk_guard_lot_size_invariants(tmp_path):
    """Verify RiskGuard clamps and rejects lot sizes violating boundaries."""
    cfg = {
        "max_lot_size": 0.10,
        "min_lot_size": 0.01,
        "lot_step": 0.01,
        "risk_per_trade_pct": 1.0,
        "max_daily_loss_usd": 200.0,
        "min_balance_usd": 9700.0,
        "max_positions_per_session": 3,
        "max_trades_per_day": 50,
        "min_time_between_trades_sec": 0.0,
        "spread_filter_pips": 3.0,
        "max_tick_age_sec": 5.0,
        "min_sl_pips": 5.0,
        "max_sl_pips": 100.0,
        "pip_size": 0.1,
        "risk_state_path": str(tmp_path / "risk_state.json"),
        "kill_switch_path": str(tmp_path / "KILL_SWITCH"),
    }
    rg = RiskGuard(config=cfg)

    account = {"balance": 10000.0, "equity": 10000.0, "daily_pnl": 0.0, "open_positions": []}
    market = {"price": 2400.0, "spread_pips": 1.5, "tick_time": time.time()}

    # 1. Valid order
    order_valid = {"order_type": "BUY", "price": 2400.0, "sl": 2397.0, "tp": 2405.0, "lots": 0.02}
    dec_valid = rg.check_order(order_valid, account, market)
    assert dec_valid.allowed is True
    assert dec_valid.lot == 0.02

    # 2. Lot exceeds max_lot_size (0.10) -> clamped or blocked depending on clamp setting
    order_huge = {"order_type": "BUY", "price": 2400.0, "sl": 2397.0, "tp": 2405.0, "lots": 0.50}
    dec_huge = rg.check_order(order_huge, account, market)
    assert dec_huge.lot <= 0.10

    # 3. Lot below min_lot_size (0.01) -> rejected
    order_tiny = {"order_type": "BUY", "price": 2400.0, "sl": 2397.0, "tp": 2405.0, "lots": 0.005}
    dec_tiny = rg.check_order(order_tiny, account, market)
    assert dec_tiny.allowed is False


def test_risk_guard_daily_loss_and_kill_switch(tmp_path):
    """Verify RiskGuard blocks trading when daily loss limit is breached or kill switch is present."""
    kill_file = tmp_path / "KILL_SWITCH"
    cfg = {
        "max_daily_loss_usd": 200.0,
        "min_balance_usd": 9700.0,
        "risk_state_path": str(tmp_path / "risk_state.json"),
        "kill_switch_path": str(kill_file),
    }
    rg = RiskGuard(config=cfg)

    # 1. Breach daily loss limit: daily_pnl = -250.0 (breaches -$200.0)
    account_loss = {"balance": 9750.0, "equity": 9750.0, "daily_pnl": -250.0, "open_positions": []}
    market = {"price": 2400.0, "spread_pips": 1.5, "tick_time": time.time()}
    order = {"order_type": "BUY", "price": 2400.0, "sl": 2397.0, "tp": 2405.0, "lots": 0.02}

    dec_loss = rg.check_order(order, account_loss, market)
    assert dec_loss.allowed is False
    assert "DAILY_LOSS" in dec_loss.reason

    # 2. Healthy account but KILL_SWITCH file exists
    account_healthy = {"balance": 10000.0, "equity": 10000.0, "daily_pnl": 0.0, "open_positions": []}
    kill_file.write_text("HALT ALL TRADING", encoding="utf-8")

    dec_kill = rg.check_order(order, account_healthy, market)
    assert dec_kill.allowed is False
    assert "KILL_SWITCH" in dec_kill.reason


def test_risk_guard_spread_and_tick_age_filters(tmp_path):
    """Verify RiskGuard fail-closed behavior on excessive spread and stale ticks."""
    cfg = {
        "spread_filter_pips": 2.5,
        "max_tick_age_sec": 3.0,
        "risk_state_path": str(tmp_path / "risk_state.json"),
        "kill_switch_path": str(tmp_path / "KILL_SWITCH"),
    }
    rg = RiskGuard(config=cfg)

    account = {"balance": 10000.0, "equity": 10000.0, "daily_pnl": 0.0, "open_positions": []}
    order = {"order_type": "BUY", "price": 2400.0, "sl": 2397.0, "tp": 2405.0, "lots": 0.02}

    # 1. Spread = 3.5 pips (> 2.5 pips limit) -> rejected
    market_wide_spread = {"price": 2400.0, "spread_pips": 3.5, "tick_time": time.time()}
    dec_spread = rg.check_order(order, account, market_wide_spread)
    assert dec_spread.allowed is False
    assert "SPREAD" in dec_spread.reason

    # 2. Tick age = 10.0 seconds (> 3.0s limit) -> rejected
    market_stale_tick = {"price": 2400.0, "spread_pips": 1.5, "tick_time": time.time() - 10.0}
    dec_stale = rg.check_order(order, account, market_stale_tick)
    assert dec_stale.allowed is False
    assert "Stale tick data" in dec_stale.reason or "STALE" in dec_stale.reason.upper()


def test_scalping_robot_v5_indicator_calculations():
    """Verify ScalpingRobotV5 calculates fast/slow EMA, Bollinger Bands, and RSI on bar series."""
    robot = ScalpingRobotV5({
        "symbol": "XAUUSD",
        "fast_ema": 5,
        "slow_ema": 10,
        "bb_period": 10,
        "bb_std": 2.0,
        "rsi_period": 7,
    })

    # Generate 30 bars
    bars = []
    base_price = 2400.0
    for i in range(30):
        p = base_price + math.sin(i / 2.0) * 5.0
        bars.append({
            "open": p - 0.2,
            "high": p + 0.8,
            "low": p - 0.8,
            "close": p,
            "volume": 50,
            "timestamp": f"2026-10-20 12:{i:02d}:00"
        })

    indicators = robot.calculate_indicators(bars)
    assert "fast_ema" in indicators
    assert "slow_ema" in indicators
    assert "bb_upper" in indicators
    assert "bb_lower" in indicators
    assert "bb_mid" in indicators
    assert "rsi" in indicators
    assert indicators["bb_upper"] >= indicators["bb_lower"]
    assert 0.0 <= indicators["rsi"] <= 100.0


def test_scalping_robot_v5_signal_confluence():
    """Verify ScalpingRobotV5 signal generation under favorable and filtered market regimes."""
    robot = ScalpingRobotV5({
        "symbol": "XAUUSD",
        "max_spread_pips": 2.0,
        "rsi_oversold": 30.0,
        "rsi_overbought": 70.0,
    })

    # Favorable indicator condition for BUY: oversold RSI, price near lower band
    favorable_indicators = {
        "current_price": 2390.0,
        "bb_lower": 2392.0,
        "bb_upper": 2410.0,
        "bb_mid": 2401.0,
        "rsi": 25.0,  # oversold
        "fast_ema": 2395.0,
        "slow_ema": 2400.0,
    }

    # Low spread (1.2 pips <= 2.0 max)
    sig = robot.evaluate_entry(favorable_indicators, current_spread_pips=1.2)
    assert sig in (ScalpingSignal.BUY, ScalpingSignal.HOLD)

    # Excessive spread (3.5 pips > 2.0 max) -> suppressed to HOLD
    sig_suppressed = robot.evaluate_entry(favorable_indicators, current_spread_pips=3.5)
    assert sig_suppressed == ScalpingSignal.HOLD


def test_swarm_resilience_on_subagent_exception(tmp_path):
    """Verify Swarm engines recover from subagent exceptions without hanging or halting execution."""
    swarm = ScalpingSwarm30(root_dir=tmp_path, report_file=tmp_path / "rep_err.json")

    original_execute = swarm._execute_agent

    def mock_faulty_execute(aid):
        if aid == 7:
            raise RuntimeError("Synthetic simulated subagent worker crash")
        return original_execute(aid)

    with patch.object(swarm, "_execute_agent", side_effect=mock_faulty_execute):
        report = swarm.run_swarm(max_workers=5, save_report=False)

    assert report["total_agents"] == 30
    assert report["warn_count"] >= 1
    faulty_agent = next(a for a in report["agents"] if a["id"] == 7)
    assert faulty_agent["status"] == "WARN"
    assert "Synthetic simulated" in faulty_agent["metric"]
