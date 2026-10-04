"""
Wave 54: Max Spread Cost Per Trade
Checks the current live spread (in pips) BEFORE opening any trade.
If the spread exceeds MAX_SPREAD_PIPS for this specific tick, block entry.
This is a per-tick check (not daily aggregation — that's Wave 49).

Default: 2.5 pips maximum spread allowed for entry.
"""

import time
import logging

logger = logging.getLogger(__name__)

MAX_SPREAD_PIPS = 2.5   # Maximum allowed spread in pips at entry


class MaxSpreadPerTrade:
    """
    Single-trade spread cap guard.
    Receives the current bid/ask spread each tick and blocks entry
    if it exceeds the configured cap.
    """

    def __init__(self, max_spread_pips: float = MAX_SPREAD_PIPS):
        self._max_spread = max_spread_pips
        self._current_spread: float = 0.0
        self._last_update: float = 0.0
        self._block_count: int = 0
        self._allow_count: int = 0
        self._update_count: int = 0
        self._created_at = time.time()

    def update(self, spread_pips: float):
        """
        Feed the current spread in pips.
        Call every tick with the live bid-ask spread.
        """
        try:
            self._current_spread = max(0.0, float(spread_pips))
            self._last_update = time.time()
            self._update_count += 1
        except Exception as e:
            logger.debug(f"[W54-SpreadCap] update error: {e}")

    def is_entry_blocked(self) -> bool:
        """
        Return True if current spread exceeds the per-trade maximum.
        Should be called at signal generation time.
        """
        try:
            if self._current_spread <= 0.0:
                # No spread data yet — allow (fail-open)
                return False

            if self._current_spread > self._max_spread:
                self._block_count += 1
                logger.warning(
                    f"[W54-SpreadCap] Entry BLOCKED — spread {self._current_spread:.2f} pips "
                    f"> max {self._max_spread:.2f} pips"
                )
                return True

            self._allow_count += 1
            logger.debug(
                f"[W54-SpreadCap] Spread OK: {self._current_spread:.2f} pips "
                f"<= {self._max_spread:.2f} pips"
            )
            return False
        except Exception as e:
            logger.debug(f"[W54-SpreadCap] is_entry_blocked error: {e}")
            return False

    def get_spread(self) -> float:
        """Return the most recently observed spread in pips."""
        return round(self._current_spread, 3)

    def info(self) -> dict:
        """Return serializable status dict for live_status.json."""
        try:
            staleness = time.time() - self._last_update if self._last_update > 0 else None
            return {
                "max_spread_pips": self._max_spread,
                "current_spread_pips": round(self._current_spread, 3),
                "is_blocked": self._current_spread > self._max_spread,
                "block_count": self._block_count,
                "allow_count": self._allow_count,
                "update_count": self._update_count,
                "data_staleness_sec": round(staleness, 1) if staleness is not None else None,
            }
        except Exception:
            return {}


# Module-level singleton
max_spread_per_trade = MaxSpreadPerTrade()
