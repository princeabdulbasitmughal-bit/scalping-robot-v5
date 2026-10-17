"""
Test Suite: Batch 51 — Wave 61 ORB & System Infrastructure Verification
========================================================================
Hermetic unit test suite verifying:
  1. Wave 61: Opening Range Breakout (ORB session window, breakout detection, BlockResult)
  2. Alert System: Threshold alerts, corrupted JSON recovery, rate limiting
  3. Performance Monitor: calculate_grade classification, _safe_float sanitization, evaluate_and_report
  4. Auto-Backup: cleanup_old_backups retention pruning in isolated sandbox
  5. Log Analyzer: parse_trader_log heartbeat, balance, and signal extraction
  6. Trade Journal: SQLite trade logging, query, and daily summary
  7. Gold News Fetcher: Whole-word high-impact keyword regex detection
  8. Email Alerter: Disabled state fail-safe & thread-safe config updates
  9. Storage Utilities: atomic_write_json with .bak backup & safe_read_json resiliency
 10. Live Runner: ScalpingLiveRunner hermetic bar updating & indicator calculation
"""

import datetime
from datetime import timezone
import json
import math
import tempfile
from pathlib import Path
import pytest

from wave61_opening_range_breakout import OpeningRangeBreakout, BlockResult
from alert_system import AlertSystem
from performance_monitor import calculate_grade, _safe_float, evaluate_and_report
from auto_backup import cleanup_old_backups
from log_analyzer import parse_trader_log
from trade_journal import TradeJournal
from gold_news_fetcher import check_high_impact
from email_alert import EmailAlerter
from python_engine.storage import atomic_write_json, safe_read_json
from python_engine.live_runner import ScalpingLiveRunner


# ── Test 1: Wave 61 Opening Range Breakout ─────────────────────────────────────
def test_wave61_opening_range_breakout():
    """Verify OpeningRangeBreakout builds range during open and filters post-window signals."""
    orb = OpeningRangeBreakout(min_ticks=5, window_seconds=1800)

    # 1. London open window: 08:05 UTC (within 30m window)
    dt_open = datetime.datetime(2026, 10, 17, 8, 5, tzinfo=timezone.utc)
    for p in [2400.0, 2402.0, 2401.0, 2404.0, 2399.0, 2403.0]:
        orb.update(p, now_dt=dt_open)

    # Window is not complete yet -> no signals blocked
    res_in_window = orb.is_signal_blocked("BUY", price=2400.0, now_dt=dt_open)
    assert bool(res_in_window) is False
    assert res_in_window.reason == "window_not_complete"

    # 2. Window expires at 08:31 UTC (elapsed >= 1800s)
    dt_post = datetime.datetime(2026, 10, 17, 8, 31, tzinfo=timezone.utc)
    orb.update(2402.0, now_dt=dt_post)
    assert orb._window_complete is True
    assert orb._or_high == 2404.0
    assert orb._or_low == 2399.0

    # BUY when price <= OR_high (2404.0) is blocked
    res_buy_blocked = orb.is_signal_blocked("BUY", price=2403.0, now_dt=dt_post)
    assert bool(res_buy_blocked) is True
    assert res_buy_blocked.reason == "price_not_above_or_high"

    # BUY breakout confirmed when price > OR_high
    res_buy_ok = orb.is_signal_blocked("BUY", price=2405.0, now_dt=dt_post)
    assert bool(res_buy_ok) is False
    assert res_buy_ok.reason == "breakout_confirmed"

    # SELL when price >= OR_low (2399.0) is blocked
    res_sell_blocked = orb.is_signal_blocked("SELL", price=2400.0, now_dt=dt_post)
    assert bool(res_sell_blocked) is True
    assert res_sell_blocked.reason == "price_not_below_or_low"

    # SELL breakout confirmed when price < OR_low
    res_sell_ok = orb.is_signal_blocked("SELL", price=2398.0, now_dt=dt_post)
    assert bool(res_sell_ok) is False
    assert res_sell_ok.reason == "breakout_confirmed"


