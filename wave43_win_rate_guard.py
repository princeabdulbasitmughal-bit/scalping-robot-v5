"""
Wave 43: WinRateGuard
If the rolling 10-trade win rate drops below 30%, pause new entries for 20 minutes.
This prevents the bot from overtrading during a losing streak.
"""

import time
import threading
from collections import deque
import logging
from typing import Optional

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
        self._min_trades = max(1, int(min_trades))
        t_val = kwargs.get("min_win_rate", threshold if threshold is not None else win_rate_threshold)
        self._threshold = float(t_val)
        p_val = kwargs.get("pause_seconds", pause_sec if pause_sec is not None else pause_duration_sec)
        self._pause_sec = float(p_val)
        # Ensure window is at least min_trades to prevent silent guard deactivation
        self._window = max(window, self._min_trades)
        self._results: deque = deque(maxlen=self._window)   # 1=win, 0=loss
        self._pause_until: float = 0.0
        self._lock = threading.RLock()

    def reset(self) -> None:
        """Reset rolling trade results and clear any active pause."""
        with self._lock:
            self._results.clear()
            self._pause_until = 0.0

    def record_trade(self, won: bool, now_ts: Optional[float] = None) -> None:
        """Call after each trade closes. won=True for win, False for loss."""
        try:
            now = time.time() if now_ts is None else float(now_ts)
            log_warning = False
            log_msg = ""
            with self._lock:
                # If pause just expired, clear stale streak so previous losing run
                # does not immediately re-block on the first post-pause trade
                if self._pause_until > 0 and now >= self._pause_until:
                    self._results.clear()
                    self._pause_until = 0.0

                self._results.append(_WIN if won else _LOSS)
                n = len(self._results)

                # Only evaluate once we have accumulated sufficient sample size
                if n >= self._min_trades:
                    wr = sum(self._results) / n
                    if wr < self._threshold:
                        if now > self._pause_until:  # Don't reset an active pause
                            self._pause_until = now + self._pause_sec
                            log_warning = True
                            mins = self._pause_sec / 60.0
                            log_msg = (
                                f"[WAVE43] Win rate {wr:.0%} on last {n} trades < "
                                f"{self._threshold:.0%} threshold — pausing entries for "
                                f"{mins:.0f} min"
                            )

            if log_warning:
                logger.warning(log_msg)
        except Exception as exc:
            logger.debug(f"[WAVE43] record_trade error: {exc}")

    def _current_win_rate_unsafe(self) -> float:
        """Must be called with self._lock held."""
        n = len(self._results)
        if n == 0:
            return 1.0
        return sum(self._results) / n

    def _current_win_rate(self) -> float:
        with self._lock:
            return self._current_win_rate_unsafe()

    def is_entry_blocked(self, now_ts: Optional[float] = None) -> bool:
        """Return True if entries should be paused."""
        try:
            now = time.time() if now_ts is None else float(now_ts)
            blocked = False
            remaining = 0.0
            with self._lock:
                if now < self._pause_until:
                    remaining = self._pause_until - now
                    blocked = True
                elif self._pause_until > 0:
                    # Pause expired: reset pause timestamp and clear old loss streak
                    self._results.clear()
                    self._pause_until = 0.0

            if blocked:
                logger.debug(f"[WAVE43] Entry blocked — win-rate pause ({remaining:.0f}s left)")
            return blocked
        except Exception as exc:
            logger.debug(f"[WAVE43] is_entry_blocked error: {exc}")
            return True

    def info(self, now_ts: Optional[float] = None) -> dict:
        try:
            now = time.time() if now_ts is None else float(now_ts)
            with self._lock:
                n = len(self._results)
                wr = sum(self._results) / n if n > 0 else 1.0
                remaining = max(0.0, self._pause_until - now)
                thresh = self._threshold
                min_t = self._min_trades

            return {
                "wave": 43,
                "name": "WinRateGuard",
                "win_rate_pct": round(wr * 100, 1),
                "sample_size": n,
                "min_trades": min_t,
                "sufficient_sample": n >= min_t,
                "threshold_pct": round(thresh * 100, 1),
                "paused": remaining > 0,
                "pause_remaining_sec": round(remaining, 1),
            }
        except Exception as exc:
            logger.debug(f"[WAVE43] info error: {exc}")
            return {"wave": 43, "name": "WinRateGuard", "error": "info_failed", "paused": False}


# Module-level singleton
win_rate_guard = WinRateGuard()
