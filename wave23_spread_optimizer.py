"""
Wave 23: Spread Optimizer
Dynamic spread threshold that tightens during low-vol sessions and widens
during peak London/NY overlap to capture more opportunities.

Spread threshold table (pips):
  Tokyo     : 1.8   (tight — low liquidity, reject high spread)
  London    : 3.0   (standard)
  NY        : 2.5
  LDN-NY    : 3.5   (overlap — allow wider spread for fast markets)
  Off-hours : 1.5   (very strict)
"""

import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Session spread thresholds in pips
_SESSION_SPREAD_LIMITS = {
    "TOKYO":    1.8,
    "LONDON":   3.0,
    "NEW_YORK": 2.5,
    "LDN_NY":   3.5,
    "OFF":      1.5,
}

# Fallback if session info not available
_DEFAULT_LIMIT = 2.5


class SpreadOptimizer:
    """
    Determines whether the current spread is acceptable for trading
    given the active market session.
    """

    def __init__(self):
        self._rejected_count: int = 0
        self._accepted_count: int = 0
        self._last_spread: float = 0.0
        self._last_session: str = "OFF"
        self._last_limit: float = _DEFAULT_LIMIT

    # ------------------------------------------------------------------
    def _detect_session(self) -> str:
        """Simple UTC-hour based session detector (fallback if no session_optimizer)."""
        utc_hour = datetime.now(timezone.utc).hour
        if 22 <= utc_hour or utc_hour < 7:    # 22:00-07:00 UTC
            return "TOKYO"
        elif 7 <= utc_hour < 12:              # 07:00-12:00 UTC
            return "LONDON"
        elif 12 <= utc_hour < 17:             # 12:00-17:00 UTC — overlap
            return "LDN_NY"
        elif 17 <= utc_hour < 22:             # 17:00-22:00 UTC
            return "NEW_YORK"
        return "OFF"

    # ------------------------------------------------------------------
    def is_spread_ok(
        self,
        spread_pips: float,
        session_name: str = None,
        vol_index: float = 1.0,
    ) -> tuple:
        """
        Returns (ok: bool, reason: str).

        Args:
            spread_pips  : current broker spread in pips
            session_name : optional session name from wave10 session optimizer
            vol_index    : current session volatility index (from wave10)
        """
        self._last_spread = spread_pips

        # Resolve session
        session = (session_name or self._detect_session()).upper()
        # Normalize common variations
        session = session.replace("NEW YORK", "NEW_YORK").replace("LDN/NY", "LDN_NY")
        if "LONDON" in session and "NY" in session:
            session = "LDN_NY"
        elif "NEW" in session or "YORK" in session:
            session = "NEW_YORK"
        elif "LONDON" in session:
            session = "LONDON"
        elif "TOKYO" in session:
            session = "TOKYO"

        self._last_session = session
        base_limit = _SESSION_SPREAD_LIMITS.get(session, _DEFAULT_LIMIT)

        # Adjust for volatility: high vol → allow slightly wider spread
        if vol_index >= 1.5:
            limit = base_limit * 1.2
        elif vol_index <= 0.5:
            limit = base_limit * 0.85
        else:
            limit = base_limit

        self._last_limit = round(limit, 2)

        if spread_pips > limit:
            self._rejected_count += 1
            reason = (
                f"SPREAD REJECT [{session}]: {spread_pips:.2f}pip > limit {limit:.2f}pip "
                f"(vol_idx={vol_index:.2f})"
            )
            logger.debug(f"[SPREAD OPT] {reason}")
            return False, reason

        self._accepted_count += 1
        reason = (
            f"spread ok [{session}]: {spread_pips:.2f}pip <= {limit:.2f}pip"
        )
        return True, reason

    def info(self) -> dict:
        """Summary dict for live_status.json."""
        return {
            "last_spread_pips": round(self._last_spread, 2),
            "session": self._last_session,
            "limit_pips": self._last_limit,
            "accepted": self._accepted_count,
            "rejected": self._rejected_count,
        }


# Module-level singleton
spread_optimizer = SpreadOptimizer()
