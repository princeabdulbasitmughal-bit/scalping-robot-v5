"""
Test Suite: Batch 59 — Backtester Confluence & Execution, LiveRunner State Sync, Trade Journal Multi-Day, Log Analyzer & Alert System
=====================================================================================================================================
Hermetic unit test suite verifying:
  1. Backtester: Tier 1 Bollinger Bands & Tier 3 RSI signal evaluation
  2. Backtester: High spread signal suppression
  3. Backtester: End-to-end tick simulation metrics calculation (PnL, win rate, drawdown)
  4. LiveRunner: Atomic live_status.json synchronization and telemetry structure
  5. LiveRunner: Thread-safe state introspection and full engine reset
  6. TradeJournal: Multi-day historical aggregation and target date query isolation
  7. LogAnalyzer: Integrated trades.log parsing and position count verification
  8. AlertSystem: Timestamp parser resilience across formats (epoch, ISO, Z-suffix, log format)
  9. AlertSystem: Active trading session detection and halted status overrides
 10. AutoBackup: Atomic instance lock acquisition and release lifecycle
"""

import json
import math
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch
import pytest

from python_engine.backtester import Backtester
from python_engine.scalping_engine import ScalpingSignal
from python_engine.live_runner import ScalpingLiveRunner
from trade_journal import TradeJournal
from log_analyzer import parse_trader_log
from alert_system import AlertSystem, parse_timestamp_utc
import auto_backup


# ── Test 1: Backtester Multi-Tier Signal Evaluation ────────────────────────────
def test_backtester_signal_evaluation_tiers():
    """Verify Backtester evaluate_signal evaluates Tier 1 BB and Tier 3 RSI signals."""
    bt = Backtester(config={"max_spread_pips": 3.0})

    # Tier 1: Bollinger Bands Mean Reversion
    # Close <= bb_lower and RSI < 55 -> BUY
    ind_buy_bb = {
        "close": 2395.0,
        "bb_lower": 2396.0,
        "bb_upper": 2410.0,
        "bb_mid": 2403.0,
        "rsi": 40.0,
    }
    assert bt.evaluate_signal(ind_buy_bb, current_spread_pips=1.0) == ScalpingSignal.BUY

    # Close >= bb_upper and RSI > 45 -> SELL
    ind_sell_bb = {
        "close": 2412.0,
        "bb_lower": 2396.0,
        "bb_upper": 2410.0,
        "bb_mid": 2403.0,
        "rsi": 60.0,
    }
    assert bt.evaluate_signal(ind_sell_bb, current_spread_pips=1.0) == ScalpingSignal.SELL

    # Tier 3: RSI Extremes (neutral BB)
    ind_rsi_extreme_buy = {
        "close": 2403.0,
        "bb_lower": 2390.0,
        "bb_upper": 2415.0,
        "bb_mid": 2403.0,
        "rsi": 30.0,  # <= 35.0
    }
    assert bt.evaluate_signal(ind_rsi_extreme_buy, current_spread_pips=1.0) == ScalpingSignal.BUY


# ── Test 2: Backtester Spread Suppression ──────────────────────────────────────
def test_backtester_spread_suppression():
    """Verify evaluate_signal suppresses signals to HOLD when spread exceeds limit."""
    bt = Backtester(config={"max_spread_pips": 2.0})

    # Clear BUY setup
    ind_buy = {
        "close": 2395.0,
        "bb_lower": 2396.0,
        "bb_upper": 2410.0,
        "rsi": 30.0,
    }

    # Allowed spread -> BUY
    assert bt.evaluate_signal(ind_buy, current_spread_pips=1.5) == ScalpingSignal.BUY

    # Excessive spread (> 2.0 pips) -> HOLD
    assert bt.evaluate_signal(ind_buy, current_spread_pips=2.5) == ScalpingSignal.HOLD


# ── Test 3: Backtester Full Tick Simulation Execution ──────────────────────────
def test_backtester_run_simulation_execution():
    """Verify run_backtest_ticks executes full tick simulation and computes complete analytics."""
    bt = Backtester(config={"tp_pips": 15.0, "sl_pips": 25.0, "lot_size": 0.01})
    results = bt.run_backtest_ticks(
        n_ticks=100,
        initial_balance=10000.0,
        session="LONDON",
        start_price=2400.0,
        print_summary=False,
    )

    assert isinstance(results, dict)
    assert "total_trades" in results
    assert "wins" in results
    assert "losses" in results
    assert "total_pnl" in results
    assert "max_drawdown" in results
    assert "win_rate" in results
    assert "final_balance" in results
    assert results["ticks_simulated"] == 100
    assert math.isfinite(results["final_balance"])


# ── Test 4: LiveRunner Atomic State Synchronization ────────────────────────────
def test_live_runner_atomic_status_sync():
    """Verify ScalpingLiveRunner writes structured live_status.json atomically."""
    with tempfile.TemporaryDirectory() as tmpdir:
        status_file = Path(tmpdir) / "live_status.json"
        runner = ScalpingLiveRunner(config={}, status_file=status_file)

        status_result = runner.update_tick(2402.50)
        assert status_file.exists()

        saved_data = json.loads(status_file.read_text(encoding="utf-8"))
        assert saved_data["status"] == "ACTIVE_SCALPING"
        assert saved_data["current_price"] == 2402.50
        assert saved_data["balance"] == 10000.0
        assert "equity" in saved_data
        assert "updated_at" in saved_data
        assert saved_data["current_price"] == status_result["current_price"]


