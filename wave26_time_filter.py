"""
Wave 26: Time Filter
--------------------
Blocks trading 30 minutes before and 30 minutes after major UTC economic
release times that are known to cause extreme gold volatility.

Default high-impact release times:
  - 12:30 UTC (08:30 ET EDT) / 13:30 UTC (08:30 ET EST) — US Jobless Claims / NFP / CPI / PPI / Retail Sales
  - 17:00 UTC — OPEC / Energy inventory data
  - 18:00 UTC (14:00 ET EDT) / 19:00 UTC (14:00 ET EST) — FOMC Minutes / Fed Rate Decision
  - 20:30 UTC — Asian session open-volatility window
  - 21:45 UTC — Broker rollover liquidity gap
"""
from __future__ import annotations
import datetime
from datetime import timezone
import logging
import math
import threading
from typing import Tuple, Sequence, Optional

logger = logging.getLogger(__name__)

# Default release times in UTC (hour, minute)
# Includes both EDT (summer) and EST (winter) times for comprehensive year-round coverage
_DEFAULT_RELEASE_TIMES_UTC: list[tuple[int, int]] = [
    (12, 30),   # US Jobless / NFP / CPI / PPI / Retail Sales (08:30 ET EDT)
    (13, 30),   # US Jobless / NFP / CPI / PPI / Retail Sales (08:30 ET EST winter)
    (17,  0),   # OPEC / Energy releases
    (18,  0),   # FOMC / Fed Decision (14:00 ET EDT)
    (19,  0),   # FOMC / Fed Decision (14:00 ET EST winter)
    (20, 30),   # Asian open-volatility window
    (21, 45),   # Rollover window
]

_BLOCK_MINUTES_BEFORE = 30
_BLOCK_MINUTES_AFTER  = 30


