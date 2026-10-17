"""
Wave 61: Opening Range Breakout (ORB) Filter
============================================
Tracks the first-30-minute price range after each major session open
(London 08:00 UTC, New York 13:00 UTC).

Logic:
- During the first 30 min of a session: record every tick (build the range)
- After 30 min: only allow BUY if price > OR_high, only allow SELL if price < OR_low
- Resets at each new session open
- Requires at least 10 ticks in the range before filtering activates
- Advisory: if range not yet built, returns False (no block)
"""

import math
import time
import logging
import threading
from datetime import datetime, timezone
from typing import Optional, Tuple, Any

logger = logging.getLogger(__name__)

_LONDON_OPEN_UTC_HOUR = 8       # 08:00 UTC
_NY_OPEN_UTC_HOUR = 13          # 13:00 UTC
_ORB_WINDOW_SECONDS = 1800      # 30 minutes
_MIN_TICKS = 10                 # minimum ticks before filter activates


class BlockResult(int):
    """
    Subscriptable result object that behaves as:
    - bool: `if res:` evaluates to `blocked`
    - tuple: `res[0]` is blocked (bool), `res[1]` is reason (str)
    - iterator: `blocked, reason = res`
    - int: `int(res)` is 1 if blocked else 0
    """
    def __new__(cls, blocked: bool, reason: str = ""):
        obj = super().__new__(cls, 1 if blocked else 0)
        obj.blocked = bool(blocked)
        obj.reason = str(reason)
        return obj

    def __iter__(self):
        yield self.blocked
        yield self.reason

    def __getitem__(self, index):
        if index == 0:
            return self.blocked
        elif index == 1:
            return self.reason
        raise IndexError(f"BlockResult index out of range: {index}")

    def __bool__(self):
        return self.blocked

    def __repr__(self):
        return f"BlockResult({self.blocked}, '{self.reason}')"


