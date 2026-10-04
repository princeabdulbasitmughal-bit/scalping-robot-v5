"""
trade_journal.py - SQLite Trade Journal for Gold Scalping Robot
Stores all trades and daily summaries in a local SQLite database.
"""
import sqlite3
import os
import logging
from datetime import datetime, date

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trades.db')


class TradeJournal:
    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH
        self._init_db()

    def _get_conn(self):
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception as e:
            logger.error("TradeJournal: DB connect error: %s", e)
            return None

    def _init_db(self):
        try:
            conn = self._get_conn()
            if not conn:
                return
            with conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS trades (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT,
                        symbol TEXT,
                        direction TEXT,
                        entry_price REAL,
                        exit_price REAL,
                        lot_size REAL,
                        sl_price REAL,
                        tp_price REAL,
                        pnl REAL,
                        exit_reason TEXT,
                        duration_sec INTEGER,
                        signal_tier INTEGER,
                        spread_pips REAL
                    )
                ''')
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS daily_summary (
                        date TEXT PRIMARY KEY,
                        total_trades INTEGER,
                        wins INTEGER,
                        losses INTEGER,
                        win_rate REAL,
                        total_pnl REAL,
                        max_drawdown REAL,
                        best_trade REAL,
                        worst_trade REAL
                    )
                ''')
            conn.close()
            logger.info("TradeJournal: DB initialized at %s", self.db_path)
        except Exception as e:
            logger.error("TradeJournal: Init error: %s", e)

    def log_trade(self, trade_dict):
        """Insert a trade record into the trades table."""
        try:
            conn = self._get_conn()
            if not conn:
                return False
            with conn:
                conn.execute('''
                    INSERT INTO trades
                    (timestamp, symbol, direction, entry_price, exit_price,
                     lot_size, sl_price, tp_price, pnl, exit_reason,
                     duration_sec, signal_tier, spread_pips)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    trade_dict.get('timestamp', datetime.utcnow().isoformat()),
                    trade_dict.get('symbol', 'XAUUSD'),
                    trade_dict.get('direction', ''),
                    trade_dict.get('entry_price', 0.0),
                    trade_dict.get('exit_price', 0.0),
                    trade_dict.get('lot_size', 0.02),
                    trade_dict.get('sl_price', 0.0),
                    trade_dict.get('tp_price', 0.0),
                    trade_dict.get('pnl', 0.0),
                    trade_dict.get('exit_reason', 'UNKNOWN'),
                    trade_dict.get('duration_sec', 0),
                    trade_dict.get('signal_tier', 0),
                    trade_dict.get('spread_pips', 0.0),
                ))
            conn.close()
            logger.info("TradeJournal: Trade logged pnl=%.2f", trade_dict.get('pnl', 0))
            return True
        except Exception as e:
            logger.error("TradeJournal: log_trade error: %s", e)
            return False

    def log_daily_summary(self, summary_dict):
        """Upsert a daily summary record."""
        try:
            conn = self._get_conn()
            if not conn:
                return False
            today = summary_dict.get('date', str(date.today()))
            with conn:
                conn.execute('''
                    INSERT INTO daily_summary
                    (date, total_trades, wins, losses, win_rate,
                     total_pnl, max_drawdown, best_trade, worst_trade)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(date) DO UPDATE SET
                        total_trades=excluded.total_trades,
                        wins=excluded.wins,
                        losses=excluded.losses,
                        win_rate=excluded.win_rate,
                        total_pnl=excluded.total_pnl,
                        max_drawdown=excluded.max_drawdown,
                        best_trade=excluded.best_trade,
                        worst_trade=excluded.worst_trade
                ''', (
                    today,
                    summary_dict.get('total_trades', 0),
                    summary_dict.get('wins', 0),
                    summary_dict.get('losses', 0),
                    summary_dict.get('win_rate', 0.0),
                    summary_dict.get('total_pnl', 0.0),
                    summary_dict.get('max_drawdown', 0.0),
                    summary_dict.get('best_trade', 0.0),
                    summary_dict.get('worst_trade', 0.0),
                ))
            conn.close()
            return True
        except Exception as e:
            logger.error("TradeJournal: log_daily_summary error: %s", e)
            return False

    def get_last_N_trades(self, n=10):
        """Return last N trades as list of dicts."""
        try:
            conn = self._get_conn()
            if not conn:
                return []
            cur = conn.execute(
                'SELECT * FROM trades ORDER BY id DESC LIMIT ?', (n,)
            )
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows
        except Exception as e:
            logger.error("TradeJournal: get_last_N_trades error: %s", e)
            return []

    def get_daily_stats(self, target_date=None):
        """Return stats for a given date (default: today)."""
        try:
            conn = self._get_conn()
            if not conn:
                return {}
            d = target_date or str(date.today())
            cur = conn.execute(
                'SELECT * FROM daily_summary WHERE date=?', (d,)
            )
            row = cur.fetchone()
            conn.close()
            return dict(row) if row else {}
        except Exception as e:
            logger.error("TradeJournal: get_daily_stats error: %s", e)
            return {}

    def get_weekly_performance(self):
        """Aggregated stats over the last 7 days."""
        try:
            conn = self._get_conn()
            if not conn:
                return {}
            cur = conn.execute('''
                SELECT
                    COUNT(*) as days,
                    SUM(total_trades) as total_trades,
                    SUM(wins) as wins,
                    SUM(losses) as losses,
                    SUM(total_pnl) as total_pnl,
                    MIN(worst_trade) as worst_trade,
                    MAX(best_trade) as best_trade
                FROM daily_summary
                WHERE date >= date('now', '-7 days')
            ''')
            row = cur.fetchone()
            conn.close()
            if row:
                d = dict(row)
                total = d.get('total_trades') or 0
                wins = d.get('wins') or 0
                d['win_rate'] = round((wins / total * 100), 1) if total > 0 else 0.0
                return d
            return {}
        except Exception as e:
            logger.error("TradeJournal: get_weekly_performance error: %s", e)
            return {}


# Singleton
_journal = TradeJournal()


def get_journal():
    return _journal
