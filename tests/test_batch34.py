"""
Tests for Batch 34 Hardening:
- alert_system.py
- gold_news_fetcher.py
- auto_backup.py
- log_analyzer.py
- email_alert.py
- supervisor.py
- wave58_price_range_filter.py (boundary edge cases)
- wave59_ma_trend_filter.py (BlockResult behavior)
- trade_journal.py (summary upsert)
"""

import math
import os
import time
import tempfile
from pathlib import Path
from datetime import datetime, timezone
import pytest

from alert_system import format_number, parse_timestamp_utc, AlertSystem
from gold_news_fetcher import check_high_impact, write_status, _KW_PATTERNS, NEWS_STATUS_FILE
from auto_backup import cleanup_old_backups
from log_analyzer import parse_trader_log
from email_alert import EmailAlerter
from supervisor import _MAX_BACKOFF_SEC, _MAX_CONSECUTIVE_FAILURES, FLAGS
from wave58_price_range_filter import PriceRangeFilter
from wave59_ma_trend_filter import BlockResult
from trade_journal import TradeJournal


def test_alert_system_format_and_time():
    # Number formatting
    assert format_number(150.0, is_currency=True) == "$150"
    assert format_number(175.50, is_currency=True) == "$175.50"
    assert format_number(65.0, is_currency=False) == "65"
    assert format_number(64.5, is_currency=False) == "64.5"

    # Timestamp parsing
    dt_epoch = parse_timestamp_utc(1700000000)
    assert dt_epoch is not None
    assert dt_epoch.tzinfo == timezone.utc

    dt_iso_z = parse_timestamp_utc("2026-10-19T14:30:00Z")
    assert dt_iso_z is not None
    assert dt_iso_z.year == 2026
    assert dt_iso_z.hour == 14

    dt_standard = parse_timestamp_utc("2026-10-19 14:30:00")
    assert dt_standard is not None
    assert dt_standard.minute == 30

    assert parse_timestamp_utc(None) is None
    assert parse_timestamp_utc("") is None


def test_alert_system_initialization(tmp_path):
    status_file = tmp_path / "live_status.json"
    alerts_log = tmp_path / "alerts.log"
    alert_status = tmp_path / "alert_status.json"

    system = AlertSystem(
        status_file=status_file,
        alerts_log_file=alerts_log,
        alert_status_file=alert_status,
        check_interval=30,
        rate_limit_minutes=15,
    )

    assert system.check_interval == 30
    assert system.rate_limit_seconds == 900
    assert system.total_alerts_today == 0

    # Active session evaluation
    assert system.is_active_session({"active_session": True}) is True
    assert system.is_active_session({"active_session": False}) is False


def test_gold_news_fetcher_keywords(tmp_path):
    # Whole-word regex matching prevents false positives
    fed_pattern = next(p for p in _KW_PATTERNS if p.pattern == r"\bfed\b")
    assert fed_pattern.search("The Fed announced new rates") is not None
    assert fed_pattern.search("The modified system unified tests") is None

    war_pattern = next(p for p in _KW_PATTERNS if p.pattern == r"\bwar\b")
    assert war_pattern.search("Regional war escalation") is not None
    assert war_pattern.search("Winning an award ceremony") is None

    # High impact headline checks
    headlines = [
        ("stock market opens higher", "2026-10-19"),
        ("fomc rate cut expectations rise", "2026-10-19"),
    ]
    is_impact, matched_title = check_high_impact(headlines)
    assert is_impact is True
    assert "fomc" in matched_title

    normal_headlines = [
        ("tech stocks rebound", "2026-10-19"),
        ("company reports quarterly earnings", "2026-10-19"),
    ]
    is_impact_normal, _ = check_high_impact(normal_headlines)
    assert is_impact_normal is False


