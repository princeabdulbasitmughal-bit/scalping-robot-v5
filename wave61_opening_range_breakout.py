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

import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_LONDON_OPEN_UTC_HOUR = 8       # 08:00 UTC
_NY_OPEN_UTC_HOUR = 13          # 13:00 UTC
_ORB_WINDOW_SECONDS = 1800      # 30 minutes
_MIN_TICKS = 10                 # minimum ticks before filter activates


class OpeningRangeBreakout:
    """
    Opening Range Breakout filter.

    Tracks the high/low of the first 30 minutes after London/NY open.
    After the window, blocks:
      - BUY if price <= OR_high  (no confirmed breakout up)
      - SELL if price >= OR_low  (no confirmed breakout down)

    Resets at each new session open.
    """

    def __init__(self):
        self._session_start: Optional[float] = None
        self._or_high: Optional[float] = None
        self._or_low: Optional[float] = None
        self._in_window: bool = False
        self._window_complete: bool = False
        self._tick_count: int = 0
        self._last_price: float = 0.0
        self._last_session_hour: int = -1

    # ------------------------------------------------------------------
    def _check_session_reset(self):
        """Reset if a new London or NY session has opened."""
        now_utc = time.gmtime()
        hour = now_utc.tm_hour
        minute = now_utc.tm_min

        # Check if we are in the first minute of a session open
        is_session_open = (
            (hour == _LONDON_OPEN_UTC_HOUR and minute == 0) or
            (hour == _NY_OPEN_UTC_HOUR and minute == 0)
        )

        # Only reset once per session (track last session hour)
        if is_session_open and hour != self._last_session_hour:
            self._session_start = time.time()
            self._or_high = None
            self._or_low = None
            self._in_window = True
            self._window_complete = False
            self._tick_count = 0
            self._last_session_hour = hour
            logger.info(f"[WAVE61] ORB session reset — {hour:02d}:00 UTC session open")

    def update(self, price: float):
        """Feed each tick price."""
        self._last_price = price
        self._check_session_reset()

        if not self._in_window:
            return

        # Check if window has expired
        if self._session_start is not None:
            elapsed = time.time() - self._session_start
            if elapsed >= _ORB_WINDOW_SECONDS:
                self._in_window = False
                self._window_complete = True
                logger.info(
                    f"[WAVE61] ORB window complete — high={self._or_high} low={self._or_low} "
                    f"ticks={self._tick_count}"
                )
                return

        # Build the range
        if self._or_high is None or price > self._or_high:
            self._or_high = price
        if self._or_low is None or price < self._or_low:
            self._or_low = price
        self._tick_count += 1

    def is_signal_blocked(self, signal: str) -> bool:
        """
        Returns True if the signal should be blocked.
        signal: 'BUY' or 'SELL'

        Blocks only when:
        - Window is complete (30 min has passed)
        - At least MIN_TICKS recorded
        - Price is NOT breaking out in the signal direction
        """
        if not self._window_complete:
            return False
        if self._tick_count < _MIN_TICKS:
            return False
        if self._or_high is None or self._or_low is None:
            return False

        price = self._last_price

        if signal == "BUY" and price <= self._or_high:
            logger.debug(
                f"[WAVE61] ORB BUY blocked — price {price:.2f} not above OR_high {self._or_high:.2f}"
            )
            return True

        if signal == "SELL" and price >= self._or_low:
            logger.debug(
                f"[WAVE61] ORB SELL blocked — price {price:.2f} not below OR_low {self._or_low:.2f}"
            )
            return True

        return False

    def get_range_pips(self) -> float:
        """Return the opening range size in pips (XAUUSD: 1 pip = 0.01)."""
        if self._or_high is None or self._or_low is None:
            return 0.0
        return round((self._or_high - self._or_low) / 0.01, 1)

    def info(self) -> dict:
        return {
            "in_window": self._in_window,
            "window_complete": self._window_complete,
            "or_high": self._or_high,
            "or_low": self._or_low,
            "range_pips": self.get_range_pips(),
            "tick_count": self._tick_count,
            "last_price": self._last_price,
        }


# Module-level singleton
opening_range_breakout = OpeningRangeBreakout()
