"""
Wave 44: PriceVelocityFilter
If price moves more than 5 pips in 3 seconds, skip entry to prevent chasing
fast-moving markets. Keeps track of the last N prices with timestamps.
"""

import math
import time
import threading
from collections import deque
import logging
from typing import Optional, Tuple, Any

logger = logging.getLogger(__name__)

_VELOCITY_PIPS_LIMIT = 5.0   # pips in the window
_VELOCITY_WINDOW_SEC = 3.0   # look-back window (seconds)
_MAX_HISTORY = 500            # tick buffer cap


class PriceVelocityFilter:
    """
    Blocks entries when price is moving too fast (chasing prevention).
    Thread-safe with RLock and supports deterministic timestamp injection.
    """

    def __init__(
        self,
        pip_limit: float = _VELOCITY_PIPS_LIMIT,
        window_sec: float = _VELOCITY_WINDOW_SEC,
        pip_size: float = 0.1,
    ):
        try:
            lim = float(pip_limit)
            self._pip_limit = lim if math.isfinite(lim) and lim > 0 else _VELOCITY_PIPS_LIMIT
        except (ValueError, TypeError):
            self._pip_limit = _VELOCITY_PIPS_LIMIT

        try:
            win = float(window_sec)
            self._window_sec = win if math.isfinite(win) and win > 0 else _VELOCITY_WINDOW_SEC
        except (ValueError, TypeError):
            self._window_sec = _VELOCITY_WINDOW_SEC

        try:
            ps = float(pip_size)
            self._pip_size = ps if math.isfinite(ps) and ps > 0 else 0.1
        except (ValueError, TypeError):
            self._pip_size = 0.1

        self._history: deque[Tuple[float, float]] = deque(maxlen=_MAX_HISTORY)  # (timestamp, price)
        self._last_velocity: float = 0.0
        self._total_blocks: int = 0
        self._lock = threading.RLock()

    def reset(self) -> None:
        """Thread-safe reset of internal price history and metrics."""
        with self._lock:
            self._history.clear()
            self._last_velocity = 0.0
            self._total_blocks = 0

    def update(self, price: Any, now_ts: Optional[float] = None) -> None:
        """Feed price each tick."""
        if price is None or isinstance(price, bool):
            return
        try:
            p = float(price)
            if not math.isfinite(p) or p <= 0:
                return
        except (ValueError, TypeError):
            return

        ts = float(now_ts) if now_ts is not None else time.time()
        with self._lock:
            self._history.append((ts, p))

    def _velocity_pips_locked(self, now_ts: Optional[float] = None) -> float:
        """Return max price range (in pips) within the last _window_sec. Must be called with lock."""
        if len(self._history) < 2:
            return 0.0
        current_time = float(now_ts) if now_ts is not None else time.time()
        cutoff = current_time - self._window_sec
        recent = [p for ts, p in self._history if ts >= cutoff]
        if len(recent) < 2:
            return 0.0
        return round((max(recent) - min(recent)) / self._pip_size, 2)

    def is_entry_blocked(self, now_ts: Optional[float] = None) -> bool:
        """Return True if price is moving too fast to enter safely."""
        try:
            with self._lock:
                self._last_velocity = self._velocity_pips_locked(now_ts)
                blocked = self._last_velocity > self._pip_limit
                if blocked:
                    self._total_blocks += 1
            if blocked:
                logger.info(
                    f"[WAVE44] Price velocity {self._last_velocity:.1f} pips/"
                    f"{self._window_sec:.0f}s exceeds {self._pip_limit:.1f} pip limit — skipping entry"
                )
                return True
            return False
        except Exception as exc:
            logger.debug(f"[WAVE44] is_entry_blocked error: {exc}")
            return True  # fail-closed

    def is_blocked(self, now_ts: Optional[float] = None) -> bool:
        """Standard alias for is_entry_blocked."""
        return self.is_entry_blocked(now_ts=now_ts)

    def is_trading_allowed(self, now_ts: Optional[float] = None) -> Tuple[bool, str]:
        """Returns (True, '') if clear, (False, reason) if blocked."""
        blocked = self.is_entry_blocked(now_ts=now_ts)
        if blocked:
            with self._lock:
                return False, f"VELOCITY_LIMIT: {self._last_velocity:.1f}p > {self._pip_limit:.1f}p limit"
        return True, ""

    def info(self) -> dict:
        with self._lock:
            return {
                "wave": 44,
                "name": "PriceVelocityFilter",
                "velocity_pips": round(self._last_velocity, 2),
                "pip_limit": self._pip_limit,
                "window_sec": self._window_sec,
                "blocked": self._last_velocity > self._pip_limit,
                "total_blocks": self._total_blocks,
                "history_length": len(self._history),
            }


# Module-level singleton
price_velocity_filter = PriceVelocityFilter()
