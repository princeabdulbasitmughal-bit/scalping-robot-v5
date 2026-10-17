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

import logging
import math
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

SESSION_LOSS_LIMIT = -100.0   # USD — block if session PnL goes below this
DEFAULT_MAX_HISTORY_SESSIONS = 30  # Keep up to 30 sessions (~10 trading days)


def _normalize_session(s: Optional[str]) -> str:
    """Normalize session name aliases to canonical title-case."""
    if not isinstance(s, str):
        return "Unknown"
    sl = s.strip().lower()
    if sl in ("tokyo", "asia"):
        return "Tokyo"
    elif sl in ("london", "europe", "eu"):
        return "London"
    elif sl in ("ny", "new york", "new_york", "us"):
        return "NY"
    return s.strip().capitalize()


def _current_session(dt: Optional[datetime] = None) -> str:
    """Return 'Tokyo', 'London', or 'NY' based on UTC hour."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

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

    def __init__(
        self,
        loss_limit: float = SESSION_LOSS_LIMIT,
        max_history_sessions: int = DEFAULT_MAX_HISTORY_SESSIONS,
    ) -> None:
        try:
            val = float(loss_limit)
            if not math.isfinite(val):
                val = SESSION_LOSS_LIMIT
        except (TypeError, ValueError):
            val = SESSION_LOSS_LIMIT

        # Enforce negative sign (loss limit is a loss threshold)
        self._loss_limit = -abs(val)
        self._max_history = max(3, int(max_history_sessions))
        self._lock = threading.RLock()
        self._session_pnl: Dict[str, float] = {}
        self._last_session_key: str = ""
        self._blocked_sessions: set = set()
        self._total_trades: int = 0
        self._created_at: float = time.time()

    def reset(self) -> None:
        """Reset tracker state for testing or daily re-initialization."""
        with self._lock:
            self._session_pnl.clear()
            self._last_session_key = ""
            self._blocked_sessions.clear()
            self._total_trades = 0

    def _key(self, dt: Optional[datetime] = None) -> Tuple[str, str]:
        """
        Resolve the (session_key, session_name) tuple for the given datetime.
        Detects session rollover and executes memory retention pruning.
        Must be called under self._lock.
        """
        if dt is None:
            dt = datetime.now(timezone.utc)
        elif dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)

        session = _current_session(dt)
        date_str = dt.strftime("%Y-%m-%d")
        key = f"{session}_{date_str}"

        # Detect session rollover
        if self._last_session_key and key != self._last_session_key:
            prev_pnl = self._session_pnl.get(self._last_session_key, 0.0)
            logger.info(
                f"[W51-SessionPnL] Session rollover: {self._last_session_key} "
                f"(final PnL: ${prev_pnl:.2f}) -> {key}"
            )
            # Prune stale session history if above threshold
            if len(self._session_pnl) > self._max_history:
                keys_to_remove = sorted(self._session_pnl.keys())[:-self._max_history]
                for old_k in keys_to_remove:
                    self._session_pnl.pop(old_k, None)
                    self._blocked_sessions.discard(old_k)

        self._last_session_key = key
        return key, session

    def record_trade(self, pnl: float, now_dt: Optional[datetime] = None) -> None:
        """
        Record a closed trade PnL into the current session bucket.
        Call once per trade close with realized PnL in USD.
        """
        try:
            if pnl is None or isinstance(pnl, bool):
                return
            pnl_val = float(pnl)
            if not math.isfinite(pnl_val):
                return
        except (TypeError, ValueError):
            return

        try:
            with self._lock:
                key, session = self._key(now_dt)
                prev = self._session_pnl.get(key, 0.0)
                new_pnl = round(prev + pnl_val, 4)
                self._session_pnl[key] = new_pnl
                self._total_trades += 1

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
            logger.error(f"[W51-SessionPnL] record_trade error: {e}", exc_info=True)

    def is_entry_blocked(self, now_dt: Optional[datetime] = None) -> bool:
        """Return True if current session has exceeded loss limit."""
        try:
            with self._lock:
                key, session = self._key(now_dt)
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
            logger.error(f"[W51-SessionPnL] is_entry_blocked error: {e}", exc_info=True)
            return True  # fail-closed

    def unblock_session(self, session: Optional[str] = None, now_dt: Optional[datetime] = None) -> bool:
        """Manually unblock the current or specified session (admin override)."""
        try:
            with self._lock:
                if session is None:
                    key, _ = self._key(now_dt)
                else:
                    norm_sess = _normalize_session(session)
                    dt = now_dt or datetime.now(timezone.utc)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    else:
                        dt = dt.astimezone(timezone.utc)
                    date_str = dt.strftime("%Y-%m-%d")
                    key = f"{norm_sess}_{date_str}"

                if key in self._blocked_sessions:
                    self._blocked_sessions.remove(key)
                    logger.info(f"[W51-SessionPnL] Session {key} manually unblocked")
                    return True
                return False
        except Exception as e:
            logger.error(f"[W51-SessionPnL] unblock_session error: {e}", exc_info=True)
            return False

    def get_session_pnl(self, session: Optional[str] = None, now_dt: Optional[datetime] = None) -> float:
        """Return PnL for the given session name today (or current session if None)."""
        try:
            with self._lock:
                if session is None:
                    key, _ = self._key(now_dt)
                else:
                    norm_sess = _normalize_session(session)
                    dt = now_dt or datetime.now(timezone.utc)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    else:
                        dt = dt.astimezone(timezone.utc)
                    date_str = dt.strftime("%Y-%m-%d")
                    key = f"{norm_sess}_{date_str}"
                return self._session_pnl.get(key, 0.0)
        except Exception:
            return 0.0

    def info(self, now_dt: Optional[datetime] = None) -> dict:
        """Return serializable status dict for live_status.json and omnicommand."""
        try:
            with self._lock:
                key, session = self._key(now_dt)
                current_pnl = self._session_pnl.get(key, 0.0)
                is_blocked = (key in self._blocked_sessions) or (current_pnl < self._loss_limit)
                return {
                    "wave": 51,
                    "name": "SessionPnLTracker",
                    "current_session": session,
                    "current_session_key": key,
                    "current_session_pnl": round(current_pnl, 2),
                    "loss_limit": self._loss_limit,
                    "is_blocked": is_blocked,
                    "blocked": is_blocked,
                    "total_trades_recorded": self._total_trades,
                    "blocked_session_count": len(self._blocked_sessions),
                    "blocked_sessions": list(self._blocked_sessions),
                    "all_session_pnl": {k: round(v, 2) for k, v in self._session_pnl.items()},
                }
        except Exception:
            return {"wave": 51, "name": "SessionPnLTracker", "error": "info_failed"}


# Module-level singleton
session_pnl_tracker = SessionPnLTracker()
