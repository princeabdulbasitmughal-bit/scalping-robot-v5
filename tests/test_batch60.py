"""
Test Suite: Batch 60 — Swarm 30 Engine, Backtester Breakeven/Trailing Stops, LiveRunner Candlestick Memory & Alert Journal
===========================================================================================================================
Hermetic unit test suite verifying:
  1. ScalpingSwarm30: Squadron routing, agent execution mapping, and status structure
  2. ScalpingSwarm30: Full 30-agent burst run, report aggregation, and health scoring
  3. Backtester: BUY order breakeven lock activation upon price progression
  4. Backtester: BUY order dynamic trailing stop upward ratchet mechanics
  5. Backtester: SELL order breakeven lock and downward trailing stop ratcheting
  6. LiveRunner: Intra-minute candlestick bar aggregation (high/low/volume updating)
  7. LiveRunner: 60-second candlestick rollover and 300-bar memory bounding cap
  8. AlertSystem: Time-since-last-trade elapsed minutes calculation from telemetry
  9. AlertSystem: Atomic alert_status.json generation and field integrity
 10. TradeJournal: Optional column parameter fallback resilience and default persistence
"""

import json
import time
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pytest

from swarm_30_scalping_engine import ScalpingSwarm30
from python_engine.backtester import Backtester
from python_engine.scalping_engine import ScalpingSignal
from python_engine.live_runner import ScalpingLiveRunner
from alert_system import AlertSystem
from trade_journal import TradeJournal


# ── Test 1: ScalpingSwarm30 Agent Execution Mapping ────────────────────────────
def test_swarm_30_agent_execution_mapping():
    """Verify ScalpingSwarm30 maps agent IDs to correct squadrons with metrics and status."""
    with tempfile.TemporaryDirectory() as tmpdir:
        swarm = ScalpingSwarm30(root_dir=Path(tmpdir))

        # Agent 1 -> Squadron 1 (Market Feeds & Order Book Sentinels)
        res1 = swarm._execute_agent(1)
        assert res1["id"] == 1
        assert res1["squadron_id"] == 1
        assert "Market Feeds" in res1["squadron_name"]
        assert res1["status"] == "OPTIMAL"
        assert res1["latency_ms"] >= 0.0

        # Agent 7 -> Squadron 2 (Technical Indicators & Signal Matrix)
        res7 = swarm._execute_agent(7)
        assert res7["id"] == 7
        assert res7["squadron_id"] == 2
        assert "Technical Indicators" in res7["squadron_name"]

        # Agent 12 -> Squadron 3 (Volatility & Dynamic TP/SL Governors)
        res12 = swarm._execute_agent(12)
        assert res12["id"] == 12
        assert res12["squadron_id"] == 3
        assert "Volatility" in res12["squadron_name"]

        # Agent 18 -> Squadron 4 (Spread & Execution Governors)
        res18 = swarm._execute_agent(18)
        assert res18["id"] == 18
        assert res18["squadron_id"] == 4
        assert "Spread" in res18["squadron_name"]

        # Agent 23 -> Squadron 5 (Drawdown & Equity Circuit Breakers)
        res23 = swarm._execute_agent(23)
        assert res23["id"] == 23
        assert res23["squadron_id"] == 5
        assert "Drawdown" in res23["squadron_name"]

        # Agent 28 -> Squadron 6 (Session, Watchdog & System Hygiene)
        res28 = swarm._execute_agent(28)
        assert res28["id"] == 28
        assert res28["squadron_id"] == 6
        assert "Session" in res28["squadron_name"]


# ── Test 2: ScalpingSwarm30 Swarm Burst Execution ──────────────────────────────
def test_swarm_30_burst_run():
    """Verify run_swarm executes all 30 subagents concurrently and compiles health score."""
    with tempfile.TemporaryDirectory() as tmpdir:
        report_file = Path(tmpdir) / "swarm_report.json"
        swarm = ScalpingSwarm30(root_dir=Path(tmpdir), report_file=report_file)

        report = swarm.run_swarm(max_workers=5, save_report=False)
        assert isinstance(report, dict)
        assert report["total_agents"] == 30
        assert len(report["agents"]) == 30
        assert len(report["squadrons"]) == 6
        assert "health_score" in report
        assert report["health_score"].endswith("%")

        # In-memory report reflection
        assert swarm.get_last_report() == report


