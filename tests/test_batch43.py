"""
tests/test_batch43.py - Comprehensive Unit Tests for Batch 43 Components:
1. email_alert (EmailAlerter): custom config_file, template creation, disabled state handling
2. email_alert (Mock SMTP Dispatch): mocked smtplib factory, alert sending, MIME formatting, connection testing
3. performance_monitor (calculate_grade): grade tier classification (A+, A, B, C) and invalid input resilience
4. performance_monitor (evaluate_and_report): end-to-end report generation from live_status.json
5. performance_monitor (Alert Thresholds): win rate < 75% and daily loss > $100 alert generation
6. watchdog_runner (calculate_backoff): exponential backoff delays with 300s ceiling and input sanitization
7. watchdog_runner (health_check & status_age): live_status.json freshness, ok boolean, and age calculations
8. watchdog_runner (detect_restart_reason): process crash codes, stale status freeze detection, and healthy states
9. python_engine/storage (atomic_write_json & .bak recovery): atomic swap, stale temp cleanup, and .bak corruption fallback
10. python_engine/scalping_engine & backtester (EconomicNewsFilter & Backtester): news blackout windows and session volatility
"""

import os
import json
import time
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from email_alert import EmailAlerter
from performance_monitor import calculate_grade, evaluate_and_report
from watchdog_runner import calculate_backoff, health_check, status_age, detect_restart_reason
from python_engine.storage import atomic_write_json, safe_read_json
from python_engine.scalping_engine import EconomicNewsFilter, ScalpingSignal, MarketRegime
from python_engine.backtester import Backtester


def test_email_alerter_custom_config_and_disabled(tmp_path):
    """Verify EmailAlerter creates template on missing config and safely skips alerts when disabled."""
    cfg_file = tmp_path / "email_config.json"
    alerter = EmailAlerter(config_file=str(cfg_file))

    assert cfg_file.exists()
    assert alerter.config["enabled"] is False

    # When disabled, send_alert returns False immediately without touching SMTP
    assert alerter.send_alert("Test Subject", "Test Body") is False

    # When enabled but missing credentials, returns False
    alerter.update_config({"enabled": True, "from_email": "", "to_email": ""})
    assert alerter.send_alert("Test Subject", "Test Body") is False


def test_email_alerter_mock_smtp_dispatch(tmp_path):
    """Verify EmailAlerter dispatches formatted MIME emails using a mocked SMTP factory."""
    cfg_file = tmp_path / "email_config.json"
    mock_server = MagicMock()
    mock_server.__enter__.return_value = mock_server

    def mock_smtp_factory(host, port, timeout=15):
        return mock_server

    alerter = EmailAlerter(config_file=str(cfg_file), smtp_factory=mock_smtp_factory)
    alerter.update_config({
        "enabled": True,
        "from_email": "bot@test.com",
        "password": "secret_password",
        "to_email": "trader@test.com",
        "smtp_host": "smtp.mock.com",
        "smtp_port": 587,
    }, persist=True)

    # Test send_alert
    ok = alerter.send_alert("Trade Win", "Gold trade closed with profit +$75.00")
    assert ok is True
    mock_server.login.assert_called_once_with("bot@test.com", "secret_password")
    assert mock_server.send_message.called

    sent_msg = mock_server.send_message.call_args[0][0]
    assert sent_msg["From"] == "bot@test.com"
    assert sent_msg["To"] == "trader@test.com"
    assert "[GoldBot] Trade Win" in sent_msg["Subject"]

    # Test test_connection
    conn_ok = alerter.test_connection()
    assert conn_ok is True


def test_performance_monitor_calculate_grade():
    """Verify calculate_grade accurately maps win rate ranges to grades and handles edge cases."""
    # A+: win_rate > 90
    assert calculate_grade(95.0) == "A+"
    assert calculate_grade(90.1) == "A+"

    # A: 85 < win_rate <= 90
    assert calculate_grade(90.0) == "A"
    assert calculate_grade(85.5) == "A"

    # B: 75 <= win_rate <= 85
    assert calculate_grade(85.0) == "B"
    assert calculate_grade(75.0) == "B"

    # C: win_rate < 75
    assert calculate_grade(74.9) == "C"
    assert calculate_grade(50.0) == "C"
    assert calculate_grade(0.0) == "C"

    # Corrupted / invalid input handling
    assert calculate_grade(None) == "C"
    assert calculate_grade("invalid") == "C"
    assert calculate_grade(float("nan")) == "C"
    assert calculate_grade(float("inf")) == "C"