# ── Test 5: LiveRunner State Introspection & Reset ──────────────────────────────
def test_live_runner_state_and_reset():
    """Verify get_state provides thread-safe snapshot and reset restores balance."""
    with tempfile.TemporaryDirectory() as tmpdir:
        status_file = Path(tmpdir) / "live_status.json"
        runner = ScalpingLiveRunner(config={}, status_file=status_file)

        state = runner.get_state()
        assert state["current_price"] == runner.current_price
        assert state["balance"] == 10000.0
        assert state["bars_count"] >= 100

        # Reset runner with new starting balance
        runner.reset(balance=12500.0)
        state_after = runner.get_state()
        assert state_after["balance"] == 12500.0
        assert state_after["open_positions_count"] == 0


# ── Test 6: TradeJournal Multi-Day Query Isolation ─────────────────────────────
def test_trade_journal_multi_day_isolation():
    """Verify get_daily_stats isolates data by date without cross-day leakage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_trades.db"
        journal = TradeJournal(db_path=str(db_path))

        journal.log_daily_summary(
            {
                "date": "2026-10-16",
                "total_trades": 8,
                "wins": 6,
                "losses": 2,
                "win_rate": 75.0,
                "total_pnl": 55.0,
            }
        )
        journal.log_daily_summary(
            {
                "date": "2026-10-17",
                "total_trades": 12,
                "wins": 10,
                "losses": 2,
                "win_rate": 83.3,
                "total_pnl": 95.0,
            }
        )

        stats_16 = journal.get_daily_stats("2026-10-16")
        assert stats_16["total_trades"] == 8
        assert stats_16["total_pnl"] == 55.0

        stats_17 = journal.get_daily_stats("2026-10-17")
        assert stats_17["total_trades"] == 12
        assert stats_17["total_pnl"] == 95.0


# ── Test 7: LogAnalyzer Integrated Trades.log Parsing ──────────────────────────
def test_log_analyzer_with_trades_log():
    """Verify parse_trader_log parses both trader.log and trades.log concurrently."""
    with tempfile.TemporaryDirectory() as tmpdir:
        trader_log = Path(tmpdir) / "trader.log"
        trades_log = Path(tmpdir) / "trades.log"

        trader_log.write_text(
            "2026-10-17 12:00:00 [INFO] Trader: [HEARTBEAT] balance=$10000.00\n",
            encoding="utf-8",
        )
        trades_log.write_text(
            "2026-10-17 12:01:00 [NEW POSITION] BUY 0.02 lots\n"
            "2026-10-17 12:02:00 [NEW POSITION] SELL 0.02 lots\n"
            "2026-10-17 12:05:00 [TRADE CLOSED] BUY TP_HIT +$25.00\n",
            encoding="utf-8",
        )

        summary = parse_trader_log(trader_log, trades_log_path=trades_log)
        assert summary["trades_log"]["exists"] is True
        assert summary["trades_log"]["total_lines"] == 3
        assert summary["trades_log"]["positions_opened"] == 2
        assert summary["trades_log"]["trades_closed"] == 1


# ── Test 8: AlertSystem Timestamp Parsing Resilience ───────────────────────────
def test_alert_system_timestamp_parsing():
    """Verify parse_timestamp_utc handles diverse timestamp representations cleanly."""
    # 1. Unix epoch
    dt1 = parse_timestamp_utc(1700000000.0)
    assert dt1 is not None
    assert dt1.tzinfo == timezone.utc

    # 2. ISO 8601 string with 'Z'
    dt2 = parse_timestamp_utc("2026-10-17T12:00:00Z")
    assert dt2 is not None
    assert dt2.year == 2026 and dt2.month == 10 and dt2.hour == 12

    # 3. Standard space-separated log format
    dt3 = parse_timestamp_utc("2026-10-17 14:30:00")
    assert dt3 is not None
    assert dt3.year == 2026 and dt3.minute == 30

    # 4. Null and empty strings
    assert parse_timestamp_utc(None) is None
    assert parse_timestamp_utc("") is None
    assert parse_timestamp_utc("invalid_string_not_a_time") is None


# ── Test 9: AlertSystem Active Session Detection ───────────────────────────────
def test_alert_system_active_session_detection():
    """Verify is_active_session respects explicit flags, halted state, and active scalping."""
    with tempfile.TemporaryDirectory() as tmpdir:
        status_file = Path(tmpdir) / "live_status.json"
        alert_sys = AlertSystem(status_file=status_file)

        # Halted state overrides session
        assert alert_sys.is_active_session({"trading_halted": True}) is False
        assert alert_sys.is_active_session({"status": "STOPPED"}) is False
        assert alert_sys.is_active_session({"status": "HALTED"}) is False

        # Explicit active session flag
        assert alert_sys.is_active_session({"active_session": True}) is True
        assert alert_sys.is_active_session({"active_session": False}) is False

        # Status ACTIVE_SCALPING
        assert alert_sys.is_active_session({"status": "ACTIVE_SCALPING"}) is True


# ── Test 10: AutoBackup Instance Lock Lifecycle ────────────────────────────────
def test_auto_backup_instance_lock_lifecycle():
    """Verify _acquire_instance_lock creates lock file and _release_instance_lock deletes it."""
    with tempfile.TemporaryDirectory() as tmpdir:
        lock_file = Path(tmpdir) / "backup.lock"

        with patch("auto_backup._LOCK_FILE", str(lock_file)):
            assert not lock_file.exists()

            # First acquisition succeeds
            owned = auto_backup._acquire_instance_lock()
            assert owned is True
            assert lock_file.exists()

            # Release lock
            auto_backup._release_instance_lock()
            assert not lock_file.exists()
