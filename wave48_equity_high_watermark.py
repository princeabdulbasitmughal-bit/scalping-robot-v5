"""
Wave 48: Equity High Watermark
Tracks the all-time equity high watermark.
If current equity drops > 2% below the watermark -> 30-minute entry block.
"""

import math
import threading
import time
import logging
from typing import Optional, Tuple, Any

logger = logging.getLogger(__name__)

_DRAWDOWN_THRESHOLD_PCT = 2.0   # percent drop from watermark to trigger block
_BLOCK_DURATION_SEC     = 1800  # 30 minutes


class EquityHighWatermark:
    """
    Monitors equity high watermark; blocks entries on significant drawdown.
    Thread-safe with RLock and supports deterministic timestamp injection.
    """

    def __init__(
        self,
        threshold_pct: float = _DRAWDOWN_THRESHOLD_PCT,
        block_sec: float = _BLOCK_DURATION_SEC,
    ):
        try:
            tp = float(threshold_pct)
            self._threshold_pct = tp if math.isfinite(tp) and tp > 0 else _DRAWDOWN_THRESHOLD_PCT
        except (ValueError, TypeError):
            self._threshold_pct = _DRAWDOWN_THRESHOLD_PCT

        try:
            bs = float(block_sec)
            self._block_sec = bs if math.isfinite(bs) and bs > 0 else _BLOCK_DURATION_SEC
        except (ValueError, TypeError):
            self._block_sec = _BLOCK_DURATION_SEC

        self._watermark     = 0.0
        self._block_until   = 0.0
        self._last_equity   = 0.0
        self._dd_pct        = 0.0
        self._total_triggers = 0
        self._lock          = threading.RLock()

    def reset(self) -> None:
        """Thread-safe reset of watermark and block state."""
        with self._lock:
            self._watermark = 0.0
            self._block_until = 0.0
            self._last_equity = 0.0
            self._dd_pct = 0.0
            self._total_triggers = 0

    # ------------------------------------------------------------------
    def update(self, equity: Any, now_ts: Optional[float] = None) -> None:
        """Feed current equity each tick."""
        if equity is None or isinstance(equity, bool):
            return
        try:
            eq = float(equity)
            if not math.isfinite(eq) or eq <= 0:
                return
        except (ValueError, TypeError):
            return

        current_time = float(now_ts) if now_ts is not None else time.time()

        with self._lock:
            self._last_equity = eq
            if eq > self._watermark:
                self._watermark = eq
            if self._watermark > 0:
                dd = (self._watermark - eq) / self._watermark * 100.0
                self._dd_pct = round(dd, 4)
                if dd >= self._threshold_pct and current_time >= self._block_until:
                    self._block_until = current_time + self._block_sec
                    self._total_triggers += 1
                    logger.warning(
                        f"[WAVE48] Drawdown {dd:.2f}% >= {self._threshold_pct:.1f}% threshold "
                        f"(Watermark: ${self._watermark:.2f}, Equity: ${eq:.2f}) -> entry blocked for {self._block_sec}s"
                    )

    def is_entry_blocked(self, now_ts: Optional[float] = None) -> bool:
        """Return True if drawdown block is active."""
        try:
            current_time = float(now_ts) if now_ts is not None else time.time()
            with self._lock:
                return current_time < self._block_until
        except Exception:
            return True  # fail-closed

    def is_blocked(self, now_ts: Optional[float] = None) -> bool:
        """Standard alias for is_entry_blocked."""
        return self.is_entry_blocked(now_ts=now_ts)

    def is_trading_allowed(self, now_ts: Optional[float] = None) -> Tuple[bool, str]:
        """Returns (True, '') if clear, (False, reason) if in drawdown block."""
        blocked = self.is_entry_blocked(now_ts=now_ts)
        if blocked:
            with self._lock:
                current_time = float(now_ts) if now_ts is not None else time.time()
                rem = max(0.0, self._block_until - current_time)
                return False, f"WATERMARK_DD: {self._dd_pct:.1f}% drawdown active ({rem:.0f}s left)"
        return True, ""

    def info(self, now_ts: Optional[float] = None) -> dict:
        current_time = float(now_ts) if now_ts is not None else time.time()
        with self._lock:
            remaining = max(0.0, self._block_until - current_time)
            return {
                "wave": 48,
                "name": "EquityHighWatermark",
                "watermark": round(self._watermark, 2),
                "last_equity": round(self._last_equity, 2),
                "drawdown_pct": round(self._dd_pct, 3),
                "entry_blocked": current_time < self._block_until,
                "block_remaining_sec": round(remaining, 1),
                "total_triggers": self._total_triggers,
            }


# Module-level singleton
equity_high_watermark = EquityHighWatermark()

# Module-level aliases for risk orchestrator integration
def is_entry_blocked(now_ts: Optional[float] = None) -> bool:
    return equity_high_watermark.is_entry_blocked(now_ts=now_ts)

def is_blocked(now_ts: Optional[float] = None) -> bool:
    return equity_high_watermark.is_entry_blocked(now_ts=now_ts)

def update(equity: Any, now_ts: Optional[float] = None) -> None:
    equity_high_watermark.update(equity, now_ts=now_ts)

def reset() -> None:
    equity_high_watermark.reset()
