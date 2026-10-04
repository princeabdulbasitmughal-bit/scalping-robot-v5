"""
Wave 26: Time Filter
--------------------
Blocks trading 30 minutes before and 30 minutes after major UTC economic
release times that are known to cause extreme gold volatility.

Default high-impact release times (UTC):
  08:30 — US Jobless Claims / NFP
  12:30 — USD CPI / PPI / Retail Sales
  14:00 — FOMC Minutes / Fed Decision
  17:00 — OPEC / Energy data
  20:30 — Asian session open-volatility window
  21:45 — Rollover / end-of-day liquidity gap (already guarded, included for completeness)

The filter is intentionally broader than any pre-existing news buffer because
wave26 focuses on *scheduled* release windows (clock-based), not on live news
keyword detection (wave21).
"""
from __future__ import annotations
import datetime
import logging
from typing import Tuple

logger = logging.getLogger(__name__)

# (hour_utc, minute_utc) of each major release
_DEFAULT_RELEASE_TIMES_UTC: list[tuple[int, int]] = [
    (8,  30),   # US Jobless / NFP
    (12, 30),   # CPI / PPI / Retail Sales
    (14,  0),   # FOMC / Fed Decision
    (17,  0),   # OPEC / Energy
    (20, 30),   # Asian open-volatility
    (21, 45),   # Rollover window
]

_BLOCK_MINUTES_BEFORE = 30
_BLOCK_MINUTES_AFTER  = 30


class TimeFilter:
    """
    Checks whether the current UTC time falls within a blocked window
    surrounding any known major economic release.

    Parameters
    ----------
    release_times : list of (hour, minute) in UTC
    block_before  : minutes to block before the release
    block_after   : minutes to block after the release
    """

    def __init__(
        self,
        release_times: list[tuple[int, int]] | None = None,
        block_before: int = _BLOCK_MINUTES_BEFORE,
        block_after: int  = _BLOCK_MINUTES_AFTER,
    ):
        self._release_times  = release_times or _DEFAULT_RELEASE_TIMES_UTC
        self._block_before   = block_before
        self._block_after    = block_after
        self._total_blocks   = 0
        self._last_block_reason: str = ""

    # ------------------------------------------------------------------ #
    #  Public API                                                           #
    # ------------------------------------------------------------------ #

    def is_trading_allowed(self, now_utc: datetime.datetime | None = None) -> Tuple[bool, str]:
        """
        Returns (True, "") if trading is allowed, or
        (False, reason) if it is inside a blocked window.
        """
        if now_utc is None:
            now_utc = datetime.datetime.utcnow()

        now_minutes = now_utc.hour * 60 + now_utc.minute

        for (rh, rm) in self._release_times:
            release_minutes = rh * 60 + rm
            diff = now_minutes - release_minutes  # negative = before, positive = after

            if -self._block_before <= diff <= self._block_after:
                direction = "before" if diff < 0 else "after"
                release_label = f"{rh:02d}:{rm:02d} UTC"
                reason = (
                    f"TIME_FILTER: {abs(diff)}m {direction} major release "
                    f"at {release_label} — trading blocked"
                )
                self._total_blocks += 1
                self._last_block_reason = reason
                logger.warning("[WAVE26] %s", reason)
                return False, reason

        return True, ""

    def info(self) -> dict:
        """Return status dict for live_status.json."""
        try:
            now_utc = datetime.datetime.utcnow()
            now_minutes = now_utc.hour * 60 + now_utc.minute
            # Find next release window in minutes
            next_release_in: int | None = None
            for (rh, rm) in sorted(self._release_times):
                rel_min = rh * 60 + rm
                delta = rel_min - now_minutes
                if delta < 0:
                    delta += 1440  # wrap to tomorrow
                if next_release_in is None or delta < next_release_in:
                    next_release_in = delta
        except Exception:
            next_release_in = None

        allowed, reason = self.is_trading_allowed()
        return {
            "trading_allowed": allowed,
            "reason": reason,
            "total_blocks": self._total_blocks,
            "next_release_in_min": next_release_in,
            "block_before_min": self._block_before,
            "block_after_min": self._block_after,
        }


# Module-level singleton
time_filter = TimeFilter()
