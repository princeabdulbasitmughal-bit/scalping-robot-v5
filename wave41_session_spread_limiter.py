"""
Wave 41: SessionSpreadLimiter
During low-liquidity sessions (Tokyo for gold), reject trades if spread > session threshold.
Tokyo: max 1.5 pips | London pre-open (06:00-07:00 UTC): max 2.0 pips | All other: max 3.0 pips
"""
import time
import datetime
import logging

logger = logging.getLogger(__name__)

# Session spread limits (pips)
_SESSION_LIMITS = {
    "tokyo":        1.5,   # 00:00-06:00 UTC
    "london_pre":   2.0,   # 06:00-07:00 UTC (low liquidity before London opens properly)
    "default":      3.0,   # all other times
}


class SessionSpreadLimiter:
    """
    Blocks entries if the current spread exceeds the session-specific maximum pip limit.
    Gold is low-liquidity during Tokyo hours and London pre-open, so spread thresholds are tighter.
    """

    def __init__(self) -> None:
        self._last_session: str = "default"
        self._last_spread: float = 0.0
        self._last_limit: float = _SESSION_LIMITS["default"]
        self._blocked_count: int = 0

    # ------------------------------------------------------------------
    @staticmethod
    def _get_session(utc_hour: int) -> str:
        if 0 <= utc_hour < 6:
            return "tokyo"
        elif 6 <= utc_hour < 7:
            return "london_pre"
        return "default"

    # ------------------------------------------------------------------
    def is_entry_blocked(self, spread_pips: float) -> bool:
        """
        Return True if spread is too wide for the current session.

        Args:
            spread_pips: Current bid-ask spread in pips.
        """
        utc_hour = datetime.datetime.utcnow().hour
        session = self._get_session(utc_hour)
        limit = _SESSION_LIMITS[session]

        self._last_session = session
        self._last_spread = spread_pips
        self._last_limit = limit

        if spread_pips > limit:
            self._blocked_count += 1
            logger.debug(
                f"[SESSION SPREAD LIMITER] Blocked — session={session} "
                f"spread={spread_pips:.2f} > limit={limit:.2f} pips"
            )
            return True
        return False

    # ------------------------------------------------------------------
    def info(self) -> dict:
        return {
            "session": self._last_session,
            "spread_pips": round(self._last_spread, 3),
            "limit_pips": self._last_limit,
            "blocked_count_total": self._blocked_count,
        }


# Module-level singleton
session_spread_limiter = SessionSpreadLimiter()
