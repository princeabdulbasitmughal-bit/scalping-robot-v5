"""
tests/test_batch112.py
======================
Unit tests for Batch 112:
- auto_backup.py (cleanup_old_backups, ensure_backup_dir, _acquire_instance_lock, _release_instance_lock)
- log_analyzer.py (parse_trader_log, print_summary)
"""

import os
import io
import sys
from pathlib import Path
import pytest
import auto_backup
import log_analyzer


# =====================================================================
# auto_backup Tests
# =====================================================================

def test_auto_backup_ensure_backup_dir(tmp_path, monkeypatch):
    test_backups_dir = str(tmp_path / "custom_backups")
    monkeypatch.setattr(auto_backup, "BACKUPS_DIR", test_backups_dir)

    assert not os.path.exists(test_backups_dir)
    auto_backup.ensure_backup_dir()
    assert os.path.exists(test_backups_dir)


def test_auto_backup_cleanup_old_backups(tmp_path):
    backups_dir = str(tmp_path / "backups")
    os.makedirs(backups_dir, exist_ok=True)

    # Create 15 fake timestamped backups
    for i in range(15):
        ts = f"20261018_{100000 + i:06d}"
        file_path = os.path.join(backups_dir, f"live_status_{ts}.json")
        with open(file_path, "w") as f:
            f.write(f'{{"backup": {i}}}')

    # Retain only last 10
    auto_backup.cleanup_old_backups(backups_dir=backups_dir, keep_last=10)

    remaining_files = os.listdir(backups_dir)
    assert len(remaining_files) == 10
    # Oldest files (indices 0-4) should be deleted, newest (indices 5-14) kept
    assert "live_status_20261018_100000.json" not in remaining_files
    assert "live_status_20261018_100014.json" in remaining_files


def test_auto_backup_single_instance_lock(tmp_path, monkeypatch):
    lock_file = str(tmp_path / "test_backup.lock")
    monkeypatch.setattr(auto_backup, "_LOCK_FILE", lock_file)

    # First acquire succeeds
    assert auto_backup._acquire_instance_lock() is True
    assert os.path.exists(lock_file)

    # Release lock
    auto_backup._release_instance_lock()
    assert not os.path.exists(lock_file)


def test_auto_backup_perform_backup_cycle(tmp_path, monkeypatch):
    repo_dir = str(tmp_path / "repo")
    backups_dir = os.path.join(repo_dir, "backups")
    os.makedirs(repo_dir, exist_ok=True)

    # Create dummy files to backup
    live_status = os.path.join(repo_dir, "live_status.json")
    with open(live_status, "w") as f:
        f.write('{"status": "OK"}')

    monkeypatch.setattr(auto_backup, "REPO_DIR", repo_dir)
    monkeypatch.setattr(auto_backup, "BACKUPS_DIR", backups_dir)
    monkeypatch.setattr(auto_backup, "FILES_TO_BACKUP", ["live_status.json"])

    auto_backup.perform_backup_cycle(cycle_count=1)

    assert os.path.exists(backups_dir)
    backup_files = os.listdir(backups_dir)
    assert len(backup_files) == 1
    assert backup_files[0].startswith("live_status_")


def test_auto_backup_risk_aliases():
    assert auto_backup.is_entry_blocked() is False
    assert auto_backup.is_blocked() is False
    auto_backup.reset()


# =====================================================================
# log_analyzer Tests
# =====================================================================

def test_log_analyzer_parse_empty_or_missing_log(tmp_path):
    missing_log = tmp_path / "non_existent.log"
    with pytest.raises(FileNotFoundError):
        log_analyzer.parse_trader_log(missing_log)

    empty_log = tmp_path / "empty.log"
    empty_log.write_text("", encoding="utf-8")
    summary = log_analyzer.parse_trader_log(empty_log)

    assert summary["total_lines_analyzed"] == 0
    assert summary["counts"]["HEARTBEAT"] == 0
    assert summary["counts"]["SIGNAL"] == 0
    assert summary["counts"]["TRADE"] == 0


