"""
tests/test_batch111.py
======================
Unit tests for Batch 111:
- alert_system.py (AlertSystem, format_number, parse_timestamp_utc)
- trade_journal.py (TradeJournal)
"""

import json
import os
import sqlite3
from datetime import datetime, timezone, timedelta
import pytest
from alert_system import AlertSystem, format_number, parse_timestamp_utc
from trade_journal import TradeJournal


# =====================================================================
# AlertSystem Tests
# =====================================================================

def test_alert_system_init_defaults(tmp_path):
    status_file = tmp_path / "live_status.json"
    alerts_log = tmp_path / "alerts.log"
    alert_status = tmp_path / "alert_status.json"

    sys = AlertSystem(
        status_file=status_file,
        alerts_log_file=alerts_log,
        alert_status_file=alert_status,
        check_interval=60,
        rate_limit_minutes=15,
    )
    assert sys.check_interval == 60
    assert sys.rate_limit_seconds == 900
    assert sys.total_alerts_today == 0
    assert sys.is_entry_blocked() is False
    assert sys.is_blocked() is False


def test_alert_system_format_number_and_parse_ts():
    # Number formatting
    assert format_number(150.0, is_currency=True) == "$150"
    assert format_number(175.50, is_currency=True) == "$175.50"
    assert format_number(65.0, is_currency=False) == "65"
    assert format_number(64.5, is_currency=False) == "64.5"

    # Timestamp parsing
    dt_epoch = parse_timestamp_utc(1700000000.0)
    assert dt_epoch is not None
    assert dt_epoch.tzinfo == timezone.utc

    dt_iso = parse_timestamp_utc("2026-10-18T03:30:00Z")
    assert dt_iso is not None
    assert dt_iso.year == 2026


def test_alert_system_evaluate_win_rate_and_daily_loss(tmp_path):
    sys = AlertSystem(status_file=tmp_path / "s.json", alerts_log_file=tmp_path / "a.log", alert_status_file=tmp_path / "st.json")
    data = {
        "win_rate": 50.0,
        "total_trades": 10,
        "daily_loss": 180.0,
        "balance": 10000.0,
        "equity": 10000.0,
        "status": "STOPPED",
    }
    conditions, overall = sys.evaluate_conditions(data)
    types = [c["type"] for c in conditions]

    assert "win_rate_critical" in types
    assert "daily_loss_danger" in types
    assert overall == "CRITICAL"


def test_alert_system_evaluate_stalled_and_too_many_positions(tmp_path):
    sys = AlertSystem(status_file=tmp_path / "s.json", alerts_log_file=tmp_path / "a.log", alert_status_file=tmp_path / "st.json")
    old_time = (datetime.now(timezone.utc) - timedelta(minutes=100)).isoformat()
    data = {
        "active_session": True,
        "last_trade_time": old_time,
        "open_positions_count": 5,
        "win_rate": 80.0,
        "balance": 10000.0,
        "equity": 10000.0,
    }
    conditions, overall = sys.evaluate_conditions(data)
    types = [c["type"] for c in conditions]

    assert "trading_stalled" in types
    assert "too_many_positions" in types
    assert overall == "WARNING"


def test_alert_system_evaluate_balance_and_drawdown(tmp_path):
    sys = AlertSystem(status_file=tmp_path / "s.json", alerts_log_file=tmp_path / "a.log", alert_status_file=tmp_path / "st.json")
    data = {
        "balance": 9750.0,  # below 9800
        "equity": 9300.0,
        "equity_drawdown_pct": 7.0,  # above 5%
        "win_rate": 75.0,
    }
    conditions, overall = sys.evaluate_conditions(data)
    types = [c["type"] for c in conditions]

    assert "balance_critical" in types
    assert "equity_drawdown" in types
    assert overall == "CRITICAL"


