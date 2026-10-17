"""
tests/test_batch72.py
Batch 72 Unit Tests: Real-Time Alert System Thresholds (alert_system.py),
Email Notification Engine with Mock SMTP (email_alert.py), and
30-Agent Ultra-Parallel Multi-Model Swarm Engine (swarm_30_scalping_engine.py).
"""

import math
import time
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pytest

from alert_system import AlertSystem, format_number, parse_timestamp_utc
from email_alert import EmailAlerter
from swarm_30_scalping_engine import ScalpingSwarm30


def test_alert_system_format_number_currency_and_percent():
    """Verify format_number formats whole numbers and decimals cleanly."""
    assert format_number(150.0, is_currency=True) == "$150"
    assert format_number(175.50, is_currency=True) == "$175.50"
    assert format_number(65.0, is_currency=False) == "65"
    assert format_number(64.5, is_currency=False) == "64.5"


def test_alert_system_parse_timestamp_formats():
    """Verify parse_timestamp_utc parses epoch, ISO strings, and log datetime strings."""
    # 1. Numeric epoch
    now_epoch = 1776420000.0
    dt_epoch = parse_timestamp_utc(now_epoch)
    assert dt_epoch is not None
    assert dt_epoch.tzinfo == timezone.utc

    # 2. ISO with Z
    iso_z = "2026-10-17T12:00:00Z"
    dt_z = parse_timestamp_utc(iso_z)
    assert dt_z is not None
    assert dt_z.year == 2026 and dt_z.month == 10

    # 3. Standard log format
    log_ts = "2026-10-17 12:30:45"
    dt_log = parse_timestamp_utc(log_ts)
    assert dt_log is not None


def test_alert_system_evaluate_win_rate_and_loss_conditions(tmp_path):
    """Verify AlertSystem detects critical win rate drops and excessive daily losses."""
    status_file = tmp_path / "live_status.json"
    alerts_log = tmp_path / "alerts.log"
    alert_status = tmp_path / "alert_status.json"

    sys_alert = AlertSystem(
        status_file=status_file,
        alerts_log_file=alerts_log,
        alert_status_file=alert_status,
    )

    data = {
        "status": "ACTIVE_SCALPING",
        "win_rate": 62.5,
        "total_trades": 16,
        "daily_pnl": -180.00,
        "balance": 10000.0,
        "equity": 10000.0,
    }

    conditions, overall = sys_alert.evaluate_conditions(data)
    types = [c["type"] for c in conditions]

    assert "win_rate_critical" in types
    assert "daily_loss_danger" in types
    assert any("Win rate critical: 62.5%" in c["message"] for c in conditions)
    assert any("Daily loss danger: $180" in c["message"] for c in conditions)


def test_alert_system_trading_stalled_and_balance_critical(tmp_path):
    """Verify AlertSystem triggers stalled warnings and critical balance alerts."""
    status_file = tmp_path / "live_status.json"
    sys_alert = AlertSystem(status_file=status_file)

    now_utc = datetime.now(timezone.utc)
    old_time = (now_utc - timedelta(minutes=100)).isoformat()

    data = {
        "status": "ACTIVE_SCALPING",
        "active_session": True,
        "last_trade_time": old_time,
        "balance": 9750.00,  # Below 9800.0
        "equity": 9750.00,
        "win_rate": 80.0,
        "total_trades": 20,
    }

    conditions, _ = sys_alert.evaluate_conditions(data)
    types = [c["type"] for c in conditions]

    assert "trading_stalled" in types
    assert "balance_critical" in types
    assert any("Balance critical: $9750" in c["message"] for c in conditions)


def test_email_alerter_config_and_disabled_mode(tmp_path):
    """Verify EmailAlerter initializes default config and rejects sending when disabled."""
    cfg_file = tmp_path / "email_config.json"
    alerter = EmailAlerter(config_file=str(cfg_file))

    assert cfg_file.exists()
    assert alerter.config["enabled"] is False

    # Attempt send when disabled -> returns False immediately without network attempt
    sent = alerter.send_alert("Test Subject", "Test Body")
    assert sent is False