def test_auto_backup_cleanup(tmp_path):
    backups_dir = str(tmp_path / "backups")
    os.makedirs(backups_dir, exist_ok=True)

    # Create 6 snapshot files across timestamps
    for i in range(6):
        ts = f"20261019_10000{i}"
        file_path = os.path.join(backups_dir, f"mt5_live_trader_{ts}.py")
        with open(file_path, "w") as f:
            f.write(f"backup {i}")

    # Retention keep_last=3 should purge oldest 3 files
    cleanup_old_backups(backups_dir=backups_dir, keep_last=3)
    remaining = os.listdir(backups_dir)
    assert len(remaining) == 3
    assert "mt5_live_trader_20261019_100005.py" in remaining
    assert "mt5_live_trader_20261019_100000.py" not in remaining


def test_log_analyzer_parsing(tmp_path):
    log_file = tmp_path / "trader.log"
    content = (
        "2026-10-19 14:00:00,123 [INFO] ScalpingRobotV5: HEARTBEAT balance=$10,000.00 equity=$10,000.00 signal=HOLD\n"
        "2026-10-19 14:00:10,123 [INFO] ScalpingRobotV5: [SIGNAL FIRED] -> BUY confidence=0.85\n"
        "2026-10-19 14:00:15,123 [INFO] ScalpingRobotV5: [NEW POSITION - SIM] ticket=12345 BUY 0.02 at 2000.0\n"
        "2026-10-19 14:05:00,123 [INFO] ScalpingRobotV5: [TRADE CLOSED] BUY | TP | PnL: +$15.00 | Balance: $10,015.00\n"
        "2026-10-19 14:06:00,123 [WARNING] ScalpingRobotV5: High spread detected 2.8 pips\n"
    )
    log_file.write_text(content, encoding="utf-8")

    result = parse_trader_log(log_file)
    assert result["total_lines_analyzed"] == 5
    assert result["heartbeat_lines"] == 1
    assert result["signal_lines"] == 2
    assert result["trade_lines"] == 2
    assert result["warning_lines"] == 1
    assert result["max_balance"] == 10000.0


def test_email_alert_rlock():
    alerter = EmailAlerter()
    # Reentrant lock verification
    with alerter._lock:
        with alerter._lock:
            # When disabled, send_alert safely returns False without network attempts
            res = alerter.send_alert("Test Subject", "Test Body")
    assert res is False


def test_supervisor_constants():
    assert _MAX_BACKOFF_SEC == 120
    assert _MAX_CONSECUTIVE_FAILURES == 20
    assert FLAGS != 0


def test_wave58_price_range_filter_bounds():
    rf = PriceRangeFilter(min_range_pips=5.0, pip_value=0.1, min_ticks=10)
    rf.reset()
    # Negative and non-finite updates should be safely ignored
    rf.update(-100.0)
    rf.update(float("nan"))
    rf.update(None)
    assert rf._ticks_today == 0
    assert rf.get_range_pips() == 0.0


def test_wave59_ma_trend_filter_block_result_ops():
    res_blocked = BlockResult(True, "test_blocked_reason")
    assert bool(res_blocked) is True
    assert res_blocked[0] is True
    assert res_blocked[1] == "test_blocked_reason"
    b, r = res_blocked
    assert b is True
    assert r == "test_blocked_reason"
    assert "BlockResult(True" in repr(res_blocked)

    res_allowed = BlockResult(False, "test_allowed_reason")
    assert bool(res_allowed) is False
    assert res_allowed[0] is False
    assert res_allowed[1] == "test_allowed_reason"


def test_trade_journal_summary_upsert(tmp_path):
    db_file = str(tmp_path / "journal_summary_test.db")
    journal = TradeJournal(db_path=db_file)

    summary_data = {
        "date": "2026-10-19",
        "total_trades": 10,
        "wins": 8,
        "losses": 2,
        "win_rate": 80.0,
        "total_pnl": 125.50,
        "max_drawdown": 1.2,
        "best_trade": 25.0,
        "worst_trade": -15.0,
    }

    with journal._lock:
        with journal._lock:
            success = journal.log_daily_summary(summary_data)
    assert success is True
