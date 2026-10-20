"""
wave69_overnight_gap_guard.py
------------------------------
Risk guard: blocks trading for a configurable number of seconds after each
daily market open, protecting against gap-fill slippage and erratic opening
prints.

Rules
-----
- Configurable UTC open times per day (e.g. 00:00 for Forex Sunday open,
  or 07:00 for London cash equities).
- After each open time is detected, a blocking window of `gap_seconds`
  duration is activated.
- Once `gap_seconds` elapses the gate reopens automatically.
- Fail-closed: gate starts OPEN (no trades blocked until an open is detected).
- Each configured open time is triggered at most once per UTC day.

Module-level aliases
---------------------
  is_entry_blocked(tick) -> bool
  is_blocked(tick)       -> bool   (alias)
  update(tick)           -> None   (call regularly to detect opens)
  reset()                -> None

Thread-safety
-------------
  All state mutations are guarded by a threading.RLock().
"""

import math
import threading
import time as _time
from datetime import datetime, time, timezone
from typing import List, Optional, Set, Tuple


# ── tuneable constants ──────────────────────────────────────────────────────
DEFAULT_GAP_SECONDS: float = 30.0    # blocking duration after open

# Default: Forex Sunday open (00:00) + London (07:00) + NY (13:30)
DEFAULT_OPEN_TIMES: List[time] = [
    time(0,  0),   # Forex / Asian open
    time(7,  0),   # London open
    time(13, 30),  # New York open
]


class OvernightGapGuard:
    """
    Blocks entries for `gap_seconds` immediately after each configured daily
    market open time.
    """

    def __init__(
        self,
        open_times: Optional[List[time]] = None,
        gap_seconds: float = DEFAULT_GAP_SECONDS,
    ) -> None:
        # ── validate gap_seconds ──────────────────────────────────────────
        if isinstance(gap_seconds, bool):
            raise TypeError("gap_seconds must not be bool")
        if not isinstance(gap_seconds, (int, float)):
            raise TypeError("gap_seconds must be numeric")
        if math.isnan(gap_seconds) or math.isinf(gap_seconds):
            raise ValueError("gap_seconds must not be NaN/Inf")
        if gap_seconds <= 0:
            raise ValueError("gap_seconds must be > 0")

        self.gap_seconds = float(gap_seconds)

        self._lock = threading.RLock()

        # configured open times (validated)
        self._open_times: List[time] = []
        src = open_times if open_times is not None else DEFAULT_OPEN_TIMES
        for t in src:
            self._add_open_time(t)

        # monotonic timestamp when gap window was triggered (0 = not active)
        self._gap_triggered_at: float = 0.0
        # tracks which opens have already fired today (by day ordinal + time)
        self._fired_today: Set[Tuple[int, time]] = set()

    # ── private ────────────────────────────────────────────────────────────
    @staticmethod
    def _validate_open_time(t: object) -> None:
        if not isinstance(t, time):
            raise TypeError(f"open_time must be datetime.time, got {type(t)}")

    def _add_open_time(self, t: time) -> None:
        self._validate_open_time(t)
        with self._lock:
            if t not in self._open_times:
                self._open_times.append(t)

    def _today_ordinal(self) -> int:
        return datetime.now(timezone.utc).toordinal()

    def _check_for_open(self) -> None:
        """
        Inspect current UTC time; trigger gap window if we're within 1 minute
        after any configured open time (and haven't fired it today).
        """
        now_utc = datetime.now(timezone.utc)
        now_t   = now_utc.time()
        day_ord = now_utc.toordinal()

        with self._lock:
            for open_t in self._open_times:
                key = (day_ord, open_t)
                if key in self._fired_today:
                    continue
                # Check if now is within [open_t, open_t + 60s)
                open_sec  = open_t.hour * 3600 + open_t.minute * 60 + open_t.second
                now_sec   = now_t.hour  * 3600 + now_t.minute  * 60 + now_t.second
                delta_sec = now_sec - open_sec
                if 0 <= delta_sec < 60:
                    # Trigger gap window (only if not already active)
                    if self._gap_triggered_at == 0.0:
                        self._gap_triggered_at = _time.monotonic()
                    self._fired_today.add(key)

            # Purge fired_today entries from previous days
            stale = {k for k in self._fired_today if k[0] != day_ord}
            self._fired_today -= stale

    # ── public API ──────────────────────────────────────────────────────────
    def add_open_time(self, t: time) -> None:
        """Add a recurring daily UTC market open time."""
        self._add_open_time(t)

    def update(self, tick: object = None) -> None:
        """
        Call regularly (e.g. on each incoming tick) to detect market opens.
        """
        self._check_for_open()

    def is_entry_blocked(self, tick: object = None) -> bool:
        """
        Return True (BLOCKED) if within the post-open gap window.
        Automatically checks for new opens on each call.
        """
        self._check_for_open()
        with self._lock:
            if self._gap_triggered_at == 0.0:
                return False
            elapsed = _time.monotonic() - self._gap_triggered_at
            if elapsed >= self.gap_seconds:
                self._gap_triggered_at = 0.0
                return False
            return True

    def reset(self) -> None:
        """Hard-reset all state (gap window + fired-today registry)."""
        with self._lock:
            self._gap_triggered_at = 0.0
            self._fired_today.clear()

    def get_remaining_gap_seconds(self) -> float:
        """Return seconds remaining in current gap window, or 0.0 if inactive."""
        with self._lock:
            if self._gap_triggered_at == 0.0:
                return 0.0
            elapsed = _time.monotonic() - self._gap_triggered_at
            return max(0.0, self.gap_seconds - elapsed)


# ── module-level singleton ──────────────────────────────────────────────────
_guard = OvernightGapGuard(
    open_times=DEFAULT_OPEN_TIMES,
    gap_seconds=DEFAULT_GAP_SECONDS,
)


def is_entry_blocked(tick: object = None) -> bool:
    """Module-level alias → OvernightGapGuard.is_entry_blocked()."""
    return _guard.is_entry_blocked(tick)


def is_blocked(tick: object = None) -> bool:
    """Alias for is_entry_blocked (uniform wave interface)."""
    return _guard.is_entry_blocked(tick)


def update(tick: object = None) -> None:
    """Module-level alias → OvernightGapGuard.update()."""
    _guard.update(tick)


def reset() -> None:
    """Module-level alias → OvernightGapGuard.reset()."""
    _guard.reset()
