"""
Wave 48: Equity High Watermark
Tracks the all-time equity high watermark.
If current equity drops > 2% below the watermark -> 30-minute entry block.
"""

import threading
import time


_DRAWDOWN_THRESHOLD_PCT = 2.0   # percent drop from watermark to trigger block
_BLOCK_DURATION_SEC     = 1800  # 30 minutes


class EquityHighWatermark:
    """Monitors equity high watermark; blocks entries on significant drawdown."""

    def __init__(self, threshold_pct: float = _DRAWDOWN_THRESHOLD_PCT,
                 block_sec: float = _BLOCK_DURATION_SEC):
        self._threshold_pct = threshold_pct
        self._block_sec     = block_sec
        self._watermark     = 0.0
        self._block_until   = 0.0
        self._last_equity   = 0.0
        self._dd_pct        = 0.0
        self._lock          = threading.Lock()

    # ------------------------------------------------------------------
    def update(self, equity: float) -> None:
        """Feed current equity each tick."""
        with self._lock:
            self._last_equity = equity
            if equity > self._watermark:
                self._watermark = equity
            if self._watermark > 0:
                dd = (self._watermark - equity) / self._watermark * 100.0
                self._dd_pct = dd
                if dd >= self._threshold_pct and time.time() > self._block_until:
                    self._block_until = time.time() + self._block_sec

    def is_entry_blocked(self) -> bool:
        with self._lock:
            return time.time() < self._block_until

    def info(self) -> dict:
        with self._lock:
            remaining = max(0.0, self._block_until - time.time())
            return {
                "watermark":       round(self._watermark, 2),
                "last_equity":     round(self._last_equity, 2),
                "drawdown_pct":    round(self._dd_pct, 3),
                "entry_blocked":   time.time() < self._block_until,
                "block_remaining_sec": round(remaining, 1),
            }


# Module-level singleton
equity_high_watermark = EquityHighWatermark()
