"""
Wave 51: Session PnL Tracker
Tracks realized PnL per trading session (Tokyo, London, NY).
If any session accumulates more than SESSION_LOSS_LIMIT USD in losses,
entry is blocked for the remainder of that session.

Sessions (UTC):
  Tokyo:  00:00 - 08:00
  London: 08:00 - 16:00
  NY:     16:00 - 24:00
"""

import time
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SESSION_LOSS_LIMIT = -100.0   # USD — block if session PnL goes below this


def _current_session(dt=None):
    """Return 'Tokyo', 'London', or 'NY' based on UTC hour."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    h = dt.hour
    if 0 <= h < 8:
        return "Tokyo"
    elif 8 <= h < 16:
        return "London"
    else:
        return "NY"


class SessionPnLTracker:
    """
    Tracks cumulative realized PnL per session and blocks entry
    when any active session has exceeded the loss limit.
    """

    def __init__(self, loss_limit: float = SESSION_LOSS_LIMIT):
        self._loss_limit = loss_limit
        # session_pnl holds {session_date_key: pnl}  e.g. {"Tokyo_2024-01-15": -45.0}
        self._session_pnl: dict = {}
        self._last_session_key = ""
        self._blocked_sessions: set = set()
        self._total_trades = 0
        self._created_at = time.time()

    def _key(self, dt=None):
        if dt is None:
            dt = datetime.now(timezone.utc)
        session = _current_session(dt)
        date_str = dt.strftime("%Y-%m-%d")
        return f"{session}_{date_str}", session

    def record_trade(self, pnl: float):
        """
        Record a closed trade PnL into the current session bucket.
        Call once per trade close with realized PnL in USD.
        """
        try:
            key, session = self._key()
            prev = self._session_pnl.get(key, 0.0)
            self._session_pnl[key] = prev + pnl
            self._total_trades += 1
            new_pnl = self._session_pnl[key]

            if new_pnl < self._loss_limit:
                if key not in self._blocked_sessions:
                    self._blocked_sessions.add(key)
                    logger.warning(
                        f"[W51-SessionPnL] {session} session loss limit hit: "
                        f"${new_pnl:.2f} < ${self._loss_limit:.2f} — ENTRY BLOCKED for rest of session"
                    )
            else:
                logger.debug(
                    f"[W51-SessionPnL] {session} session PnL: ${new_pnl:.2f} "
                    f"(limit: ${self._loss_limit:.2f})"
                )
        except Exception as e:
            logger.debug(f"[W51-SessionPnL] record_trade error: {e}")

    def is_entry_blocked(self) -> bool:
        """Return True if current session has exceeded loss limit."""
        try:
            key, session = self._key()
            if key in self._blocked_sessions:
                logger.debug(f"[W51-SessionPnL] Entry BLOCKED — {session} session exceeded loss limit")
                return True
            # Also check threshold even if not yet in blocked set (real-time guard)
            pnl = self._session_pnl.get(key, 0.0)
            if pnl < self._loss_limit:
                self._blocked_sessions.add(key)
                logger.warning(f"[W51-SessionPnL] {session} session loss ${pnl:.2f} — blocking entry")
                return True
            return False
        except Exception as e:
            logger.debug(f"[W51-SessionPnL] is_entry_blocked error: {e}")
            return False

    def get_session_pnl(self, session: str = None) -> float:
        """Return PnL for the given session name today (or current session if None)."""
        try:
            if session is None:
                key, _ = self._key()
            else:
                dt = datetime.now(timezone.utc)
                date_str = dt.strftime("%Y-%m-%d")
                key = f"{session}_{date_str}"
            return self._session_pnl.get(key, 0.0)
        except Exception:
            return 0.0

    def info(self) -> dict:
        """Return serializable status dict for live_status.json."""
        try:
            key, session = self._key()
            current_pnl = self._session_pnl.get(key, 0.0)
            return {
                "current_session": session,
                "current_session_pnl": round(current_pnl, 2),
                "loss_limit": self._loss_limit,
                "is_blocked": key in self._blocked_sessions or current_pnl < self._loss_limit,
                "total_trades_recorded": self._total_trades,
                "blocked_session_count": len(self._blocked_sessions),
                "all_session_pnl": {k: round(v, 2) for k, v in self._session_pnl.items()},
            }
        except Exception:
            return {}


# Module-level singleton
session_pnl_tracker = SessionPnLTracker()
