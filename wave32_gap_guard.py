"""
Wave 32: Gap Guard
Detects large price gaps between consecutive ticks and blocks trading
during the dangerous gap-fill zone.

Logic:
  - If |current_price - last_price| > gap_threshold_pips: trigger block
  - Block lasts block_duration_sec (default 120s) after gap detected
  - Log gap size and direction
"""

import time


class GapGuard:
    def __init__(
        self,
        gap_threshold_pips: float = 5.0,
        block_duration_sec: float = 120.0,
        pip_size: float = 0.1,
    ):
        self._gap_threshold = gap_threshold_pips * pip_size  # in price units
        self._block_duration = block_duration_sec
        self._pip_size = pip_size
        self._last_price: float = 0.0
        self._gap_detected_at: float = 0.0
        self._last_gap_pips: float = 0.0
        self._total_gaps: int = 0
        self._total_blocks: int = 0
        self._created_at: float = time.time()

    def update_price(self, price: float) -> None:
        """Feed latest tick. Triggers block if gap is detected."""
        price = float(price)
        if self._last_price > 0:
            gap_raw = abs(price - self._last_price)
            if gap_raw >= self._gap_threshold:
                self._gap_detected_at = time.time()
                self._last_gap_pips = round(gap_raw / self._pip_size, 1)
                self._total_gaps += 1
                self._total_blocks += 1
        self._last_price = price

    def is_trading_allowed(self) -> tuple:
        """
        Returns (allowed: bool, reason: str).
        allowed=False means a gap was recently detected; avoid trading.
        """
        if self._gap_detected_at == 0:
            return (True, "no_gap")
        elapsed = time.time() - self._gap_detected_at
        if elapsed < self._block_duration:
            remaining = round(self._block_duration - elapsed, 1)
            return (False, f"gap_block_{remaining}s_remaining_gap={self._last_gap_pips}pips")
        return (True, "gap_cleared")

    def info(self) -> dict:
        allowed, reason = self.is_trading_allowed()
        elapsed = time.time() - self._gap_detected_at if self._gap_detected_at else 0
        remaining = max(0.0, self._block_duration - elapsed) if self._gap_detected_at else 0.0
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