class TimeFilter:
    """
    Checks whether the current UTC time falls within a blocked window
    surrounding any known major economic release. Thread-safe with RLock.
    """

    def __init__(
        self,
        release_times: Sequence[tuple[int, int]] | None = None,
        block_before: int = _BLOCK_MINUTES_BEFORE,
        block_after: int  = _BLOCK_MINUTES_AFTER,
    ):
        self._lock = threading.RLock()
        if release_times is not None:
            self._release_times = list(release_times)
        else:
            self._release_times = list(_DEFAULT_RELEASE_TIMES_UTC)
        self._validate_release_times(self._release_times)
        self._block_before   = max(0, int(block_before))
        self._block_after    = max(0, int(block_after))
        self._total_blocks   = 0
        self._last_block_reason: str = ""
        self._was_blocked: bool = False

    # ------------------------------------------------------------------ #
    #  Validation & Normalization Helpers                                #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _validate_release_times(times: Sequence[tuple[int, int]]) -> None:
        if not isinstance(times, (list, tuple)):
            raise TypeError(f"release_times must be a list/tuple, got {type(times).__name__}")
        for item in times:
            if not (isinstance(item, (tuple, list)) and len(item) == 2):
                raise ValueError(f"Each release time must be a tuple of (hour, minute), got {item!r}")
            h, m = item
            if not (isinstance(h, int) and isinstance(m, int)):
                raise TypeError(f"Hour and minute must be integers, got ({type(h).__name__}, {type(m).__name__})")
            if not (0 <= h <= 23):
                raise ValueError(f"Hour must be in 0..23, got {h}")
            if not (0 <= m <= 59):
                raise ValueError(f"Minute must be in 0..59, got {m}")

    @staticmethod
    def _normalize_datetime(dt: datetime.datetime | int | float | str | None) -> datetime.datetime:
        """
        Ensures datetime is a timezone-aware UTC datetime.
        - None: returns datetime.datetime.now(timezone.utc)
        - int/float: treated as UTC unix epoch timestamp
        - str: parsed as ISO 8601 string
        - naive datetime: assumed to represent UTC, tzinfo attached
        - aware datetime: converted to UTC via astimezone
        """
        if dt is None:
            return datetime.datetime.now(timezone.utc)
        if isinstance(dt, (int, float)):
            return datetime.datetime.fromtimestamp(dt, tz=timezone.utc)
        if isinstance(dt, str):
            dt = datetime.datetime.fromisoformat(dt)
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    # ------------------------------------------------------------------ #
    #  Public API                                                        #
    # ------------------------------------------------------------------ #

    def is_trading_allowed(
        self,
        now_utc: datetime.datetime | int | float | str | None = None,
        update_state: bool = True,
    ) -> Tuple[bool, str]:
        """
        Returns (True, "") if trading is allowed, or
        (False, reason) if it is inside a blocked window.
        """
        with self._lock:
            dt = self._normalize_datetime(now_utc)
            return self._is_trading_allowed_locked(dt, update_state=update_state)

    def is_entry_blocked(self, now_utc: datetime.datetime | int | float | str | None = None) -> bool:
        """Alias conforming to Wave 35-39 guard interface (returns True if blocked)."""
        allowed, _ = self.is_trading_allowed(now_utc, update_state=True)
        return not allowed

    def is_blocked(self, now_utc: datetime.datetime | int | float | str | None = None) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked(now_utc)

    def _is_trading_allowed_locked(
        self,
        dt: datetime.datetime,
        update_state: bool = True,
    ) -> Tuple[bool, str]:
        # Second-precision comparison avoids 59-second trailing asymmetry
        now_seconds = dt.hour * 3600 + dt.minute * 60 + dt.second
        block_before_sec = self._block_before * 60
        block_after_sec  = self._block_after * 60

        for (rh, rm) in self._release_times:
            release_seconds = rh * 3600 + rm * 60
            raw_diff = now_seconds - release_seconds
            # Circular diff in seconds: range [-43200, +43199] handles midnight rollover
            diff = (raw_diff + 43200) % 86400 - 43200

            if -block_before_sec <= diff <= block_after_sec:
                direction = "before" if diff < 0 else "after"
                diff_m = int(round(abs(diff) / 60))
                release_label = f"{rh:02d}:{rm:02d} UTC"
                reason = (
                    f"TIME_FILTER: {diff_m}m {direction} major release "
                    f"at {release_label} — trading blocked"
                )
                if update_state:
                    if not self._was_blocked:
                        self._total_blocks += 1
                        self._was_blocked = True
                        logger.warning("[WAVE26] %s", reason)
                    self._last_block_reason = reason
                return False, reason

        if update_state:
            self._was_blocked = False
        return True, ""

    def info(self, now_utc: datetime.datetime | int | float | str | None = None) -> dict:
        """Return status dict for live_status.json and OmniCommand telemetry."""
        with self._lock:
            dt = self._normalize_datetime(now_utc)
            now_sec = dt.hour * 3600 + dt.minute * 60 + dt.second

            # Find next scheduled release in minutes
            next_release_in: int | None = None
            try:
                for (rh, rm) in sorted(self._release_times):
                    rel_sec = rh * 3600 + rm * 60
                    delta_sec = rel_sec - now_sec
                    if delta_sec < 0:
                        delta_sec += 86400  # wrap to tomorrow
                    delta_min = delta_sec // 60
                    if next_release_in is None or delta_min < next_release_in:
                        next_release_in = delta_min
            except Exception:
                next_release_in = None

            allowed, reason = self._is_trading_allowed_locked(dt, update_state=True)

            # Compute remaining minutes in active block
            remaining_block_min = 0
            if not allowed:
                block_after_sec = self._block_after * 60
                for (rh, rm) in self._release_times:
                    rel_sec = rh * 3600 + rm * 60
                    raw_diff = now_sec - rel_sec
                    diff = (raw_diff + 43200) % 86400 - 43200
                    if -self._block_before * 60 <= diff <= block_after_sec:
                        sec_left = block_after_sec - diff
                        rem_m = int(math.ceil(sec_left / 60))
                        if rem_m > remaining_block_min:
                            remaining_block_min = rem_m

            return {
                "wave": 26,
                "name": "TimeFilter",
                "trading_allowed": allowed,
                "blocked": not allowed,
                "is_blocked": not allowed,
                "entry_blocked": not allowed,
                "reason": reason,
                "last_block_reason": self._last_block_reason,
                "total_blocks": self._total_blocks,
                "next_release_in_min": next_release_in,
                "remaining_block_min": remaining_block_min,
                "block_before_min": self._block_before,
                "block_after_min": self._block_after,
                "release_times": list(self._release_times),
            }

    # ------------------------------------------------------------------ #
    #  Runtime Configuration API                                         #
    # ------------------------------------------------------------------ #

    def set_release_times(self, release_times: Sequence[tuple[int, int]]) -> None:
        """Thread-safe update of scheduled release times."""
        self._validate_release_times(release_times)
        with self._lock:
            self._release_times = list(release_times)

    def add_release_time(self, hour: int, minute: int) -> None:
        """Thread-safe addition of a release time."""
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(f"Invalid time: {hour:02d}:{minute:02d}")
        with self._lock:
            entry = (hour, minute)
            if entry not in self._release_times:
                self._release_times.append(entry)

    def reset(self) -> None:
        """Thread-safe reset of block counters and status flags."""
        with self._lock:
            self._total_blocks = 0
            self._was_blocked = False
            self._last_block_reason = ""

    def reset_stats(self) -> None:
        """Alias for reset."""
        self.reset()


# Module-level singleton
time_filter = TimeFilter()
