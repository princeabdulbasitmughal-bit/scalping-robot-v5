"""
wave67_session_time_filter.py
------------------------------
Risk guard: only allows trading entries during configured trading sessions
(e.g. Asian, London, New York).

Rules
-----
- Maintains a list of (UTC open, UTC close) session windows (recurring daily).
- Returns BLOCKED if the current UTC time is OUTSIDE all active sessions.
- Any overlap between windows is handled correctly (any active window = allowed).
- Zero sessions configured → BLOCKED (fail-closed by default when unconfigured).
- Fail-closed: invalid window types raise; duplicate windows are silently
  de-duplicated.

Default sessions (UTC)
-----------------------
  Asian   : 00:00 – 08:00
  London  : 07:00 – 16:00   (overlaps Asian close)
  New York: 13:00 – 22:00   (overlaps London close)

Module-level aliases
---------------------
  is_entry_blocked(tick) -> bool
  is_blocked(tick)       -> bool   (alias)
  update(tick)           -> None   (no-op; wave interface)
  reset()                -> None   (clears all sessions → fail-closed)

Thread-safety
-------------
  All state mutations are guarded by a threading.RLock().
"""

import threading
from datetime import datetime, time, timezone
from typing import List, Optional, Tuple


class SessionTimeFilter:
    """
    Blocks trading entries outside configured UTC session windows.

    Parameters
    ----------
    sessions : list of (open_time, close_time) as UTC datetime.time objects.
               None → use DEFAULT_SESSIONS.
               []   → no sessions (always blocked — fail-closed).
    """

    DEFAULT_SESSIONS: List[Tuple[time, time]] = [
        (time(0,  0), time(8,  0)),   # Asian session
        (time(7,  0), time(16, 0)),   # London session
        (time(13, 0), time(22, 0)),   # New York session
    ]

    def __init__(self, sessions: Optional[List[Tuple[time, time]]] = None) -> None:
        self._lock = threading.RLock()
        self._sessions: List[Tuple[time, time]] = []

        src = sessions if sessions is not None else self.DEFAULT_SESSIONS
        for s in src:
            self._validate_and_add(s)

    # ── private helpers ─────────────────────────────────────────────────────
    @staticmethod
    def _validate_pair(open_t: time, close_t: time) -> None:
        for t in (open_t, close_t):
            if not isinstance(t, time):
                raise TypeError(
                    f"Session boundary must be datetime.time, got {type(t)}"
                )
        if open_t >= close_t:
            raise ValueError(
                f"Session open {open_t} must be strictly before close {close_t}"
            )

    def _validate_and_add(self, session: tuple) -> None:
        if not isinstance(session, (tuple, list)) or len(session) != 2:
            raise TypeError("Each session must be a 2-tuple of (open_time, close_time)")
        open_t, close_t = session[0], session[1]
        self._validate_pair(open_t, close_t)
        entry = (open_t, close_t)
        with self._lock:
            if entry not in self._sessions:
                self._sessions.append(entry)

    # ── public API ──────────────────────────────────────────────────────────
    def add_session(self, open_time: time, close_time: time) -> None:
        """Add a recurring UTC trading session."""
        self._validate_pair(open_time, close_time)
        entry = (open_time, close_time)
        with self._lock:
            if entry not in self._sessions:
                self._sessions.append(entry)

    def is_entry_blocked(self, tick: object = None) -> bool:
        """
        Return True (BLOCKED) if the current UTC time is outside all sessions.

        Parameters
        ----------
        tick : optional; accepted for API uniformity but not used.

        Returns
        -------
        bool  – True = blocked (outside all sessions), False = allowed.
        """
        now_time = datetime.now(timezone.utc).time()
        with self._lock:
            if not self._sessions:
                return True   # fail-closed: no sessions configured
            for open_t, close_t in self._sessions:
                if open_t <= now_time <= close_t:
                    return False   # inside at least one session
        return True   # outside all sessions

    def reset(self) -> None:
        """Clear all sessions (returns to fail-closed state)."""
        with self._lock:
            self._sessions.clear()

    def get_session_count(self) -> int:
        """Return the number of configured sessions."""
        with self._lock:
            return len(self._sessions)

    def get_active_session(self) -> Optional[Tuple[time, time]]:
        """
        Return the first active session (open_t, close_t) or None if outside
        all sessions.
        """
        now_time = datetime.now(timezone.utc).time()
        with self._lock:
            for open_t, close_t in self._sessions:
                if open_t <= now_time <= close_t:
                    return (open_t, close_t)
        return None


# ── module-level singleton ──────────────────────────────────────────────────
_filter = SessionTimeFilter()


def is_entry_blocked(tick: object = None) -> bool:
    """Module-level alias → SessionTimeFilter.is_entry_blocked()."""
    return _filter.is_entry_blocked(tick)


def is_blocked(tick: object = None) -> bool:
    """Alias for is_entry_blocked (uniform wave interface)."""
    return _filter.is_entry_blocked(tick)


def update(tick: object = None) -> None:
    """No-op update hook (wave interface compatibility)."""
    pass


def reset() -> None:
    """Module-level alias → SessionTimeFilter.reset()."""
    _filter.reset()