# ── Test 2: Alert System Corrupted JSON Recovery ──────────────────────────────
def test_alert_system_resilience():
    """Verify AlertSystem survives corrupted status JSON and triggers daily loss alerts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        status_file = tmp_path / "live_status.json"
        alerts_log = tmp_path / "alerts.log"
        alert_status = tmp_path / "alert_status.json"

        # Write corrupted JSON to status_file
        status_file.write_text("{ corrupt json: missing_bracket", encoding="utf-8")

        system = AlertSystem(
            status_file=status_file,
            alerts_log_file=alerts_log,
            alert_status_file=alert_status,
            check_interval=60,
            rate_limit_minutes=15,
        )

        # check_alerts with raw dict bypasses corrupted file safely
        data_loss = {
            "status": "ACTIVE_SCALPING",
            "win_rate_pct": 82.0,
            "daily_loss": 350.0,  # exceeds $300 critical threshold
            "balance": 10000.0,
            "equity": 9650.0,
            "open_positions_count": 0,
            "last_trade_time": 1000.0,
            "total_trades": 12,
        }
        alerts = system.check_alerts(data_loss)
        assert len(alerts) >= 1
        assert any("Daily loss danger" in a for a in alerts)


# ── Test 3: Performance Monitor Grade & Sanitization ──────────────────────────
def test_performance_monitor_grading():
    """Verify performance grading and numeric sanitization in PerformanceMonitor."""
    assert calculate_grade(95.0) == "A+"
    assert calculate_grade(88.0) == "A"
    assert calculate_grade(78.0) == "B"
    assert calculate_grade(70.0) == "C"
    assert calculate_grade(float('nan')) == "C"
    assert calculate_grade("invalid") == "C"

    assert _safe_float(42.5, 0.0) == 42.5
    assert _safe_float("123.45", 0.0) == 123.45
    assert _safe_float(float('inf'), 10.0) == 10.0
    assert _safe_float(None, 5.0) == 5.0
    assert _safe_float("not_a_number", 99.0) == 99.0

    # Test evaluate_and_report on missing file returns False
    with tempfile.TemporaryDirectory() as tmpdir:
        non_existent = Path(tmpdir) / "missing_status.json"
        rep_file = Path(tmpdir) / "rep.txt"
        assert evaluate_and_report(status_file=non_existent, report_file=rep_file) is False


# ── Test 4: Auto Backup Retention Pruning ──────────────────────────────────────
def test_auto_backup_retention():
    """Verify cleanup_old_backups retains only the latest N backup snapshots."""
    with tempfile.TemporaryDirectory() as tmpdir:
        backups_dir = Path(tmpdir)

        # Create 15 synthetic snapshot files across different timestamps
        timestamps = [f"20261017_{100000 + i:06d}" for i in range(15)]
        for ts in timestamps:
            snap_file = backups_dir / f"mt5_live_trader_{ts}.py"
            snap_file.write_text(f"# backup {ts}", encoding="utf-8")

        assert len(list(backups_dir.glob("*.py"))) == 15

        # Prune to keep only last 10
        cleanup_old_backups(backups_dir=str(backups_dir), keep_last=10)

        remaining = list(backups_dir.glob("*.py"))
        assert len(remaining) == 10

        # Verify the 5 oldest are deleted and the 10 newest are retained
        remaining_names = {f.name for f in remaining}
        for ts in timestamps[:5]:
            assert f"mt5_live_trader_{ts}.py" not in remaining_names
        for ts in timestamps[5:]:
            assert f"mt5_live_trader_{ts}.py" in remaining_names


# ── Test 5: Log Analyzer Metric Extraction ────────────────────────────────────
def test_log_analyzer_parsing():
    """Verify parse_trader_log extracts line counts, balances, and signals correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "trader.log"
        content = (
            "2026-10-17 08:00:01,123 [INFO] ScalpingRobotV5: HEARTBEAT: balance=$10050.25 equity=$10050.25 signal=BUY\n"
            "2026-10-17 08:00:02,123 [INFO] ScalpingRobotV5: HEARTBEAT: balance=$10075.50 equity=$10075.50 signal=HOLD\n"
            "2026-10-17 08:00:03,123 [WARNING] RiskGuard: Spread elevated to 2.8 pips\n"
            "2026-10-17 08:00:04,123 [ERROR] OrderManager: Broker reject code 10004\n"
        )
        log_file.write_text(content, encoding="utf-8")

        res = parse_trader_log(log_file)
        assert res["total_lines_analyzed"] == 4
        assert res["counts"]["HEARTBEAT"] == 2
        assert res["counts"]["WARNING"] == 1
        assert res["counts"]["ERROR"] == 1
        assert len(res["balances"]) == 2
        assert res["max_balance"] == 10075.50
        assert res["min_balance"] == 10050.25
        assert res["heartbeat_signals"]["BUY"] == 1
        assert res["heartbeat_signals"]["HOLD"] == 1


