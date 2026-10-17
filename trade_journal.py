"""
trade_journal.py - SQLite Trade Journal for Gold Scalping Robot
Stores all trades and daily summaries in a local SQLite database.
"""
import sqlite3
import os
import logging
import threading
from datetime import datetime, date, timezone

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trades.db')


class TradeJournal:
    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH
        self._lock = threading.RLock()
        self._init_db()

    def _get_conn(self):
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=10000;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            return conn
        except Exception as e:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            logger.error("TradeJournal: DB connect error: %s", e)
            return None

    def _init_db(self):
        with self._lock:
            conn = self._get_conn()
            if not conn:
                return
            try:
                with conn:
                    conn.execute("PRAGMA journal_mode=WAL;")
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
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp DESC);")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol_timestamp ON trades(symbol, timestamp DESC);")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_exit_reason ON trades(exit_reason);")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_summary_date ON daily_summary(date DESC);")
                logger.info("TradeJournal: DB initialized at %s", self.db_path)
            except Exception as e:
                logger.error("TradeJournal: Init error: %s", e)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    def log_trade(self, trade_dict):
        """Insert a trade record into the trades table."""
        with self._lock:
            conn = self._get_conn()
            if not conn:
                return False
            try:
                pnl_val = float(trade_dict.get('pnl') or 0.0)
                with conn:
                    conn.execute('''
                        INSERT INTO trades
                        (timestamp, symbol, direction, entry_price, exit_price,
                         lot_size, sl_price, tp_price, pnl, exit_reason,
                         duration_sec, signal_tier, spread_pips)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        trade_dict.get('timestamp', datetime.now(timezone.utc).isoformat()),
                        trade_dict.get('symbol', 'XAUUSD'),
                        trade_dict.get('direction', ''),
                        float(trade_dict.get('entry_price') or 0.0),
                        float(trade_dict.get('exit_price') or 0.0),
                        float(trade_dict.get('lot_size') or 0.02),
                        float(trade_dict.get('sl_price') or 0.0),
                        float(trade_dict.get('tp_price') or 0.0),
                        pnl_val,
                        trade_dict.get('exit_reason', 'UNKNOWN'),
                        int(trade_dict.get('duration_sec') or 0),
                        int(trade_dict.get('signal_tier') or 0),
                        float(trade_dict.get('spread_pips') or 0.0),
                    ))
                logger.info("TradeJournal: Trade logged pnl=%.2f", pnl_val)
                return True
            except Exception as e:
                logger.error("TradeJournal: log_trade error: %s", e)
                return False
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    def log_daily_summary(self, summary_dict):
        """Upsert a daily summary record."""
        with self._lock:
            conn = self._get_conn()
            if not conn:
                return False
            today = summary_dict.get('date') or datetime.now(timezone.utc).strftime('%Y-%m-%d')
            try:
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
                return True
            except Exception as e:
                logger.error("TradeJournal: log_daily_summary error: %s", e)
                return False
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    def get_last_N_trades(self, n=10):
        """Return last N trades as list of dicts."""
        conn = self._get_conn()
        if not conn:
            return []
        try:
            cur = conn.execute(
                'SELECT * FROM trades ORDER BY id DESC LIMIT ?', (n,)
            )
            return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.error("TradeJournal: get_last_N_trades error: %s", e)
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def get_daily_stats(self, target_date=None):
        """Return stats for a given date (default: today)."""
        conn = self._get_conn()
        if not conn:
            return {}
        d = target_date or str(date.today())
        try:
            cur = conn.execute(
                'SELECT * FROM daily_summary WHERE date=?', (d,)
            )
            row = cur.fetchone()
            return dict(row) if row else {}
        except Exception as e:
            logger.error("TradeJournal: get_daily_stats error: %s", e)
            return {}
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def get_weekly_performance(self):
        """Aggregated stats over the last 7 days."""
        conn = self._get_conn()
        if not conn:
            return {}
        try:
            cur = conn.execute('''
                SELECT
                    COUNT(*) as days,
                    COALESCE(SUM(total_trades), 0) as total_trades,
                    COALESCE(SUM(wins), 0) as wins,
                    COALESCE(SUM(losses), 0) as losses,
                    COALESCE(SUM(total_pnl), 0.0) as total_pnl,
                    MIN(worst_trade) as worst_trade,
                    MAX(best_trade) as best_trade
                FROM daily_summary
                WHERE date >= date('now', '-7 days')
            ''')
            row = cur.fetchone()
            if row and row['days'] > 0:
                d = dict(row)
                total = d.get('total_trades') or 0
                wins = d.get('wins') or 0
                d['win_rate'] = round((wins / total * 100), 1) if total > 0 else 0.0
                d['worst_trade'] = float(d['worst_trade'] or 0.0)
                d['best_trade'] = float(d['best_trade'] or 0.0)
                d['total_pnl'] = float(d['total_pnl'] or 0.0)
                return d
            return {}
        except Exception as e:
            logger.error("TradeJournal: get_weekly_performance error: %s", e)
            return {}
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def is_entry_blocked(self) -> bool:
        """Unified risk interface: trade journaling never blocks trade execution."""
        return False

    def is_blocked(self) -> bool:
        return self.is_entry_blocked()

    def reset(self) -> None:
        """Lifecycle reset."""
        pass


# Singleton
_journal = TradeJournal()


def get_journal():
    return _journal