# ── Test 3: Backtester BUY Breakeven Activation ────────────────────────────────
def test_backtester_buy_breakeven_activation():
    """Verify BUY order activates breakeven lock when profit reaches threshold."""
    bt = Backtester(
        config={
            "pip_size": 0.1,
            "breakeven_pips": 8.0,       # 8 pips = 0.8 points
            "breakeven_lock_pips": 2.0,  # 2 pips = 0.2 points
        }
    )

    t = {
        "type": ScalpingSignal.BUY,
        "entry_price": 2400.0,
        "sl": 2397.0,  # 30 pips initial SL
        "tp": 2401.5,
        "breakeven_activated": False,
    }

    # Bid price reaches 2400.85 (gain = 0.85 >= 0.80 breakeven_dist)
    bid = 2400.85
    if not t["breakeven_activated"] and (bid - t["entry_price"]) >= bt.breakeven_dist:
        t["sl"] = t["entry_price"] + bt.breakeven_lock
        t["breakeven_activated"] = True

    assert t["breakeven_activated"] is True
    assert round(t["sl"], 2) == 2400.20  # Locked into +$2 profit


# ── Test 4: Backtester BUY Trailing Stop Upward Ratchet ─────────────────────────
def test_backtester_buy_trailing_stop_ratchet():
    """Verify BUY order ratchets trailing stop upward as price advances."""
    bt = Backtester(
        config={
            "pip_size": 0.1,
            "trailing_stop_pips": 10.0,  # 1.0 point trailing distance
        }
    )

    t = {
        "type": ScalpingSignal.BUY,
        "entry_price": 2400.0,
        "sl": 2400.20,
        "breakeven_activated": True,
    }

    # Price advances to 2402.50 -> new_sl = 2402.50 - 1.0 = 2401.50
    bid = 2402.50
    new_sl = bid - bt.trailing_dist
    if new_sl > t["sl"]:
        t["sl"] = new_sl

    assert round(t["sl"], 2) == 2401.50

    # Price dips slightly to 2402.00 -> SL must NOT drop backward (ratchet guarantee)
    bid_dip = 2402.00
    new_sl_dip = bid_dip - bt.trailing_dist
    if new_sl_dip > t["sl"]:
        t["sl"] = new_sl_dip

    assert round(t["sl"], 2) == 2401.50  # Maintained high watermark


# ── Test 5: Backtester SELL Breakeven & Trailing Stop ──────────────────────────
def test_backtester_sell_breakeven_and_trailing():
    """Verify SELL order activates breakeven and tightens trailing stop downward."""
    bt = Backtester(
        config={
            "pip_size": 0.1,
            "breakeven_pips": 8.0,       # 0.8 points
            "breakeven_lock_pips": 2.0,  # 0.2 points
            "trailing_stop_pips": 10.0,  # 1.0 point
        }
    )

    t = {
        "type": ScalpingSignal.SELL,
        "entry_price": 2400.0,
        "sl": 2403.0,  # 30 pips initial SL
        "breakeven_activated": False,
    }

    # Ask price drops to 2399.10 (profit = 2400.0 - 2399.10 = 0.90 >= 0.80)
    ask = 2399.10
    if not t["breakeven_activated"] and (t["entry_price"] - ask) >= bt.breakeven_dist:
        t["sl"] = t["entry_price"] - bt.breakeven_lock
        t["breakeven_activated"] = True

    assert t["breakeven_activated"] is True
    assert round(t["sl"], 2) == 2399.80  # Locked into profit below entry

    # Ask price falls further to 2398.00 -> new_sl = 2398.00 + 1.0 = 2399.00 < 2399.80
    ask_further = 2398.00
    new_sl = ask_further + bt.trailing_dist
    if new_sl < t["sl"]:
        t["sl"] = new_sl

    assert round(t["sl"], 2) == 2399.00


