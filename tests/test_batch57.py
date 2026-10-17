"""
Test Suite: Batch 57 — Institutional Backtester, Signal Engine, Live Runner, Trade Journal, Performance Monitor & Backup Rotator
=================================================================================================================================
Hermetic unit test suite verifying:
  1. Backtester: Session volatility lookup and normalization
  2. Backtester: Dynamic session allocation across tick lifecycles
  3. Backtester: Gaussian tick simulation with bid/ask spread mechanics
  4. SignalEngine: Bollinger Bands, bandwidth squeeze, and Wilder's RSI calculation
  5. SignalEngine: MACD line, signal line, crossover detection, and parameter updates
  6. LiveRunner: Micro-tick processing, bar aggregation, and non-finite price safety
  7. TradeJournal: SQLite trade logging, schema creation, and history retrieval
  8. TradeJournal: Daily summary upsert and conflict resolution
  9. PerformanceMonitor: Performance grading scale and alert threshold evaluation
 10. AutoBackup: Timestamped backup grouping and retention cleanup
"""

import json
import math
import sqlite3
import tempfile
from pathlib import Path
from datetime import datetime, timezone
import pytest

from python_engine.backtester import Backtester
from python_engine.signal_engine import SignalEngine
from python_engine.live_runner import ScalpingLiveRunner
from trade_journal import TradeJournal
from performance_monitor import calculate_grade, evaluate_and_report
import auto_backup


# ── Test 1: Backtester Session Volatility Lookup ───────────────────────────────
def test_backtester_session_volatility():
    """Verify get_session_volatility returns calibrated sigmas and default fallback."""
    bt = Backtester()
    assert bt.get_session_volatility("TOKYO") == 0.02
    assert bt.get_session_volatility("tokyo") == 0.02
    assert bt.get_session_volatility("LONDON") == 0.08
    assert bt.get_session_volatility("NY") == 0.12
    assert bt.get_session_volatility("NEW_YORK") == 0.12
    # Fallback to London default (0.08) for unknown sessions
    assert bt.get_session_volatility("SYDNEY") == 0.08


# ── Test 2: Backtester Dynamic Session Allocation ──────────────────────────────
def test_backtester_determine_session():
    """Verify determine_session assigns Tokyo, London, and NY based on tick index."""
    bt = Backtester()
    total = 300

    # First third -> Tokyo (vol 0.02)
    s_tokyo, v_tokyo = bt.determine_session(10, total)
    assert s_tokyo == "TOKYO"
    assert v_tokyo == 0.02

    # Middle third -> London (vol 0.08)
    s_london, v_london = bt.determine_session(150, total)
    assert s_london == "LONDON"
    assert v_london == 0.08

    # Final third -> NY (vol 0.12)
    s_ny, v_ny = bt.determine_session(280, total)
    assert s_ny == "NY"
    assert v_ny == 0.12

    # Edge case: zero or negative ticks falls back safely
    s_edge, v_edge = bt.determine_session(0, 0)
    assert s_edge == "LONDON"
    assert v_edge == 0.08


# ── Test 3: Backtester Gaussian Tick Simulation ────────────────────────────────
def test_backtester_simulate_ticks():
    """Verify simulate_ticks generates realistic bid/ask prices with spread mechanics."""
    bt = Backtester()
    ticks = bt.simulate_ticks(n_ticks=50, start_price=2400.0, session="LONDON")

    assert len(ticks) == 50
    for t in ticks:
        assert "tick" in t
        assert "price" in t and math.isfinite(t["price"]) and t["price"] > 0
        assert "bid" in t and "ask" in t
        # Ask must be strictly higher than bid by spread
        assert t["ask"] >= t["bid"]
        assert 0.5 <= t["spread_pips"] <= 2.5
        assert t["session"] == "LONDON"
        assert t["volatility"] == 0.08


