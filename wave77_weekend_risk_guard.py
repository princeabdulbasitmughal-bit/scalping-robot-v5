"""
wave77_weekend_risk_guard.py
------------------------------
Risk guard: blocks trading in a configurable time window before the weekly
Forex close (Friday) and just after the weekly re-open (Sunday), protecting
against gap risk and thin weekend liquidity.

Rules
-----
- Blocks from `friday_close_buffer_minutes` before Friday 22:00 UTC until
  the weekly close.
- Blocks from Sunday 22:00 UTC until `sunday_open_buffer_minutes` after
  the weekly re-open.
- Returns BLOCKED if current UTC datetime falls in either window.
- Fail-closed: invalid config raises. Gate is OPEN during normal weekday hours.

Default settings (UTC)
-----------------------
  Friday close  : 22:00 UTC  →  block window: 21:30–22:00  (30 min before)
  Sunday re-open: 22:00 UTC  →  block window: 22:00–22:30  (30 min after)

Module-level aliases
---------------------
  is_entry_blocked(tick) -> bool
  is_blocked(tick)       -> bool
  update(tick)           -> None   (no-op; wave interface)
  reset()                -> None   (no persistent state to clear)

Thread-safety
-------------
  All logic is read-only on wall clock; no mutable state needed beyond config.
  RLock guards config updates.
"""

import math
import threading
from datetime import datetime, timezone, timedelta

DEFAULT_FRIDAY_BUFFER_MIN: int = 30   # minutes before Friday 22:00 to block
DEFAULT_SUNDAY_BUFFER_MIN: int = 30   # minutes after  Sunday 22:00 to unblock

# isoweekday(): Monday=1, ..., Friday=5, Saturday=6, Sunday=7
_FRIDAY = 5
_SUNDAY = 7
_WEEKLY_CLOSE_HOUR  = 22   # UTC Friday close
_WEEKLY_OPEN_HOUR   = 22   # UTC Sunday open


class WeekendRiskGuard:
    """Blocks entries during configurable pre-close / post-open weekend buffers."""

    def __init__(
        self,
        friday_buffer_minutes: int = DEFAULT_FRIDAY_BUFFER_MIN,
        sunday_buffer_minutes: int = DEFAULT_SUNDAY_BUFFER_MIN,
    ) -> None:
        for name, val in [("friday_buffer_minutes", friday_buffer_minutes),
                          ("sunday_buffer_minutes", sunday_buffer_minutes)]:
            if isinstance(val, bool) or not isinstance(val, int):
                raise TypeError(f"{name} must be a plain int")
            if val < 0:
                raise ValueError(f"{name} must be >= 0")

        self._lock = threading.RLock()
        self._friday_buf = friday_buffer_minutes
        self._sunday_buf = sunday_buffer_minutes

    def is_entry_blocked(self, tick: object = None) -> bool:
        """
        Return True (BLOCKED) when inside a weekend risk window.
        """
        now = datetime.now(timezone.utc)
        dow = now.isoweekday()   # 1=Mon … 7=Sun
        hour = now.hour
        minute = now.minute

        with self._lock:
            fb = self._friday_buf
            sb = self._sunday_buf

        # ── Friday pre-close block ────────────────────────────────────────
        if dow == _FRIDAY:
            close_minutes = _WEEKLY_CLOSE_HOUR * 60          # 22*60 = 1320
            now_minutes   = hour * 60 + minute
            if now_minutes >= (close_minutes - fb):
                return True

        # ── Saturday — always blocked (market closed) ─────────────────────
        if dow == 6:
            return True

        # ── Sunday post-open block ────────────────────────────────────────
        if dow == _SUNDAY:
            open_minutes = _WEEKLY_OPEN_HOUR * 60            # 22*60 = 1320
            now_minutes  = hour * 60 + minute
            # Before open: blocked; after open within buffer: also blocked
            if now_minutes < open_minutes:
                return True   # before Sunday open
            if now_minutes < (open_minutes + sb):
                return True   # within post-open buffer

        return False

    def update(self, tick: object = None) -> None:
        """No-op update hook (wave interface compatibility)."""
        pass

    def reset(self) -> None:
        """No persistent state — no-op reset (config is retained)."""
        pass

    def get_config(self) -> dict:
        """Return current buffer configuration (thread-safe)."""
        with self._lock:
            return {
                "friday_buffer_minutes": self._friday_buf,
                "sunday_buffer_minutes": self._sunday_buf,
            }


# ── module-level singleton ──────────────────────────────────────────────────
_guard = WeekendRiskGuard()


def is_entry_blocked(tick: object = None) -> bool:
    return _guard.is_entry_blocked(tick)


def is_blocked(tick: object = None) -> bool:
    return _guard.is_entry_blocked(tick)


def update(tick: object = None) -> None:
    pass


def reset() -> None:
    _guard.reset()
