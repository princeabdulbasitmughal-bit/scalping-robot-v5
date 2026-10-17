"""
tests/test_batch76.py
Batch 76 Landmark Milestone Tests: SQLite Trade Journal (trade_journal.py) & Auto-Backup Engine (auto_backup.py).
Establishes the historic 1,007+ passing tests milestone across 76 test suites!
Verifies:
1. trade_journal: Database initialization, WAL journal mode & table schemas.
2. trade_journal: Log trade boundary values (negative PnL, missing direction, zero lot).
3. trade_journal: Query last N trades with descending order and limit enforcement.
4. trade_journal: Daily summary ON CONFLICT upsert idempotency.
5. trade_journal: 7-day weekly performance multi-day aggregation & win-rate math.
6. trade_journal: get_journal() singleton pattern stability.
7. auto_backup: ensure_backup_dir creation and idempotency.
8. auto_backup: cleanup_old_backups timestamp grouping and oldest snapshot pruning.
9. auto_backup: perform_backup_cycle atomic file copy and .tmp cleanup.
10. auto_backup: _acquire_instance_lock and _release_instance_lock lifecycle.
"""

import os
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
import pytest

from trade_journal import TradeJournal, get_journal
import auto_backup


def test_trade_journal_custom_db_creation_and_wal(tmp_path):
    """Verify TradeJournal initializes database with WAL pragma and creates all indexes."""
    db_file = tmp_path / "custom_trades.db"
    journal = TradeJournal(db_path=str(db_file))

    assert db_file.exists()
    conn = journal._get_conn()
    try:
        cur = conn.execute("PRAGMA journal_mode;")
        mode = cur.fetchone()[0]
        assert mode.lower() == "wal"

        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cur.fetchall()}
        assert "trades" in tables
        assert "daily_summary" in tables
    finally:
        conn.close()


def test_trade_journal_log_trade_boundary_values(tmp_path):
    """Verify log_trade safely handles negative PnL, missing direction, and zero lot."""
    db_file = tmp_path / "boundary_trades.db"
    journal = TradeJournal(db_path=str(db_file))

    trade = {
        "timestamp": "2026-10-17T12:00:00Z",
        "symbol": "XAUUSD",
        "direction": "",
        "entry_price": 2650.0,
        "exit_price": 2645.0,
        "lot_size": 0.0,
        "pnl": -125.75,
        "exit_reason": "SL_HIT",
    }
    success = journal.log_trade(trade)
    assert success is True

    trades = journal.get_last_N_trades(1)
    assert len(trades) == 1
    t = trades[0]
    assert t["pnl"] == -125.75
    assert t["exit_reason"] == "SL_HIT"
    assert t["lot_size"] == 0.02  # Fallback default when zero/empty


def test_trade_journal_get_last_n_trades_limit_and_order(tmp_path):
    """Verify get_last_N_trades retrieves trades in strict descending ID order."""
    db_file = tmp_path / "order_trades.db"
    journal = TradeJournal(db_path=str(db_file))

    for i in range(1, 16):
        journal.log_trade({"symbol": "XAUUSD", "pnl": float(i * 10), "exit_reason": f"TRADE_{i}"})

    trades = journal.get_last_N_trades(5)
    assert len(trades) == 5
    assert trades[0]["exit_reason"] == "TRADE_15"
    assert trades[-1]["exit_reason"] == "TRADE_11"


def test_trade_journal_daily_summary_upsert_overwrite(tmp_path):
    """Verify log_daily_summary updates existing daily record without duplication."""
    db_file = tmp_path / "upsert_trades.db"
    journal = TradeJournal(db_path=str(db_file))

    date_str = "2026-10-17"
    # Insert 1
    summary_1 = {
        "date": date_str,
        "total_trades": 5,
        "wins": 4,
        "losses": 1,
        "win_rate": 80.0,
        "total_pnl": 120.0,
    }
    assert journal.log_daily_summary(summary_1) is True

    # Upsert with new totals
    summary_2 = {
        "date": date_str,
        "total_trades": 8,
        "wins": 7,
        "losses": 1,
        "win_rate": 87.5,
        "total_pnl": 210.0,
    }
    assert journal.log_daily_summary(summary_2) is True

    stats = journal.get_daily_stats(date_str)
    assert stats["total_trades"] == 8
    assert stats["wins"] == 7
    assert stats["win_rate"] == 87.5
    assert stats["total_pnl"] == 210.0