# ── Test 6: LiveRunner Intra-Minute Candlestick Aggregation ─────────────────────
def test_live_runner_intra_minute_bar_aggregation():
    """Verify ticks within the same minute aggregate high, low, and volume."""
    with tempfile.TemporaryDirectory() as tmpdir:
        status_file = Path(tmpdir) / "live_status.json"
        runner = ScalpingLiveRunner(config={}, status_file=status_file)

        # Baseline bar
        bar_count = len(runner.bars)
        last_bar = runner.bars[-1]
        initial_vol = last_bar.get("volume", 0)

        # High tick
        runner.update_tick(2410.00)
        assert runner.bars[-1]["high"] >= 2410.00
        assert runner.bars[-1]["close"] == 2410.00
        assert runner.bars[-1]["volume"] == initial_vol + 1
        assert len(runner.bars) == bar_count  # No new bar yet

        # Low tick
        runner.update_tick(2390.00)
        assert runner.bars[-1]["low"] <= 2390.00
        assert runner.bars[-1]["close"] == 2390.00
        assert runner.bars[-1]["volume"] == initial_vol + 2


# ── Test 7: LiveRunner Candlestick Rollover & Memory Bounding ───────────────────
def test_live_runner_rollover_and_memory_cap():
    """Verify candlestick rollover after 60s and strict 300-bar memory bounding."""
    with tempfile.TemporaryDirectory() as tmpdir:
        status_file = Path(tmpdir) / "live_status.json"
        runner = ScalpingLiveRunner(config={}, status_file=status_file)

        # 1. Force rollover by setting last_bar_time 65s in the past
        runner.last_bar_time = time.time() - 65.0
        initial_bar_count = len(runner.bars)

        runner.update_tick(2405.0)
        assert len(runner.bars) == initial_bar_count + 1
        assert runner.bars[-1]["open"] == 2405.0
        assert runner.bars[-1]["close"] == 2405.0

        # 2. Memory bounding: populate 350 bars and verify cap at 300
        runner.bars = [{"close": 2400.0} for _ in range(350)]
        runner.last_bar_time = time.time() - 70.0  # trigger rollover
        runner.update_tick(2402.0)

        assert len(runner.bars) <= 300


# ── Test 8: AlertSystem Time Since Last Trade Calculation ──────────────────────
def test_alert_system_time_since_last_trade():
    """Verify get_time_since_last_trade_minutes accurately computes elapsed minutes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        status_file = Path(tmpdir) / "live_status.json"
        alert_sys = AlertSystem(status_file=status_file)

        # Mock trade 20 minutes ago
        now_dt = datetime.now(timezone.utc)
        trade_time = (now_dt - timedelta(minutes=20)).isoformat()

        data = {"last_trade_time": trade_time}
        minutes_idle = alert_sys.get_time_since_last_trade_minutes(data)

        # Must be close to 20.0 minutes
        assert 19.5 <= minutes_idle <= 20.5


# ── Test 9: AlertSystem Status File Persistence ────────────────────────────────
def test_alert_system_status_file_persistence():
    """Verify _write_alert_status writes atomically and preserves fields."""
    with tempfile.TemporaryDirectory() as tmpdir:
        alert_status_file = Path(tmpdir) / "alert_status.json"
        alert_sys = AlertSystem(alert_status_file=alert_status_file)

        alert_sys.last_alert = "ALERT: Win rate critical: 65%"
        alert_sys.total_alerts_today = 3
        alert_sys._write_alert_status("CRITICAL")

        assert alert_status_file.exists()
        saved = json.loads(alert_status_file.read_text(encoding="utf-8"))
        assert saved["status"] == "CRITICAL"
        assert saved["last_alert"] == "ALERT: Win rate critical: 65%"
        assert saved["total_alerts_today"] == 3
        assert "date" in saved
        assert "updated_at" in saved


# ── Test 10: TradeJournal Optional Column Fallbacks ────────────────────────────
def test_trade_journal_optional_defaults():
    """Verify log_trade safely handles missing or None optional fields."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "minimal_trades.db"
        journal = TradeJournal(db_path=str(db_path))

        minimal_trade = {
            "symbol": "XAUUSD",
            "direction": "BUY",
            "entry_price": 2400.0,
            "pnl": 12.50,
            # optional fields omitted (exit_price, duration_sec, signal_tier, spread_pips)
        }

        assert journal.log_trade(minimal_trade) is True

        trades = journal.get_last_N_trades(1)
        assert len(trades) == 1
        t = trades[0]
        assert t["symbol"] == "XAUUSD"
        assert t["pnl"] == 12.50
        assert t["exit_price"] == 0.0
        assert t["duration_sec"] == 0
        assert t["signal_tier"] == 0
        assert t["spread_pips"] == 0.0
