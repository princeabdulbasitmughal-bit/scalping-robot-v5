"""
Wave 41: SessionSpreadLimiter (Hardened & Thread-Safe)
During low-liquidity sessions (Tokyo for gold), reject trades if spread > session threshold.
Tokyo: max 1.5 pips | London pre-open (06:00-07:00 UTC): max 2.0 pips | All other: max 3.0 pips
"""

import logging
import math
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Default session spread limits (pips)
_SESSION_LIMITS: Dict[str, float] = {
    "tokyo": 1.5,       # 00:00-06:00 UTC
    "london_pre": 2.0,  # 06:00-07:00 UTC (low liquidity before London opens)
    "default": 3.0,     # all other times
}


class SessionSpreadLimiter:
    """
    Blocks entries if the current spread exceeds the session-specific maximum pip limit.
    Gold is low-liquidity during Tokyo hours and London pre-open, so spread thresholds are tighter.
    """

    def __init__(self, custom_limits: Optional[Dict[str, float]] = None) -> None:
        self._lock = threading.RLock()
        self._limits: Dict[str, float] = dict(_SESSION_LIMITS)
        if custom_limits:
            self._limits.update({k: float(v) for k, v in custom_limits.items()})

        self._last_session: str = "default"
        self._last_spread: float = 0.0
        self._last_limit: float = self._limits.get("default", 3.0)
        self._blocked_count: int = 0
        self._invalid_count: int = 0

    # ------------------------------------------------------------------
    @staticmethod
    def _get_session(utc_hour: int, utc_minute: int = 0) -> str:
        """
        Resolve session name based on UTC hour and minute.
        Resilient against invalid, non-int, or out-of-range hour values.
        """
        try:
            hour = int(utc_hour) % 24
        except (TypeError, ValueError):
            return "default"

        if 0 <= hour < 6:
            return "tokyo"
        elif 6 <= hour < 7:
            return "london_pre"
        return "default"

    # ------------------------------------------------------------------
    def is_entry_blocked(
        self,
        spread_pips: Any,
        now_dt: Optional[datetime] = None
    ) -> bool:
        """
        Return True if spread is too wide for the current session or invalid.

        Args:
            spread_pips: Current bid-ask spread in pips (must be finite positive number).
            now_dt: Optional datetime object for historical backtesting / deterministic tests.
        """
        # 1. Non-finite, non-numeric, or non-positive spread validation
        try:
            val = float(spread_pips)
            is_valid = (
                not isinstance(spread_pips, bool)
                and math.isfinite(val)
                and val > 0.0
            )
        except (TypeError, ValueError):
            is_valid = False
            val = float("nan")

        if not is_valid:
            with self._lock:
                self._blocked_count += 1
                self._invalid_count += 1
                self._last_spread = val if math.isnan(val) else 0.0
            logger.warning(
                f"[SESSION SPREAD LIMITER] Blocked — invalid spread value ({spread_pips})"
            )
            return True

        # 2. Time and session resolution
        if now_dt is not None:
            dt = now_dt.astimezone(timezone.utc) if now_dt.tzinfo else now_dt.replace(tzinfo=timezone.utc)
        else:
            dt = datetime.now(timezone.utc)

        session = self._get_session(dt.hour, dt.minute)

        # 3. Synchronized threshold comparison
        blocked = False
        log_msg = None

        with self._lock:
            limit = self._limits.get(session, self._limits.get("default", 3.0))
            self._last_session = session
            self._last_spread = val
            self._last_limit = limit

            if val > limit:
                self._blocked_count += 1
                blocked = True
                log_msg = (
                    f"[SESSION SPREAD LIMITER] Blocked — session={session} "
                    f"spread={val:.2f} > limit={limit:.2f} pips"
                )

        # Logging outside lock avoids deadlock with complex log handlers
        if log_msg:
            logger.debug(log_msg)

        return blocked

    def is_blocked(self, spread_pips: Any, now_dt: Optional[datetime] = None) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked(spread_pips, now_dt=now_dt)

    # ------------------------------------------------------------------
    def update_limits(self, new_limits: Dict[str, float]) -> None:
        """Thread-safe update of session limits."""
        with self._lock:
            for session_key, limit_val in new_limits.items():
                if isinstance(limit_val, (int, float)) and math.isfinite(limit_val) and limit_val > 0:
                    self._limits[session_key] = float(limit_val)

    # ------------------------------------------------------------------
    def reset(self) -> None:
        """Thread-safe state reset."""
        with self._lock:
            self._blocked_count = 0
            self._invalid_count = 0
            self._last_spread = 0.0

    # ------------------------------------------------------------------
    def info(self) -> dict:
        with self._lock:
            return {
                "wave": 41,
                "name": "SessionSpreadLimiter",
                "session": self._last_session,
                "spread_pips": round(self._last_spread, 3) if math.isfinite(self._last_spread) else None,
                "limit_pips": self._last_limit,
                "blocked_count_total": self._blocked_count,
                "invalid_count": self._invalid_count,
            }


# Module-level singleton
session_spread_limiter = SessionSpreadLimiter()

# Module-level aliases for risk orchestrator integration
def is_entry_blocked(spread_pips: Any, now_dt: Optional[datetime] = None) -> bool:
    return session_spread_limiter.is_entry_blocked(spread_pips, now_dt=now_dt)

def is_blocked(spread_pips: Any, now_dt: Optional[datetime] = None) -> bool:
    return session_spread_limiter.is_entry_blocked(spread_pips, now_dt=now_dt)

def update_limits(new_limits: Dict[str, float]) -> None:
    session_spread_limiter.update_limits(new_limits)

def reset() -> None:
    session_spread_limiter.reset()
