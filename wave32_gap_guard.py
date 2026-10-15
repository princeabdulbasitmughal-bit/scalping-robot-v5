"""
Wave 32: Gap Guard
Detects large price gaps between consecutive ticks and blocks trading
during the dangerous gap-fill zone.

Logic:
  - If |current_price - last_price| > gap_threshold_pips: trigger block
  - Block lasts block_duration_sec (default 120s) after gap detected
  - Log gap size and direction
"""

import math
import time
import logging
import threading

logger = logging.getLogger(__name__)


class GapGuard:
    def __init__(
        self,
        gap_threshold_pips: float = 5.0,
        block_duration_sec: float = 120.0,
        pip_size: float = 0.1,
    ):
        self._pip_size = max(float(pip_size), 1e-6)  # guard against zero pip_size
        self._gap_threshold = gap_threshold_pips * self._pip_size  # in price units
        self._block_duration = block_duration_sec
        self._last_price: float = 0.0
        self._gap_detected_at: float = 0.0
        self._last_gap_pips: float = 0.0
        self._total_gaps: int = 0
        self._total_blocks: int = 0
        self._created_at: float = time.monotonic()
        self._lock = threading.Lock()

    def update_price(self, price: float) -> None:
        """Feed latest tick. Triggers block if gap is detected."""
        try:
            price = float(price)
            if not math.isfinite(price):
                return
            with self._lock:
                if self._last_price > 0:
                    gap_raw = abs(price - self._last_price)
                    if gap_raw >= self._gap_threshold:
                        self._gap_detected_at = time.monotonic()
                        self._last_gap_pips = round(gap_raw / self._pip_size, 1)
                        self._total_gaps += 1
                        self._total_blocks += 1
                        logger.warning(
                            f"[WAVE32] GAP detected: {self._last_gap_pips:.1f} pips — "
                            f"blocking for {self._block_duration}s"
                        )
                self._last_price = price
        except Exception as e:
            logger.debug(f"[WAVE32] update_price error: {e}")

    def update(self, price: float) -> None:
        """Alias for update_price."""
        self.update_price(price)

    def is_trading_allowed(self) -> tuple:
        """
        Returns (allowed: bool, reason: str).
        allowed=False means a gap was recently detected; avoid trading.
        """
        with self._lock:
            if self._gap_detected_at == 0:
                return (True, "no_gap")
            elapsed = time.monotonic() - self._gap_detected_at
            if elapsed < self._block_duration:
                remaining = round(self._block_duration - elapsed, 1)
                return (False, f"gap_block_{remaining}s_remaining_gap={self._last_gap_pips}pips")
            return (True, "gap_cleared")

    def info(self) -> dict:
        with self._lock:
            # Inline is_trading_allowed logic — avoids re-acquiring non-reentrant lock (deadlock)
            if self._gap_detected_at == 0:
                allowed, reason = True, "no_gap"
                elapsed = 0.0
                remaining = 0.0
            else:
                elapsed = time.monotonic() - self._gap_detected_at
                if elapsed < self._block_duration:
                    remaining = round(self._block_duration - elapsed, 1)
                    allowed = False
                    reason = f"gap_block_{remaining}s_remaining_gap={self._last_gap_pips}pips"
                else:
                    allowed, reason = True, "gap_cleared"
                    remaining = 0.0
            return {
                "trading_allowed": allowed,
                "reason": reason,
                "last_gap_pips": self._last_gap_pips,
                "block_duration_sec": self._block_duration,
                "cooldown_remaining_sec": round(remaining, 1),
                "total_gaps_detected": self._total_gaps,
                "total_trade_blocks": self._total_blocks,
                "gap_threshold_pips": self._gap_threshold / self._pip_size,
            }



# Module-level singleton
gap_guard = GapGuard(
    gap_threshold_pips=5.0,
    block_duration_sec=120.0,
    pip_size=0.1,
)