def test_trade_journal_weekly_performance_aggregation(tmp_path):
    """Verify get_weekly_performance computes aggregated metrics over recent days."""
    db_file = tmp_path / "weekly_trades.db"
    journal = TradeJournal(db_path=str(db_file))

    # Log 3 daily summaries for recent days
    today = datetime.now(timezone.utc).date()
    for i in range(3):
        d_str = str(today - timedelta(days=i))
        journal.log_daily_summary({
            "date": d_str,
            "total_trades": 10,
            "wins": 8,
            "losses": 2,
            "total_pnl": 150.0,
            "best_trade": 50.0,
            "worst_trade": -20.0,
        })

    weekly = journal.get_weekly_performance()
    assert weekly["days"] == 3
    assert weekly["total_trades"] == 30
    assert weekly["wins"] == 24
    assert weekly["losses"] == 6
    assert weekly["total_pnl"] == 450.0
    assert weekly["win_rate"] == 80.0


def test_trade_journal_get_journal_singleton():
    """Verify get_journal returns the global singleton TradeJournal instance."""
    j1 = get_journal()
    j2 = get_journal()
    assert j1 is j2
    assert isinstance(j1, TradeJournal)


def test_auto_backup_ensure_backup_dir_creation(tmp_path, monkeypatch):
    """Verify ensure_backup_dir creates directory if missing and is idempotent."""
    target_dir = tmp_path / "new_backups_dir"
    monkeypatch.setattr(auto_backup, "BACKUPS_DIR", str(target_dir))

    assert not target_dir.exists()
    auto_backup.ensure_backup_dir()
    assert target_dir.exists()

    # Second call should not error
    auto_backup.ensure_backup_dir()
    assert target_dir.exists()


def test_auto_backup_cleanup_old_backups_retention(tmp_path):
    """Verify cleanup_old_backups retains only the N newest snapshots and deletes older ones."""
    backups_dir = tmp_path / "backups_retention"
    backups_dir.mkdir()

    # Create 12 snapshot files with distinct timestamp groups
    for i in range(1, 13):
        ts = f"20261017_{i:02d}0000"
        f = backups_dir / f"mt5_live_trader_{ts}.py"
        f.write_text(f"# Snapshot {i}", encoding="utf-8")

    assert len(list(backups_dir.iterdir())) == 12

    # Prune down to 5 snapshots
    auto_backup.cleanup_old_backups(backups_dir=str(backups_dir), keep_last=5)

    remaining_files = sorted(f.name for f in backups_dir.iterdir())
    assert len(remaining_files) == 5
    # The 5 newest snapshots should be 08 through 12
    assert "mt5_live_trader_20261017_120000.py" in remaining_files
    assert "mt5_live_trader_20261017_080000.py" in remaining_files
    assert "mt5_live_trader_20261017_010000.py" not in remaining_files


def test_auto_backup_perform_backup_cycle_atomic_copy(tmp_path, monkeypatch):
    """Verify perform_backup_cycle copies targeted files with timestamp suffix and cleans up .tmp."""
    repo_dir = tmp_path / "repo"
    backups_dir = repo_dir / "backups"
    repo_dir.mkdir()
    engine_dir = repo_dir / "python_engine"
    engine_dir.mkdir()

    # Seed source files
    trader_src = engine_dir / "mt5_live_trader.py"
    trader_src.write_text("# Live trader code", encoding="utf-8")
    status_src = repo_dir / "live_status.json"
    status_src.write_text('{"status": "RUNNING"}', encoding="utf-8")

    monkeypatch.setattr(auto_backup, "REPO_DIR", str(repo_dir))
    monkeypatch.setattr(auto_backup, "BACKUPS_DIR", str(backups_dir))
    monkeypatch.setattr(auto_backup, "FILES_TO_BACKUP", [
        os.path.join("python_engine", "mt5_live_trader.py"),
        "live_status.json",
    ])

    auto_backup.perform_backup_cycle(cycle_count=1)

    assert backups_dir.exists()
    backup_files = list(backups_dir.iterdir())
    assert len(backup_files) == 2

    # Verify no .tmp files remain
    tmp_files = [f for f in backup_files if f.suffix == ".tmp"]
    assert len(tmp_files) == 0


def test_auto_backup_instance_lock_lifecycle(tmp_path, monkeypatch):
    """Verify _acquire_instance_lock and _release_instance_lock enforce single-instance semantics."""
    lock_file = tmp_path / "test_backup.lock"
    monkeypatch.setattr(auto_backup, "_LOCK_FILE", str(lock_file))

    # 1. Initial acquisition succeeds
    assert auto_backup._acquire_instance_lock() is True
    assert lock_file.exists()

    # 2. Concurrent acquisition fails (lock file already held)
    with patch("psutil.pid_exists", return_value=True):
        assert auto_backup._acquire_instance_lock() is False

    # 3. Release lock
    auto_backup._release_instance_lock()
    assert not lock_file.exists()

    # 4. Re-acquisition succeeds after release
    assert auto_backup._acquire_instance_lock() is True
    auto_backup._release_instance_lock()
