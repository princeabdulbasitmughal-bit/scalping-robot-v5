"""
Wave 43: WinRateGuard
If the rolling 10-trade win rate drops below 30%, pause new entries for 20 minutes.
This prevents the bot from overtrading during a losing streak.
"""

import time
from collections import deque
import logging

logger = logging.getLogger(__name__)

_WIN = 1
_LOSS = 0

_MIN_TRADES_TO_JUDGE = 5   # Need at least this many trades before applying guard
_WIN_RATE_THRESHOLD = 0.30  # 30%
_PAUSE_DURATION_SEC = 1200  # 20 minutes


class WinRateGuard:
    """Pauses entries when rolling win rate is too low."""

    def __init__(self,
                 min_trades: int = _MIN_TRADES_TO_JUDGE,
                 win_rate_threshold: float = _WIN_RATE_THRESHOLD,
                 pause_duration_sec: float = _PAUSE_DURATION_SEC,
                 window: int = 10,
                 threshold: float = None,
                 pause_sec: float = None,
                 **kwargs):
        self._min_trades = min_trades
        self._threshold = threshold if threshold is not None else win_rate_threshold
        self._pause_sec = pause_sec if pause_sec is not None else pause_duration_sec
        self._window = window
        self._results: deque = deque(maxlen=window)   # 1=win, 0=loss
        self._pause_until: float = 0.0

    def record_trade(self, won: bool) -> None:
        """Call after each trade closes. won=True for win, False for loss."""
        self._results.append(_WIN if won else _LOSS)
        wr = self._current_win_rate()
        n = len(self._results)
        if n >= self._min_trades and wr < self._threshold:
            if time.time() > self._pause_until:          # Don't reset an active pause
                self._pause_until = time.time() + self._pause_sec
                logger.warning(
                    f"[WAVE43] Win rate {wr:.0%} on last {n} trades < "
                    f"{self._threshold:.0%} threshold — pausing entries for "
                    f"{self._pause_sec / 60:.0f} min"
                )

    def _current_win_rate(self) -> float:
        if not self._results:
            return 1.0
        return sum(self._results) / len(self._results)

    def is_entry_blocked(self) -> bool:
        """Return True if entries should be paused."""
        if time.time() < self._pause_until:
            remaining = self._pause_until - time.time()
            logger.info(f"[WAVE43] Entry blocked — win-rate pause ({remaining:.0f}s left)")
            return True
        return False

    def info(self) -> dict:
        wr = self._current_win_rate()
        remaining = max(0.0, self._pause_until - time.time())
        return {
            "win_rate_pct": round(wr * 100, 1),
            "sample_size": len(self._results),
            "threshold_pct": self._threshold * 100,
            "paused": remaining > 0,
            "pause_remaining_sec": round(remaining, 1),
        }


# Module-level singleton
win_rate_guard = WinRateGuard()
