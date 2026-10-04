"""
Wave 44: PriceVelocityFilter
If price moves more than 5 pips in 3 seconds, skip entry to prevent chasing
fast-moving markets. Keeps track of the last N prices with timestamps.
"""

import time
from collections import deque
import logging

logger = logging.getLogger(__name__)

_VELOCITY_PIPS_LIMIT = 5.0   # pips in the window
_VELOCITY_WINDOW_SEC = 3.0   # look-back window (seconds)
_MAX_HISTORY = 500            # tick buffer cap


class PriceVelocityFilter:
    """Blocks entries when price is moving too fast (chasing prevention)."""

    def __init__(self,
                 pip_limit: float = _VELOCITY_PIPS_LIMIT,
                 window_sec: float = _VELOCITY_WINDOW_SEC):
        self._pip_limit = pip_limit
        self._window_sec = window_sec
        self._history: deque = deque(maxlen=_MAX_HISTORY)  # (timestamp, price)
        self._last_velocity: float = 0.0

    def update(self, price: float) -> None:
        """Feed price each tick."""
        self._history.append((time.time(), price))

    def _velocity_pips(self) -> float:
        """Return max price range (in pips) within the last _window_sec."""
        if len(self._history) < 2:
            return 0.0
        cutoff = time.time() - self._window_sec
        recent = [p for ts, p in self._history if ts >= cutoff]
        if len(recent) < 2:
            return 0.0
        return (max(recent) - min(recent)) * 10.0   # pips for XAUUSD (0.1/pip)

    def is_entry_blocked(self) -> bool:
        """Return True if price is moving too fast to enter safely."""
        self._last_velocity = self._velocity_pips()
        if self._last_velocity > self._pip_limit:
            logger.info(
                f"[WAVE44] Price velocity {self._last_velocity:.1f} pips/"
                f"{self._window_sec:.0f}s exceeds {self._pip_limit:.1f} pip limit — skipping entry"
            )
            return True
        return False

    def info(self) -> dict:
        return {
            "velocity_pips": round(self._last_velocity, 2),
            "pip_limit": self._pip_limit,
            "window_sec": self._window_sec,
            "blocked": self._last_velocity > self._pip_limit,
        }


# Module-level singleton
price_velocity_filter = PriceVelocityFilter()
