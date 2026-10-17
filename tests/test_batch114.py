import os
import json
import tempfile
import math
from pathlib import Path
from unittest.mock import patch, MagicMock

import performance_monitor
from performance_monitor import calculate_grade, _safe_float, evaluate_and_report
import supervisor
from supervisor import calculate_backoff, check_circuit_breaker, log, is_entry_blocked, is_blocked


def test_performance_monitor_calculate_grade():
    assert calculate_grade(95.0) == "A+"
    assert calculate_grade(90.1) == "A+"
    assert calculate_grade(90.0) == "A"
    assert calculate_grade(86.5) == "A"
    assert calculate_grade(85.0) == "B"
    assert calculate_grade(75.0) == "B"
    assert calculate_grade(74.9) == "C"
    assert calculate_grade(50.0) == "C"
    assert calculate_grade(float("nan")) == "C"
    assert calculate_grade(float("inf")) == "C"
    assert calculate_grade("invalid") == "C"
    assert calculate_grade(None) == "C"


def test_performance_monitor_safe_float():
    assert _safe_float(12.5) == 12.5
    assert _safe_float("42.75") == 42.75
    assert _safe_float(None, 5.0) == 5.0
    assert _safe_float(float("nan"), 0.0) == 0.0
    assert _safe_float(float("inf"), 0.0) == 0.0
    assert _safe_float("abc", 9.9) == 9.9
    # Boolean guard
    assert _safe_float(True, 0.0) == 0.0
    assert _safe_float(False, 0.0) == 0.0


def test_performance_monitor_evaluate_and_report_success():
    with tempfile.TemporaryDirectory() as tmpdir:
        status_file = Path(tmpdir) / "live_status.json"
        report_file = Path(tmpdir) / "performance_report.txt"

        payload = {
            "status": "RUNNING",
            "account_mode": "DEMO",
            "broker_name": "MetaQuotes",
            "account_id": "123456",
            "symbol": "XAUUSD",
            "current_price": 2650.50,
            "balance": 10250.0,
            "equity": 10320.0,
            "margin_free": 9800.0,
            "daily_pnl": 150.0,
            "total_trades": 10,
            "win_rate": 90.0,
            "open_positions": [],
            "latency_metrics": {
                "tick_to_signal_us": 120,
                "signal_to_dispatch_us": 80,
                "order_execution_ms": 45,
            }
        }
        status_file.write_text(json.dumps(payload), encoding="utf-8")

        success = evaluate_and_report(status_file=status_file, report_file=report_file)
        assert success is True
        assert report_file.exists()

        content = report_file.read_text(encoding="utf-8")
        assert "SCALPING ROBOT V5 - PERFORMANCE REPORT" in content
        assert "Performance Grade   : A" in content or "Performance Grade   : A+" in content
        assert "[OK] No active alerts." in content
        assert "Tick to Signal Latency  : 120 us" in content


def test_performance_monitor_alerts_generation():
    with tempfile.TemporaryDirectory() as tmpdir:
        status_file = Path(tmpdir) / "live_status.json"
        report_file = Path(tmpdir) / "performance_report.txt"

        payload = {
            "status": "RUNNING",
            "daily_pnl": -150.0,
            "total_trades": 8,
            "win_rate": 62.5,
            "open_positions": [],
        }
        status_file.write_text(json.dumps(payload), encoding="utf-8")

        success = evaluate_and_report(status_file=status_file, report_file=report_file)
        assert success is True
        content = report_file.read_text(encoding="utf-8")
        assert "ALERT: Win rate below 75%" in content
        assert "ALERT: Daily loss >$100" in content


def test_performance_monitor_missing_or_corrupt_status():
    with tempfile.TemporaryDirectory() as tmpdir:
        status_file = Path(tmpdir) / "non_existent.json"
        report_file = Path(tmpdir) / "report.txt"

        assert evaluate_and_report(status_file=status_file, report_file=report_file) is False

        # Corrupt JSON
        status_file.write_text("CORRUPTED JSON {{{{", encoding="utf-8")
        assert evaluate_and_report(status_file=status_file, report_file=report_file) is False


def test_performance_monitor_is_entry_blocked():
    with tempfile.TemporaryDirectory() as tmpdir:
        status_file = Path(tmpdir) / "live_status.json"

        # Missing file defaults to False
        assert performance_monitor.is_entry_blocked(status_file=status_file) is False
        assert performance_monitor.is_blocked(status_file=status_file) is False

        # Good performance -> False
        status_file.write_text(json.dumps({"daily_pnl": 50.0, "total_trades": 10, "win_rate": 80.0}), encoding="utf-8")
        assert performance_monitor.is_entry_blocked(status_file=status_file) is False

        # Daily loss breached -> True
        status_file.write_text(json.dumps({"daily_pnl": -110.0, "total_trades": 5, "win_rate": 80.0}), encoding="utf-8")
        assert performance_monitor.is_entry_blocked(status_file=status_file) is True

        # Win rate below threshold -> True
        status_file.write_text(json.dumps({"daily_pnl": 10.0, "total_trades": 5, "win_rate": 60.0}), encoding="utf-8")
        assert performance_monitor.is_entry_blocked(status_file=status_file) is True

        # Corrupted status file -> True (fail-closed)
        status_file.write_text("CORRUPT {{{{", encoding="utf-8")
        assert performance_monitor.is_entry_blocked(status_file=status_file) is True


def test_supervisor_calculate_backoff_progression():
    assert calculate_backoff(0) == 0
    assert calculate_backoff(-5) == 0
    assert calculate_backoff(1) == 8
    assert calculate_backoff(2) == 16
    assert calculate_backoff(3) == 32
    assert calculate_backoff(4) == 64
    assert calculate_backoff(5) == 120
    assert calculate_backoff(10) == 120
    # Boolean and invalid input guards
    assert calculate_backoff(True) == 0
    assert calculate_backoff(False) == 0
    assert calculate_backoff("invalid") == 0


def test_supervisor_check_circuit_breaker():
    assert check_circuit_breaker(0) is False
    assert check_circuit_breaker(19) is False
    assert check_circuit_breaker(20) is True
    assert check_circuit_breaker(25) is True
    # Guard against invalid inputs
    assert check_circuit_breaker(True) is False
    assert check_circuit_breaker("20") is False


def test_supervisor_log_writing():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = os.path.join(tmpdir, "supervisor.log")
        log("Process heartbeat ping", log_file=log_file)
        assert os.path.exists(log_file)
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert "[SUP] Process heartbeat ping" in content
        assert "UTC" in content


def test_supervisor_is_entry_blocked_and_aliases():
    with patch("supervisor.get_watchdog_pid", return_value=None):
        assert is_entry_blocked() is True
        assert is_blocked() is True

    with patch("supervisor.get_watchdog_pid", return_value=9999):
        assert is_entry_blocked() is False
        assert is_blocked() is False

    with patch("supervisor.get_watchdog_pid", side_effect=RuntimeError("Process table error")):
        assert is_entry_blocked() is True
        assert is_blocked() is True