def test_alert_system_check_alerts_rate_limiting(tmp_path):
    status_file = tmp_path / "live_status.json"
    alerts_log = tmp_path / "alerts.log"
    alert_status = tmp_path / "alert_status.json"

    sys = AlertSystem(status_file=status_file, alerts_log_file=alerts_log, alert_status_file=alert_status, rate_limit_minutes=15)
    danger_data = {
        "win_rate": 40.0,
        "total_trades": 10,
        "daily_loss": 200.0,
        "balance": 9700.0,
        "equity": 9700.0,
    }

    # First check: triggers alerts
    alerts1 = sys.check_alerts(live_data=danger_data)
    assert len(alerts1) >= 2
    assert sys.total_alerts_today >= 2
    assert sys.is_entry_blocked() is True

    # Immediate second check: rate-limited
    alerts2 = sys.check_alerts(live_data=danger_data)
    assert len(alerts2) == 0  # rate limited

    # Verify alert_status.json written
    assert alert_status.exists()
    with open(alert_status, "r", encoding="utf-8") as f:
        status_json = json.load(f)
    assert status_json["status"] == "CRITICAL"

    sys.reset()
    assert sys.total_alerts_today == 0


# =====================================================================
# TradeJournal Tests
# =====================================================================

def test_trade_journal_init_and_db_creation(tmp_path):
    db_file = str(tmp_path / "test_trades.db")
    journal = TradeJournal(db_path=db_file)
    assert os.path.exists(db_file)
    assert journal.is_entry_blocked() is False
    assert journal.is_blocked() is False

    # Check schema
    conn = sqlite3.connect(db_file)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [r[0] for r in cur.fetchall()]
    conn.close()

    assert "trades" in tables
    assert "daily_summary" in tables


def test_trade_journal_log_trade_and_fetch(tmp_path):
    db_file = str(tmp_path / "test_trades.db")
    journal = TradeJournal(db_path=db_file)

    t1 = {
        "timestamp": "2026-10-18T01:00:00Z",
        "symbol": "XAUUSD",
        "direction": "BUY",
        "entry_price": 2650.0,
        "exit_price": 2655.0,
        "lot_size": 0.05,
        "sl_price": 2640.0,
        "tp_price": 2670.0,
        "pnl": 50.0,
        "exit_reason": "TP_HIT",
        "duration_sec": 120,
        "signal_tier": 1,
        "spread_pips": 1.2,
    }
    t2 = {
        "timestamp": "2026-10-18T02:00:00Z",
        "symbol": "XAUUSD",
        "direction": "SELL",
        "entry_price": 2655.0,
        "exit_price": 2657.0,
        "lot_size": 0.05,
        "pnl": -20.0,
        "exit_reason": "SL_HIT",
    }

    assert journal.log_trade(t1) is True
    assert journal.log_trade(t2) is True

    last_trades = journal.get_last_N_trades(n=5)
    assert len(last_trades) == 2
    assert last_trades[0]["direction"] == "SELL"  # DESC order
    assert last_trades[1]["direction"] == "BUY"
    assert last_trades[1]["pnl"] == 50.0


def test_trade_journal_log_daily_summary_upsert(tmp_path):
    db_file = str(tmp_path / "test_trades.db")
    journal = TradeJournal(db_path=db_file)

    d1 = {
        "date": "2026-10-18",
        "total_trades": 10,
        "wins": 7,
        "losses": 3,
        "win_rate": 70.0,
        "total_pnl": 150.0,
        "max_drawdown": 25.0,
        "best_trade": 50.0,
        "worst_trade": -20.0,
    }
    assert journal.log_daily_summary(d1) is True

    stats = journal.get_daily_stats(target_date="2026-10-18")
    assert stats["total_trades"] == 10
    assert stats["win_rate"] == 70.0
    assert stats["total_pnl"] == 150.0

    # Upsert with new totals for same date
    d1_updated = dict(d1, total_trades=12, wins=9, win_rate=75.0, total_pnl=220.0)
    assert journal.log_daily_summary(d1_updated) is True

    stats_up = journal.get_daily_stats(target_date="2026-10-18")
    assert stats_up["total_trades"] == 12
    assert stats_up["total_pnl"] == 220.0


def test_trade_journal_get_weekly_performance_and_aliases(tmp_path):
    db_file = str(tmp_path / "test_trades.db")
    journal = TradeJournal(db_path=db_file)

    # Insert summary for today
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    journal.log_daily_summary({
        "date": today_str,
        "total_trades": 8,
        "wins": 6,
        "losses": 2,
        "win_rate": 75.0,
        "total_pnl": 120.0,
        "best_trade": 40.0,
        "worst_trade": -15.0,
    })

    weekly = journal.get_weekly_performance()
    assert weekly.get("total_trades") == 8
    assert weekly.get("total_pnl") == 120.0
    assert weekly.get("win_rate") == 75.0

    journal.reset()
    assert journal.is_entry_blocked() is False