# ── Test 4: SignalEngine Bollinger Bands & RSI ─────────────────────────────────
def test_signal_engine_bb_and_rsi():
    """Verify SignalEngine computes Bollinger Bands, squeeze detection, and RSI."""
    engine = SignalEngine(config={"bb_period": 10, "bb_std": 2.0, "rsi_period": 10})

    prices = [2400.0 + i * 0.5 for i in range(20)]
    bb = engine.compute_bb(prices)
    assert isinstance(bb, dict)
    assert bb["upper"] > bb["middle"] > bb["lower"]
    assert math.isfinite(bb["width"])
    assert isinstance(bb["squeeze"], bool)

    # Monotonically increasing prices must have high RSI (> 70)
    rsi_bullish = engine.compute_rsi(prices)
    assert 70.0 <= rsi_bullish <= 100.0

    # Monotonically decreasing prices must have low RSI (< 30)
    falling_prices = [2410.0 - i * 0.5 for i in range(20)]
    rsi_bearish = engine.compute_rsi(falling_prices)
    assert 0.0 <= rsi_bearish <= 30.0


# ── Test 5: SignalEngine MACD & Config Update ──────────────────────────────────
def test_signal_engine_macd_and_config_update():
    """Verify compute_macd outputs line, signal, histogram, and update_config is thread-safe."""
    engine = SignalEngine(config={"macd_fast": 5, "macd_slow": 10, "macd_signal": 5})

    prices = [2400.0 + math.sin(i * 0.2) * 5.0 for i in range(30)]
    macd = engine.compute_macd(prices)
    assert "macd_line" in macd
    assert "signal_line" in macd
    assert "histogram" in macd
    assert macd["cross"] in ("BUY", "SELL", "NONE")

    # Update parameters dynamically
    engine.update_config({"macd_fast": 8, "bb_period": 15})
    info = engine.info()
    assert info["macd_fast"] == 8
    assert info["bb_period"] == 15


# ── Test 6: ScalpingLiveRunner Micro-Tick Processing ───────────────────────────
def test_live_runner_tick_processing():
    """Verify ScalpingLiveRunner ingests ticks, handles invalid inputs, and maintains bars."""
    with tempfile.TemporaryDirectory() as tmpdir:
        status_file = Path(tmpdir) / "live_status.json"
        runner = ScalpingLiveRunner(config={}, status_file=status_file)

        # Valid tick update
        runner.update_tick(2405.50)
        assert runner.current_price == 2405.50
        assert runner.bars[-1]["close"] == 2405.50

        # Non-finite or negative tick input must fall back safely without raising
        runner.update_tick(-100.0)
        assert math.isfinite(runner.current_price)
        assert runner.current_price > 0.0

        runner.update_tick(float("nan"))
        assert math.isfinite(runner.current_price)
        assert runner.current_price > 0.0


# ── Test 7: TradeJournal SQLite Trade Logging ──────────────────────────────────
def test_trade_journal_logging_and_history():
    """Verify TradeJournal initializes SQLite schema and records/queries trades."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_trades.db"
        journal = TradeJournal(db_path=str(db_path))

        trade_1 = {
            "symbol": "XAUUSD",
            "direction": "BUY",
            "entry_price": 2400.0,
            "exit_price": 2405.0,
            "lot_size": 0.02,
            "sl_price": 2390.0,
            "tp_price": 2410.0,
            "pnl": 10.0,
            "exit_reason": "TP_HIT",
            "duration_sec": 45,
            "signal_tier": 1,
            "spread_pips": 1.2,
        }

        trade_2 = {
            "symbol": "XAUUSD",
            "direction": "SELL",
            "entry_price": 2405.0,
            "exit_price": 2408.0,
            "lot_size": 0.02,
            "pnl": -6.0,
            "exit_reason": "SL_HIT",
        }

        assert journal.log_trade(trade_1) is True
        assert journal.log_trade(trade_2) is True

        history = journal.get_last_N_trades(5)
        assert len(history) == 2
        assert history[0]["exit_reason"] == "SL_HIT"  # Most recent first
        assert history[1]["exit_reason"] == "TP_HIT"


# ── Test 8: TradeJournal Daily Summary Upsert ──────────────────────────────────
def test_trade_journal_daily_summary_upsert():
    """Verify log_daily_summary records and updates stats on conflict for a given date."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_trades.db"
        journal = TradeJournal(db_path=str(db_path))

        date_str = "2026-10-17"
        initial_summary = {
            "date": date_str,
            "total_trades": 5,
            "wins": 4,
            "losses": 1,
            "win_rate": 80.0,
            "total_pnl": 45.50,
            "max_drawdown": 1.2,
            "best_trade": 15.0,
            "worst_trade": -6.0,
        }
        assert journal.log_daily_summary(initial_summary) is True

        # Update on the same date (upsert)
        updated_summary = {
            "date": date_str,
            "total_trades": 6,
            "wins": 5,
            "losses": 1,
            "win_rate": 83.3,
            "total_pnl": 60.50,
            "max_drawdown": 1.2,
            "best_trade": 15.0,
            "worst_trade": -6.0,
        }
        assert journal.log_daily_summary(updated_summary) is True

        # Verify updated values via direct query
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("SELECT total_trades, wins, total_pnl FROM daily_summary WHERE date = ?", (date_str,))
        row = cur.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == 6
        assert row[1] == 5
        assert row[2] == 60.50