class OpeningRangeBreakout:
    """
    Opening Range Breakout filter.

    Tracks the high/low of the first 30 minutes after London/NY open.
    After the window, blocks:
      - BUY if price <= OR_high  (no confirmed breakout up)
      - SELL if price >= OR_low  (no confirmed breakout down)

    Resets at each new session open.
    Thread-safe with RLock and supports deterministic datetime injection.
    """

    def __init__(self, min_ticks: int = _MIN_TICKS, window_seconds: int = _ORB_WINDOW_SECONDS):
        self._min_ticks = max(1, int(min_ticks))
        self._window_seconds = max(60, int(window_seconds))
        self._session_start: Optional[float] = None
        self._or_high: Optional[float] = None
        self._or_low: Optional[float] = None
        self._in_window: bool = False
        self._window_complete: bool = False
        self._tick_count: int = 0
        self._last_price: float = 0.0
        # Track (year, day_of_year, hour) to correctly reset across multiple days
        self._last_session_key: tuple = (-1, -1, -1)
        self._total_blocks: int = 0
        self._lock = threading.RLock()

    def reset(self) -> None:
        """Thread-safe reset of internal ORB state."""
        with self._lock:
            self._session_start = None
            self._or_high = None
            self._or_low = None
            self._in_window = False
            self._window_complete = False
            self._tick_count = 0
            self._last_price = 0.0
            self._last_session_key = (-1, -1, -1)
            self._total_blocks = 0

    def _normalize_dt(self, dt: Optional[datetime]) -> datetime:
        if dt is None:
            return datetime.now(timezone.utc)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    # ------------------------------------------------------------------
    def _check_session_reset(self, now_dt: Optional[datetime] = None) -> None:
        """Reset when we detect a new London or NY session opening."""
        dt = self._normalize_dt(now_dt)
        hour = dt.hour
        minute = dt.minute
        year = dt.year
        yday = dt.timetuple().tm_yday

        is_session_hour = (hour == _LONDON_OPEN_UTC_HOUR or hour == _NY_OPEN_UTC_HOUR)
        within_grace = minute < 15   # first 15 minutes of the hour

        # Reset once per session: use (year, yday, hour) so next day's same hour fires again
        session_key = (year, yday, hour)
        if is_session_hour and within_grace and session_key != self._last_session_key:
            current_ts = dt.timestamp()
            self._session_start = current_ts - (minute * 60)  # backdate to exact open
            self._or_high = None
            self._or_low = None
            self._in_window = True
            self._window_complete = False
            self._tick_count = 0
            self._last_session_key = session_key
            logger.info(f"[WAVE61] ORB session reset — {hour:02d}:00 UTC session open")

    def update(self, price: Any, now_dt: Optional[datetime] = None) -> None:
        """Feed each tick price."""
        if price is None or isinstance(price, bool):
            return
        try:
            p = float(price)
            if not math.isfinite(p) or p <= 0:
                return
        except (ValueError, TypeError):
            return

        dt = self._normalize_dt(now_dt)
        current_ts = dt.timestamp()

        try:
            with self._lock:
                self._last_price = p
                self._check_session_reset(now_dt)

                if not self._in_window:
                    return

                # Check if window has expired
                if self._session_start is not None:
                    elapsed = current_ts - self._session_start
                    if elapsed >= self._window_seconds:
                        self._in_window = False
                        self._window_complete = True
                        logger.info(
                            f"[WAVE61] ORB window complete — high={self._or_high} low={self._or_low} "
                            f"ticks={self._tick_count}"
                        )
                        return

                # Build the range
                if self._or_high is None or p > self._or_high:
                    self._or_high = p
                if self._or_low is None or p < self._or_low:
                    self._or_low = p
                self._tick_count += 1
        except Exception as e:
            logger.debug(f"[WAVE61] update error: {e}")

    # ------------------------------------------------------------------
    def is_signal_blocked(self, signal: Any, price: Optional[float] = None, now_dt: Optional[datetime] = None) -> BlockResult:
        """
        Returns BlockResult (behaves as bool, 2-tuple, and subscriptable [0]/[1]).
        """
        try:
            sig = str(signal).strip().upper() if signal is not None else ""
            if sig not in ("BUY", "SELL"):
                return BlockResult(False, "non_directional_signal")

            with self._lock:
                if not self._window_complete:
                    return BlockResult(False, "window_not_complete")
                if self._tick_count < self._min_ticks:
                    return BlockResult(False, "insufficient_ticks")
                if self._or_high is None or self._or_low is None:
                    return BlockResult(False, "range_not_established")

                curr_p = float(price) if price is not None and math.isfinite(float(price)) and float(price) > 0 else self._last_price
                or_h = self._or_high
                or_l = self._or_low

            if sig == "BUY" and curr_p <= or_h:
                with self._lock:
                    self._total_blocks += 1
                logger.debug(
                    f"[WAVE61] ORB BUY blocked — price {curr_p:.2f} not above OR_high {or_h:.2f}"
                )
                return BlockResult(True, "price_not_above_or_high")

            if sig == "SELL" and curr_p >= or_l:
                with self._lock:
                    self._total_blocks += 1
                logger.debug(
                    f"[WAVE61] ORB SELL blocked — price {curr_p:.2f} not below OR_low {or_l:.2f}"
                )
                return BlockResult(True, "price_not_below_or_low")

            return BlockResult(False, "breakout_confirmed")
        except Exception as e:
            logger.error(f"[WAVE61] is_signal_blocked error: {e}")
            return BlockResult(False, "error")

    def is_entry_blocked(self, signal: Any, price: Optional[float] = None, now_dt: Optional[datetime] = None) -> bool:
        """Boolean alias for is_signal_blocked."""
        return bool(self.is_signal_blocked(signal, price=price, now_dt=now_dt))

    def get_range_pips(self, pip_size: float = 0.1) -> float:
        """Return the opening range size in pips (XAUUSD: pip_size=0.1)."""
        with self._lock:
            if self._or_high is None or self._or_low is None:
                return 0.0
            p_size = pip_size if pip_size > 0 else 0.1
            return round((self._or_high - self._or_low) / p_size, 1)

    def info(self) -> dict:
        with self._lock:
            if self._or_high is not None and self._or_low is not None:
                range_pips = round((self._or_high - self._or_low) / 0.1, 1)
            else:
                range_pips = 0.0
            return {
                "wave": 61,
                "name": "OpeningRangeBreakout",
                "in_window": self._in_window,
                "window_complete": self._window_complete,
                "or_high": self._or_high,
                "or_low": self._or_low,
                "range_pips": range_pips,
                "tick_count": self._tick_count,
                "last_price": self._last_price,
                "total_blocks": self._total_blocks,
            }


# Module-level singleton
opening_range_breakout = OpeningRangeBreakout()
