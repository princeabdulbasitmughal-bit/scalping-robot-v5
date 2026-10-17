"""
Wave 39: DrawdownPause
If equity drops > 1.5% from peak in the last 30 minutes → pause all entries for 15 minutes.
"""
import math
import time
import logging
import threading
from collections import deque

logger = logging.getLogger(__name__)


class DrawdownPause:
    """
    Monitors rolling equity. If equity falls > DRAWDOWN_PCT from the 30-minute high,
    blocks new entries for PAUSE_SEC seconds to let the market stabilize.
    """

    WINDOW_SEC: float = 1800.0     # 30-minute lookback window
    DRAWDOWN_PCT: float = 1.5      # trigger threshold (%)
    PAUSE_SEC: float = 900.0       # 15-minute block

    def __init__(self) -> None:
        # deque of (timestamp, equity) tuples
        self._equity_history: deque = deque(maxlen=4000)
        self._blocked_until: float = 0.0
        self._last_trigger_reason: str = ""
        self._lock = threading.RLock()

    def reset(self) -> None:
        """Reset equity history, triggers, and unblock."""
        with self._lock:
            self._equity_history.clear()
            self._blocked_until = 0.0
            self._last_trigger_reason = ""

    # ------------------------------------------------------------------
    def update(self, equity: float, now_ts: float = None) -> None:
        """Call every tick / position check with the current equity value."""
        if (
            equity is None
            or not isinstance(equity, (int, float))
            or not math.isfinite(equity)
            or equity <= 0
        ):
            return

        now = now_ts if now_ts is not None else time.time()
        with self._lock:
            self._equity_history.append((now, float(equity)))
            # Prune stale entries older than WINDOW_SEC
            cutoff = now - self.WINDOW_SEC
            while self._equity_history and self._equity_history[0][0] < cutoff:
                self._equity_history.popleft()

    # ------------------------------------------------------------------
    def is_entry_blocked(self, balance: float = None, now_ts: float = None) -> bool:
        """Return True if entries should be paused due to recent drawdown."""
        now = now_ts if now_ts is not None else time.time()
        if balance is not None:
            self.update(balance, now_ts=now)

        with self._lock:
            if now < self._blocked_until:
                remaining = self._blocked_until - now
                logger.debug(
                    f"[DRAWDOWN PAUSE] Entry blocked for {remaining:.0f}s more — {self._last_trigger_reason}"
                )
                return True

            # Prune stale entries older than WINDOW_SEC using current now
            cutoff = now - self.WINDOW_SEC
            while self._equity_history and self._equity_history[0][0] < cutoff:
                self._equity_history.popleft()

            if len(self._equity_history) < 2:
                return False

            # Find peak equity in the window
            peak = max(eq for _, eq in self._equity_history)
            current = self._equity_history[-1][1]

            if peak <= 0:
                return False

            drawdown_pct = (peak - current) / peak * 100.0
            if drawdown_pct >= self.DRAWDOWN_PCT:
                self._blocked_until = now + self.PAUSE_SEC
                self._last_trigger_reason = (
                    f"peak=${peak:.2f} current=${current:.2f} drawdown={drawdown_pct:.2f}%"
                )
                logger.warning(
                    f"[DRAWDOWN PAUSE] Triggered — {self._last_trigger_reason}; "
                    f"pausing entries for {self.PAUSE_SEC:.0f}s"
                )
                return True

            return False

    # ------------------------------------------------------------------
    def seconds_remaining(self, now_ts: float = None) -> float:
        now = now_ts if now_ts is not None else time.time()
        with self._lock:
            return max(0.0, self._blocked_until - now)

    def info(self, now_ts: float = None) -> dict:
        now = now_ts if now_ts is not None else time.time()
        with self._lock:
            peak = max((eq for _, eq in self._equity_history), default=0.0)
            current = self._equity_history[-1][1] if self._equity_history else 0.0
            dd = (peak - current) / peak * 100.0 if peak > 0 else 0.0
            return {
                "blocked": now < self._blocked_until,
                "blocked_until": self._blocked_until,
                "seconds_remaining": max(0.0, self._blocked_until - now),
                "drawdown_pct": round(dd, 3),
                "peak_equity": round(peak, 2),
                "current_equity": round(current, 2),
                "history_points": len(self._equity_history),
                "last_reason": self._last_trigger_reason,
            }


# Module-level singleton
drawdown_pause = DrawdownPause()
