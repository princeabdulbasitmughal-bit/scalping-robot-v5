"""
Unit Tests for TradeJournal (trade_journal.py).
Tests SQLite database creation, trade logging, daily summary upserting,
timeframe queries, connection cleanup, and concurrent multi-thread logging.
"""

import os
import tempfile
import threading
from datetime import date
import pytest

from trade_journal import TradeJournal


@pytest.fixture
def temp_journal():
    """Create a TradeJournal instance backed by a temporary file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_trades.db")
        journal = TradeJournal(db_path=db_path)
        yield journal


def test_init_and_table_creation(temp_journal):
    """Verify tables exist and are properly initialized."""
    assert os.path.exists(temp_journal.db_path)
    conn = temp_journal._get_conn()
    try:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cur.fetchall()}
        assert "trades" in tables
        assert "daily_summary" in tables
    finally:
        conn.close()


def test_log_trade_and_fetch(temp_journal):
    """Verify log_trade inserts records and get_last_N_trades retrieves them."""
    trade = {
        "symbol": "XAUUSD",
        "direction": "BUY",
        "entry_price": 2400.50,
        "exit_price": 2405.00,
        "lot_size": 0.05,
        "sl_price": 2395.00,
        "tp_price": 2410.00,
        "pnl": 225.0,
        "exit_reason": "TP_HIT",
        "duration_sec": 45,
        "signal_tier": 1,
        "spread_pips": 1.5,
    }
    success = temp_journal.log_trade(trade)
    assert success is True

    trades = temp_journal.get_last_N_trades(5)
    assert len(trades) == 1
    t = trades[0]
    assert t["symbol"] == "XAUUSD"
    assert t["direction"] == "BUY"
    assert t["pnl"] == 225.0
    assert t["exit_reason"] == "TP_HIT"


def test_log_daily_summary_upsert(temp_journal):
    """Verify log_daily_summary inserts and properly upserts on conflict."""
    today = str(date.today())
    summary_v1 = {
        "date": today,
        "total_trades": 10,
        "wins": 7,
        "losses": 3,
        "win_rate": 70.0,
        "total_pnl": 350.0,
        "max_drawdown": 45.0,
        "best_trade": 120.0,
        "worst_trade": -30.0,
    }
    assert temp_journal.log_daily_summary(summary_v1) is True

    stats = temp_journal.get_daily_stats(today)
    assert stats["total_trades"] == 10
    assert stats["total_pnl"] == 350.0

    # Upsert with new stats
    summary_v2 = {
        "date": today,
        "total_trades": 12,
        "wins": 9,
        "losses": 3,
        "win_rate": 75.0,
        "total_pnl": 480.0,
        "max_drawdown": 45.0,
        "best_trade": 130.0,
        "worst_trade": -30.0,
    }
    assert temp_journal.log_daily_summary(summary_v2) is True

    stats_v2 = temp_journal.get_daily_stats(today)
    assert stats_v2["total_trades"] == 12
    assert stats_v2["total_pnl"] == 480.0
    assert stats_v2["win_rate"] == 75.0


def test_get_weekly_performance(temp_journal):
    """Verify weekly performance calculations with win rate calculation."""
    today = str(date.today())
    summary = {
        "date": today,
        "total_trades": 20,
        "wins": 14,
        "losses": 6,
        "win_rate": 70.0,
        "total_pnl": 500.0,
        "max_drawdown": 50.0,
        "best_trade": 100.0,
        "worst_trade": -40.0,
    }
    temp_journal.log_daily_summary(summary)

    perf = temp_journal.get_weekly_performance()
    assert perf["total_trades"] == 20
    assert perf["wins"] == 14
    assert perf["losses"] == 6
    assert perf["total_pnl"] == 500.0
    assert perf["win_rate"] == 70.0


def test_concurrent_logging(temp_journal):
    """Verify multi-thread concurrent writes do not cause database locks or crashes."""
    errors = []

    def worker(worker_id):
        try:
            for j in range(10):
                trade = {
                    "symbol": "XAUUSD",
                    "direction": "BUY" if j % 2 == 0 else "SELL",
                    "pnl": float(worker_id * 10 + j),
                    "exit_reason": "SCALPED",
                }
                if not temp_journal.log_trade(trade):
                    errors.append(f"Worker {worker_id} failed trade {j}")
        except Exception as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    trades = temp_journal.get_last_N_trades(100)
    assert len(trades) == 50