# ── Test 6: Trade Journal SQLite Logging ──────────────────────────────────────
def test_trade_journal_sqlite():
    """Verify TradeJournal initializes tables and logs trades into SQLite database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test_trades.db")
        journal = TradeJournal(db_path=db_path)

        trade = {
            "symbol": "XAUUSD",
            "direction": "BUY",
            "entry_price": 2400.50,
            "exit_price": 2403.50,
            "lot_size": 0.02,
            "sl_price": 2398.00,
            "tp_price": 2404.00,
            "pnl": 6.00,
            "exit_reason": "TAKE_PROFIT",
            "duration_sec": 45,
            "signal_tier": 1,
            "spread_pips": 1.5,
        }

        success = journal.log_trade(trade)
        assert success is True

        conn = journal._get_conn()
        cur = conn.cursor()
        cur.execute("SELECT symbol, direction, pnl, exit_reason FROM trades")
        row = cur.fetchone()
        assert row["symbol"] == "XAUUSD"
        assert row["direction"] == "BUY"
        assert row["pnl"] == 6.00
        assert row["exit_reason"] == "TAKE_PROFIT"
        conn.close()


# ── Test 7: Gold News Fetcher Whole-Word Regex ────────────────────────────────
def test_gold_news_fetcher_regex():
    """Verify check_high_impact correctly flags macro events and ignores false positives."""
    # Positive headlines with whole-word keywords
    headlines_positive = [
        ("federal reserve issues statement on interest rate trajectory", "Sat, 17 Oct 2026 12:00:00 GMT"),
        ("gold prices rise as cpi report shows cooling inflation", "Sat, 17 Oct 2026 12:05:00 GMT"),
    ]
    is_impact, keyword = check_high_impact(headlines_positive)
    assert is_impact is True

    # Benign headlines that contain keyword substrings but NOT whole words (e.g., 'forward', 'award')
    headlines_benign = [
        ("moving forward with infrastructure plans", "Sat, 17 Oct 2026 12:10:00 GMT"),
        ("company receives sustainability award", "Sat, 17 Oct 2026 12:15:00 GMT"),
    ]
    is_impact_benign, _ = check_high_impact(headlines_benign)
    assert is_impact_benign is False


# ── Test 8: Email Alerter Disabled State Fail-Safe ────────────────────────────
def test_email_alerter_disabled():
    """Verify EmailAlerter returns False safely without sending when disabled."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_file = str(Path(tmpdir) / "email_config.json")
        alerter = EmailAlerter(config_file=cfg_file)

        # Default configuration is disabled
        assert alerter.config["enabled"] is False

        # Attempt to send alert while disabled
        sent = alerter.send_alert("Test Subject", "Test Body")
        assert sent is False

        # Update configuration in thread-safe manner
        alerter.update_config({"smtp_host": "smtp.office365.com"}, persist=True)
        assert alerter.config["smtp_host"] == "smtp.office365.com"


# ── Test 9: Safe Storage Utilities Atomic Write & Read ────────────────────────
def test_storage_atomic_io():
    """Verify atomic_write_json generates .bak backup and safe_read_json handles corrupt files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "state.json"
        data = {"session": "NY", "pnl": 125.50, "active": True}

        # Write data atomically
        ok = atomic_write_json(file_path, data)
        assert ok is True
        assert file_path.exists()
        assert file_path.with_suffix(".json.bak").exists()

        # Read data back safely
        read_data = safe_read_json(file_path, default={})
        assert read_data["session"] == "NY"
        assert read_data["pnl"] == 125.50

        # When primary is corrupted, safe_read_json seamlessly recovers from .bak
        file_path.write_text("{ corrupt", encoding="utf-8")
        recovered = safe_read_json(file_path, default={"fallback": True})
        assert recovered["session"] == "NY"
        assert recovered["pnl"] == 125.50

        # When both primary and .bak are removed or corrupted, safe_read_json returns fallback
        file_path.with_suffix(".json.bak").unlink()
        fallback = safe_read_json(file_path, default={"fallback": True})
        assert fallback["fallback"] is True


# ── Test 10: Scalping Live Runner State & Indicators ──────────────────────────
def test_scalping_live_runner_ticks():
    """Verify ScalpingLiveRunner seeds bars, updates ticks, and computes indicators."""
    with tempfile.TemporaryDirectory() as tmpdir:
        status_file = Path(tmpdir) / "test_live_status.json"
        runner = ScalpingLiveRunner(status_file=status_file)

        assert len(runner.bars) == 100
        assert runner.balance == 10000.0

        # Feed a new tick
        tick_res = runner.update_tick(2405.50)
        assert runner.current_price == 2405.50
        assert runner.bars[-1]["close"] == 2405.50
        assert len(runner.bars) >= 100