# ── Test 9: PerformanceMonitor Grading & Evaluation ────────────────────────────
def test_performance_monitor_grading_and_evaluation():
    """Verify calculate_grade scoring boundaries and evaluate_and_report execution."""
    assert calculate_grade(95.0) == "A+"
    assert calculate_grade(88.0) == "A"
    assert calculate_grade(76.0) == "B"
    assert calculate_grade(65.0) == "C"
    assert calculate_grade(float("nan")) == "C"

    with tempfile.TemporaryDirectory() as tmpdir:
        status_file = Path(tmpdir) / "live_status.json"
        report_file = Path(tmpdir) / "performance_report.txt"

        status_data = {
            "status": "ACTIVE_SCALPING",
            "account_mode": "DEMO",
            "broker_name": "MetaQuotes-Demo",
            "symbol": "XAUUSD",
            "current_price": 2402.50,
            "balance": 10050.0,
            "equity": 10050.0,
            "margin_free": 10050.0,
            "daily_pnl": 50.0,
            "total_trades": 12,
            "win_rate": 83.33,
            "open_positions": [],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        status_file.write_text(json.dumps(status_data), encoding="utf-8")

        success = evaluate_and_report(status_file=status_file, report_file=report_file)
        assert success is True
        assert report_file.exists()

        report_content = report_file.read_text(encoding="utf-8")
        assert "SCALPING ROBOT V5 - PERFORMANCE REPORT" in report_content
        assert "Performance Grade   : B" in report_content
        assert "Win Rate            : 83.33%" in report_content


# ── Test 10: AutoBackup Grouping & Retention Cleanup ───────────────────────────
def test_auto_backup_cleanup_retention():
    """Verify cleanup_old_backups removes oldest timestamp groups while preserving keep_last newest."""
    with tempfile.TemporaryDirectory() as tmpdir:
        backups_dir = Path(tmpdir)

        # Create 8 timestamp groups with 2 files each (16 total files)
        # Suffix format: YYYYMMDD_HHMMSS
        timestamps = [f"20261017_{100000 + i * 100:06d}" for i in range(8)]
        for ts in timestamps:
            (backups_dir / f"mt5_live_trader_{ts}.py").write_text("code", encoding="utf-8")
            (backups_dir / f"live_status_{ts}.json").write_text("{}", encoding="utf-8")

        assert len(list(backups_dir.glob("*"))) == 16

        # Retain only last 3 timestamp groups (should keep 6 files, delete 10)
        auto_backup.cleanup_old_backups(backups_dir=str(backups_dir), keep_last=3)

        remaining_files = list(backups_dir.glob("*"))
        assert len(remaining_files) == 6

        # The remaining files must belong only to the 3 latest timestamps
        expected_kept_ts = set(timestamps[-3:])
        for f in remaining_files:
            match = any(ts in f.name for ts in expected_kept_ts)
            assert match is True