def test_log_analyzer_parse_heartbeat_and_balances(tmp_path):
    log_file = tmp_path / "trader.log"
    lines = [
        "2026-10-18 01:00:00,000 [INFO] Trader: [HEARTBEAT] balance=$10,000.00 signal=HOLD",
        "2026-10-18 01:01:00,000 [INFO] Trader: [HEARTBEAT] balance=$10,150.50 signal=BUY",
        "2026-10-18 01:02:00,000 [INFO] Trader: [HEARTBEAT] balance=$9,950.00 signal=SELL",
    ]
    log_file.write_text("\n".join(lines), encoding="utf-8")

    summary = log_analyzer.parse_trader_log(log_file)
    assert summary["heartbeat_lines"] == 3
    assert len(summary["balances"]) == 3
    assert summary["max_balance"] == 10150.50
    assert summary["min_balance"] == 9950.00
    assert summary["balance_range"] == 200.50
    assert summary["heartbeat_signals"]["BUY"] == 1
    assert summary["heartbeat_signals"]["SELL"] == 1
    assert summary["heartbeat_signals"]["HOLD"] == 1


def test_log_analyzer_parse_signals_and_trades(tmp_path):
    log_file = tmp_path / "trader.log"
    lines = [
        "2026-10-18 02:00:00,000 [INFO] SignalEngine: [SIGNAL FIRED] -> BUY score=75",
        "2026-10-18 02:00:01,000 [INFO] OrderManager: [NEW POSITION - LIVE] BUY 0.05 lot @ 2650.0",
        "2026-10-18 02:05:00,000 [INFO] OrderManager: [TRADE CLOSED] BUY | TP_HIT | PnL: $+120.00 | Balance: $10,120.00",
        "2026-10-18 02:05:01,000 [INFO] RiskManager: [RISK] TRADE WIN +$120.00",
    ]
    log_file.write_text("\n".join(lines), encoding="utf-8")

    summary = log_analyzer.parse_trader_log(log_file)
    assert summary["signal_lines"] >= 1
    assert summary["trade_lines"] >= 2
    assert summary["trade_breakdown"]["new_positions"] == 1
    assert summary["trade_breakdown"]["trades_closed"] == 1
    assert summary["trade_breakdown"]["risk_wins_recorded"] == 1
    assert len(summary["trade_breakdown"]["closed_trades_pnl"]) == 1
    assert summary["trade_breakdown"]["closed_trades_pnl"][0]["pnl"] == 120.00


def test_log_analyzer_parse_errors_and_warnings(tmp_path):
    log_file = tmp_path / "trader.log"
    lines = [
        "2026-10-18 03:00:00,000 [ERROR] Network: Connection reset by peer WinError 10054",
        "2026-10-18 03:00:01,000 [WARNING] SpreadMonitor: High spread 3.8 pips exceeds session max",
        "2026-10-18 03:00:02,000 [CRITICAL] Guard: Emergency circuit breaker tripped",
    ]
    log_file.write_text("\n".join(lines), encoding="utf-8")

    summary = log_analyzer.parse_trader_log(log_file)
    assert summary["error_lines"] == 1
    assert summary["warning_lines"] == 1
    assert summary["counts"]["CRITICAL"] == 1


def test_log_analyzer_print_summary_and_aliases(tmp_path, capsys):
    log_file = tmp_path / "trader.log"
    log_file.write_text("2026-10-18 04:00:00,000 [INFO] Trader: [HEARTBEAT] balance=$10,000.00 signal=HOLD\n", encoding="utf-8")

    summary = log_analyzer.parse_trader_log(log_file)
    log_analyzer.print_summary(summary)

    captured = capsys.readouterr()
    assert "SCALPING ROBOT V5 PRO - LOG ANALYSIS & PERFORMANCE REPORT" in captured.out
    assert "HEARTBEAT lines:    1" in captured.out

    assert log_analyzer.is_entry_blocked() is False
    assert log_analyzer.is_blocked() is False
    log_analyzer.reset()