def test_performance_monitor_evaluate_and_report(tmp_path):
    """Verify evaluate_and_report parses live_status.json and generates performance_report.txt."""
    status_file = tmp_path / "live_status.json"
    report_file = tmp_path / "performance_report.txt"

    # Non-existent status file -> returns False
    assert evaluate_and_report(status_file=status_file, report_file=report_file) is False

    # Write realistic status
    status_data = {
        "status": "ACTIVE_SCALPING",
        "account_mode": "REAL",
        "broker_name": "Exness-Pro",
        "account_id": "12345678",
        "symbol": "XAUUSD",
        "current_price": 2412.50,
        "balance": 10500.0,
        "equity": 10550.0,
        "margin_free": 10200.0,
        "daily_pnl": 150.0,
        "total_trades": 12,
        "win_rate": 83.33,
        "open_positions": [
            {"id": 101, "symbol": "XAUUSD", "type": "BUY", "lot_size": 0.05, "entry": 2410.0, "sl": 2405.0, "tp": 2420.0}
        ],
        "latency_metrics": {
            "tick_to_signal_us": 250,
            "signal_to_dispatch_us": 180,
            "order_execution_ms": 15.2,
            "dynamic_slippage_points": 1,
            "ticks_processed": 5000,
        }
    }
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(status_data, f)

    res = evaluate_and_report(status_file=status_file, report_file=report_file)
    assert res is True
    assert report_file.exists()

    report_text = report_file.read_text(encoding="utf-8")
    assert "SCALPING ROBOT V5 - PERFORMANCE REPORT" in report_text
    assert "Performance Grade   : B" in report_text
    assert "Win Rate            : 83.33%" in report_text
    assert "Daily PnL           : $150.00" in report_text
    assert "OPEN POSITIONS (1)" in report_text
    assert "[XAUUSD] BUY  | Lots: 0.05" in report_text
    assert "Order Execution Latency : 15.2 ms" in report_text


def test_performance_monitor_alert_thresholds(tmp_path):
    """Verify evaluate_and_report flags low win rates (< 75%) and heavy daily losses (< -$100)."""
    status_file = tmp_path / "live_status.json"
    report_file = tmp_path / "performance_report.txt"

    danger_status = {
        "status": "ACTIVE_SCALPING",
        "balance": 9800.0,
        "equity": 9750.0,
        "daily_pnl": -125.50,
        "total_trades": 8,
        "win_rate": 62.5,
        "open_positions": [],
    }
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(danger_status, f)

    res = evaluate_and_report(status_file=status_file, report_file=report_file)
    assert res is True

    report_text = report_file.read_text(encoding="utf-8")
    assert "Performance Grade   : C" in report_text
    assert "ALERT: Win rate below 75%" in report_text
    assert "ALERT: Daily loss >$100" in report_text


def test_watchdog_runner_backoff_calculation():
    """Verify calculate_backoff enforces exponential scaling with a 300-second maximum cap."""
    # count -> min(300, 30 * 2^count)
    assert calculate_backoff(0) == 30
    assert calculate_backoff(1) == 60
    assert calculate_backoff(2) == 120
    assert calculate_backoff(3) == 240
    assert calculate_backoff(4) == 300  # 30 * 16 = 480 -> capped at 300
    assert calculate_backoff(10) == 300

    # Negative / malformed inputs default to count=0 -> 30s
    assert calculate_backoff(-5) == 30
    assert calculate_backoff("invalid") == 30
    assert calculate_backoff(None) == 30


def test_watchdog_runner_health_check_and_status_age(tmp_path):
    """Verify watchdog health_check and status_age with missing, fresh, and stale files."""
    status_file = tmp_path / "live_status.json"

    # 1. Missing file -> age is high, health_check is False
    assert status_age(status_file) == 9999.0
    assert health_check(status_file) is False

    # 2. Fresh file with ok=True
    fresh_data = {
        "ok": True,
        "timestamp": time.time() - 10.0,  # 10s old (< 60s)
        "status": "active_scalping"
    }
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(fresh_data, f)

    assert health_check(status_file) is True
    assert status_age(status_file) < 5.0

    # 3. Explicit ok=False -> health check fails
    fresh_data["ok"] = False
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(fresh_data, f)
    assert health_check(status_file) is False

    # 4. Stale timestamp (90 seconds ago > 60s) -> health check fails
    stale_data = {
        "ok": True,
        "timestamp": time.time() - 90.0,
        "status": "active_scalping"
    }
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(stale_data, f)
    assert health_check(status_file) is False


