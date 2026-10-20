"""
wave65_news_blackout_guard.py
------------------------------
Risk guard: blocks trading during configurable news blackout windows.

Rules
-----
- Maintains a list of (UTC start, UTC end) blackout windows per day.
- Returns BLOCKED if the current UTC time falls inside any window.
- Windows are specified as (hour, minute) tuples for daily recurring events.
- Fail-closed: invalid inputs are rejected; overlapping windows are handled
  (any overlap triggers block).
- Additional one-shot absolute blackout events can be scheduled via
  `add_absolute_window(start_dt, end_dt)`.

Module-level aliases
---------------------
  is_entry_blocked(tick) -> bool
  is_blocked(tick)       -> bool   (alias)
  update(tick)           -> None   (no-op; wave interface)
  reset()                -> None   (clears all windows)

Thread-safety
-------------
  All state mutations are guarded by a threading.RLock().

Typical economic calendar windows (defaults)
--------------------------------------------
  Non-Farm Payrolls  : 12:30 UTC ± 15 min  → (12,15)–(12,45)
  FOMC               : 18:00 UTC ± 30 min  → (17,30)–(18,30)
  CPI                : 12:30 UTC ± 15 min  (overlaps NFP window)
  ECB Rate Decision  : 12:45 UTC ± 15 min  → (12,30)–(13,00)
"""

import math
import threading
from datetime import datetime, time, timezone
from typing import List, Optional, Tuple


class NewsBlackoutGuard:
    """
    Blocks trading entries during pre-configured UTC time windows.

    Parameters
    ----------
    windows : list of (start_time, end_time) as UTC `datetime.time` objects.
              Recurring daily. Pass `[]` to start with no windows.
    """

    # Default recurring windows (UTC, daily) — common high-impact news events
    DEFAULT_WINDOWS: List[Tuple[time, time]] = [
        (time(12, 15), time(12, 45)),   # NFP / CPI ± 15 min
        (time(12, 30), time(13, 0)),    # ECB Rate Decision
        (time(17, 30), time(18, 30)),   # FOMC ± 30 min
    ]

    def __init__(
        self,
        windows: Optional[List[Tuple[time, time]]] = None,
    ) -> None:
        self._lock = threading.RLock()

        # Recurring daily UTC windows
        self._recurring: List[Tuple[time, time]] = []
        # Absolute one-shot windows (datetime pairs)
        self._absolute: List[Tuple[datetime, datetime]] = []

        # Load defaults or user-supplied
        src = windows if windows is not None else self.DEFAULT_WINDOWS
        for w in src:
            self._validate_and_add(w)

    # ── private helpers ─────────────────────────────────────────────────────
    @staticmethod
    def _validate_time_pair(start: time, end: time) -> None:
        for t in (start, end):
            if not isinstance(t, time):
                raise TypeError(f"Window boundary must be datetime.time, got {type(t)}")
        if start >= end:
            raise ValueError(f"Window start {start} must be before end {end}")

    def _validate_and_add(self, window: Tuple[time, time]) -> None:
        if not isinstance(window, (tuple, list)) or len(window) != 2:
            raise TypeError("Each window must be a 2-tuple of (datetime.time, datetime.time)")
        start, end = window
        self._validate_time_pair(start, end)
        with self._lock:
            self._recurring.append((start, end))

    # ── public API ──────────────────────────────────────────────────────────
    def add_recurring_window(self, start: time, end: time) -> None:
        """Add a recurring UTC daily blackout window."""
        self._validate_time_pair(start, end)
        with self._lock:
            self._recurring.append((start, end))

    def add_absolute_window(self, start: datetime, end: datetime) -> None:
        """
        Add a one-shot absolute UTC blackout window.

        Parameters
        ----------
        start, end : timezone-aware datetime objects (UTC recommended).
        """
        for dt in (start, end):
            if not isinstance(dt, datetime):
                raise TypeError("Absolute window boundaries must be datetime objects")
        if start >= end:
            raise ValueError("Absolute window start must be before end")
        with self._lock:
            self._absolute.append((start, end))

    def is_entry_blocked(self, tick: object = None) -> bool:
        """
        Return True (BLOCKED) if the current UTC time is inside any blackout window.

        Parameters
        ----------
        tick : optional; accepted for API uniformity but not used.

        Returns
        -------
        bool  – True = blocked (in blackout), False = allowed.
        """
        now_utc = datetime.now(timezone.utc)
        now_time = now_utc.time()

        with self._lock:
            # Check recurring daily windows
            for start, end in self._recurring:
                if start <= now_time <= end:
                    return True

            # Check absolute one-shot windows
            for start, end in self._absolute:
                # Make start/end timezone-aware if naive (assume UTC)
                s = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
                e = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
                if s <= now_utc <= e:
                    return True

        return False

    def reset(self) -> None:
        """Clear all blackout windows."""
        with self._lock:
            self._recurring.clear()
            self._absolute.clear()

    def get_window_count(self) -> int:
        """Return total number of active blackout windows."""
        with self._lock:
            return len(self._recurring) + len(self._absolute)


# ── module-level singleton ──────────────────────────────────────────────────
_guard = NewsBlackoutGuard()


def is_entry_blocked(tick: object = None) -> bool:
    """Module-level alias → NewsBlackoutGuard.is_entry_blocked()."""
    return _guard.is_entry_blocked(tick)


def is_blocked(tick: object = None) -> bool:
    """Alias for is_entry_blocked (uniform wave interface)."""
    return _guard.is_entry_blocked(tick)


def update(tick: object = None) -> None:
    """No-op update hook (wave interface compatibility)."""
    pass


def reset() -> None:
    """Module-level alias → NewsBlackoutGuard.reset()."""
    _guard.reset()