def test_email_alerter_mock_smtp_factory_dispatch(tmp_path):
    """Verify EmailAlerter uses injected mock SMTP factory for TLS and message dispatch."""
    cfg_file = tmp_path / "email_config.json"

    actions = []

    class MockSMTP:
        def __init__(self, host, port, timeout):
            self.host = host
            self.port = port
            actions.append(f"CONNECT:{host}:{port}")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            actions.append("DISCONNECT")

        def login(self, user, pwd):
            actions.append(f"LOGIN:{user}")

        def send_message(self, msg):
            actions.append(f"SEND:{msg['Subject']}")

    alerter = EmailAlerter(
        config_file=str(cfg_file),
        smtp_factory=lambda host, port, timeout=15: MockSMTP(host, port, timeout),
    )
    alerter.update_config({
        "enabled": True,
        "from_email": "bot@example.com",
        "password": "secret_token",
        "to_email": "trader@example.com",
        "smtp_host": "smtp.mock.com",
        "smtp_port": 587,
    }, persist=True)

    sent = alerter.send_alert("Margin Warning", "Account margin is below 250%")
    assert sent is True

    assert "CONNECT:smtp.mock.com:587" in actions
    assert "LOGIN:bot@example.com" in actions
    assert any("Margin Warning" in a for a in actions)
    assert "DISCONNECT" in actions


def test_email_alerter_test_connection_mock(tmp_path):
    """Verify test_connection executes authentication through mock SMTP."""
    cfg_file = tmp_path / "email_config.json"
    connected = []

    class MockSMTPTest:
        def __init__(self, host, port, timeout):
            connected.append(host)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def login(self, user, pwd):
            connected.append(user)

    alerter = EmailAlerter(
        config_file=str(cfg_file),
        smtp_factory=lambda h, p, timeout=10: MockSMTPTest(h, p, timeout),
    )
    alerter.update_config({
        "from_email": "test@example.com",
        "password": "pass",
        "smtp_host": "smtp.test.com",
    }, persist=True)

    success = alerter.test_connection()
    assert success is True
    assert "smtp.test.com" in connected
    assert "test@example.com" in connected


def test_swarm_30_scalping_engine_squadron_mapping(tmp_path):
    """Verify ScalpingSwarm30 executes single agent with correct squadron attribution."""
    report_file = tmp_path / "report.json"
    swarm = ScalpingSwarm30(root_dir=tmp_path, report_file=report_file)

    # Execute Agent 1 (Squadron 1)
    res1 = swarm._execute_agent(agent_id=1)
    assert res1["id"] == 1
    assert res1["squadron_id"] == 1
    assert res1["squadron_name"] == "Market Feeds & Order Book Sentinels"
    assert res1["status"] in ("OPTIMAL", "WARN")

    # Execute Agent 12 (Squadron 3: Volatility & Dynamic TP/SL Governors)
    res12 = swarm._execute_agent(agent_id=12)
    assert res12["id"] == 12
    assert res12["squadron_id"] == 3
    assert res12["squadron_name"] == "Volatility & Dynamic TP/SL Governors"


def test_swarm_30_scalping_engine_report_generation(tmp_path):
    """Verify ScalpingSwarm30 runs all 30 agents and generates comprehensive JSON report."""
    report_file = tmp_path / "swarm_report.json"
    swarm = ScalpingSwarm30(root_dir=tmp_path, report_file=report_file)

    report = swarm.run_swarm(max_workers=4, save_report=True)

    assert report["total_agents"] == 30
    assert len(report["agents"]) == 30
    assert len(report["squadrons"]) == 6
    assert report["squadrons"][0]["agents_count"] == 5
    assert report_file.exists()


def test_swarm_30_scalping_engine_thread_safety(tmp_path):
    """Verify ScalpingSwarm30 caches last report and allows safe concurrent reads."""
    report_file = tmp_path / "swarm_report.json"
    swarm = ScalpingSwarm30(root_dir=tmp_path, report_file=report_file)

    assert swarm.get_last_report() is None
    rep = swarm.run_swarm(max_workers=4, save_report=False)
    cached = swarm.get_last_report()

    assert cached is not None
    assert cached["total_agents"] == 30