def test_watchdog_runner_detect_restart_reason():
    """Verify detect_restart_reason identifies process crashes, freezes, and normal operation."""
    # 1. Process crashed (poll returns exit code 1)
    mock_crashed = MagicMock()
    mock_crashed.poll.return_value = 1
    reason_crash = detect_restart_reason(mock_crashed, age=10.0)
    assert reason_crash == "CRASH: process exited with code 1"

    # 2. Process alive (poll returns None), but age > 120s -> FREEZE
    mock_alive = MagicMock()
    mock_alive.poll.return_value = None
    reason_freeze = detect_restart_reason(mock_alive, age=150.0)
    assert reason_freeze == "FREEZE: no status update for 120+ seconds"

    # 3. Process alive and status is fresh -> None (no restart needed)
    reason_ok = detect_restart_reason(mock_alive, age=25.0)
    assert reason_ok is None


def test_python_engine_storage_atomic_and_recovery(tmp_path):
    """Verify atomic_write_json creates backups and safe_read_json recovers from corrupted JSON."""
    test_file = tmp_path / "live_state.json"
    bak_file = tmp_path / "live_state.json.bak"

    data = {
        "balance": 10250.0,
        "equity": 10300.0,
        "positions": [{"ticket": 12345, "direction": "BUY", "lot": 0.02}]
    }

    # 1. Atomic write creates primary and .bak
    assert atomic_write_json(test_file, data) is True
    assert test_file.exists()
    assert bak_file.exists()

    # 2. Safe read parses primary correctly
    loaded = safe_read_json(test_file)
    assert loaded == data

    # 3. Corrupt primary file with broken JSON
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("{{{ broken json non-terminating ...")

    # 4. Safe read catches JSONDecodeError and recovers from .bak!
    recovered = safe_read_json(test_file)
    assert recovered == data
    assert recovered["balance"] == 10250.0

    # 5. Non-existent file returns default
    missing_file = tmp_path / "missing.json"
    assert safe_read_json(missing_file, default={"status": "default"}) == {"status": "default"}


def test_python_engine_economic_news_filter_and_backtester():
    """Verify EconomicNewsFilter blackout windows and Backtester session volatility modeling."""
    # 1. EconomicNewsFilter
    news = EconomicNewsFilter(pre_minutes=15, post_minutes=30)
    news.clear_events()

    event_time_str = "2026-10-20 12:30:00"
    news.add_event(event_time=event_time_str, event_name="US CPI Release", currency="USD", impact="HIGH")

    # Event ts: 2026-10-20 12:30:00 UTC
    dt_event = datetime(2026, 10, 20, 12, 30, 0, tzinfo=timezone.utc)

    # 10 minutes before event (12:20 UTC) -> blackout (PRE_EVENT)
    dt_pre = dt_event - timedelta(minutes=10)
    is_blk_pre, ev_pre = news.is_blackout(current_time=dt_pre, currency="USD")
    assert is_blk_pre is True
    assert ev_pre["phase"] == "PRE_EVENT"
    assert ev_pre["event"] == "US CPI Release"

    # 20 minutes after event (12:50 UTC) -> blackout (POST_EVENT)
    dt_post = dt_event + timedelta(minutes=20)
    is_blk_post, ev_post = news.is_blackout(current_time=dt_post, currency="USD")
    assert is_blk_post is True
    assert ev_post["phase"] == "POST_EVENT"

    # 45 minutes after event (13:15 UTC) -> blackout expired
    dt_clear = dt_event + timedelta(minutes=45)
    is_blk_clear, _ = news.is_blackout(current_time=dt_clear, currency="USD")
    assert is_blk_clear is False

    # Currency filter: EUR is not blacked out
    is_blk_eur, _ = news.is_blackout(current_time=dt_pre, currency="EUR")
    assert is_blk_eur is False

    # 2. Backtester session volatility
    bt = Backtester({"symbol": "XAUUSD", "lot_size": 0.02})
    assert bt.get_session_volatility("TOKYO") == 0.02
    assert bt.get_session_volatility("LONDON") == 0.08
    assert bt.get_session_volatility("NY") == 0.12

    # Session determination based on index
    sess_tokyo, vol_tokyo = bt.determine_session(10, 100)
    assert sess_tokyo == "TOKYO"
    assert vol_tokyo == 0.02

    sess_london, vol_london = bt.determine_session(50, 100)
    assert sess_london == "LONDON"
    assert vol_london == 0.08

    sess_ny, vol_ny = bt.determine_session(85, 100)
    assert sess_ny == "NY"
    assert vol_ny == 0.12

    # Simulate realistic ticks
    ticks = bt.simulate_ticks(n_ticks=30, start_price=2400.0)
    assert len(ticks) == 30
    assert all("bid" in t and "ask" in t and "spread_pips" in t for t in ticks)
    assert all(t["ask"] >= t["bid"] for t in ticks)
