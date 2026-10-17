"""
Wave 54: Max Spread Cost Per Trade
Checks the current live spread (in pips) BEFORE opening any trade.
If the spread exceeds MAX_SPREAD_PIPS for this specific tick, block entry.
This is a per-tick check (not daily aggregation — that's Wave 49).

Default: 2.5 pips maximum spread allowed for entry.
"""

import math
import time
import logging
import threading
from typing import Optional, Tuple, Any

logger = logging.getLogger(__name__)

MAX_SPREAD_PIPS = 2.5   # Maximum allowed spread in pips at entry


class MaxSpreadPerTrade:
    """
    Single-trade spread cap guard.
    Receives the current bid/ask spread each tick and blocks entry
    if it exceeds the configured cap.
    Thread-safe with RLock and direct spread check support.
    """

    def __init__(self, max_spread_pips: float = MAX_SPREAD_PIPS):
        try:
            m = float(max_spread_pips)
            self._max_spread = m if math.isfinite(m) and m > 0 else MAX_SPREAD_PIPS
        except (ValueError, TypeError):
            self._max_spread = MAX_SPREAD_PIPS

        self._current_spread: float = 0.0
        self._last_update: float = 0.0
        self._block_count: int = 0
        self._allow_count: int = 0
        self._update_count: int = 0
        self._created_at = time.time()
        self._lock = threading.RLock()

    def reset(self) -> None:
        """Thread-safe reset of internal spread metrics."""
        with self._lock:
            self._current_spread = 0.0
            self._last_update = 0.0
            self._block_count = 0
            self._allow_count = 0
            self._update_count = 0

    def update(self, spread_pips: Any) -> None:
        """
        Feed the current spread in pips.
        Call every tick with the live bid-ask spread.
        """
        if spread_pips is None or isinstance(spread_pips, bool):
            return
        try:
            sp = float(spread_pips)
            if not math.isfinite(sp) or sp < 0:
                return
            with self._lock:
                self._current_spread = sp
                self._last_update = time.time()
                self._update_count += 1
        except (ValueError, TypeError):
            return

    def is_entry_blocked(self, spread_pips: Optional[Any] = None) -> bool:
        """
        Return True if current or provided spread exceeds the per-trade maximum.
        """
        try:
            with self._lock:
                if spread_pips is not None:
                    try:
                        sp = float(spread_pips)
                        if not math.isfinite(sp) or sp <= 0.0:
                            return True  # invalid candidate spread fails closed
                    except (ValueError, TypeError):
                        return True
                else:
                    sp = self._current_spread

                if sp <= 0.0:
                    # No spread data yet — allow (fail-open)
                    return False

                if sp > self._max_spread:
                    self._block_count += 1
                    logger.warning(
                        f"[W54-SpreadCap] Entry BLOCKED — spread {sp:.2f} pips "
                        f"> max {self._max_spread:.2f} pips"
                    )
                    return True

                self._allow_count += 1
                return False
        except Exception as e:
            logger.error(f"[W54-SpreadCap] is_entry_blocked error: {e}")
            return True  # fail-closed

    def is_blocked(self, spread_pips: Optional[Any] = None) -> bool:
        """Standard alias for is_entry_blocked."""
        return self.is_entry_blocked(spread_pips=spread_pips)

    def is_trading_allowed(self, spread_pips: Optional[Any] = None) -> Tuple[bool, str]:
        """Returns (True, '') if clear, (False, reason) if blocked."""
        blocked = self.is_entry_blocked(spread_pips=spread_pips)
        if blocked:
            with self._lock:
                sp = float(spread_pips) if spread_pips is not None else self._current_spread
                return False, f"SPREAD_TOO_HIGH: {sp:.2f}p > {self._max_spread:.2f}p limit"
        return True, ""

    def get_spread(self) -> float:
        """Return the most recently observed spread in pips."""
        with self._lock:
            return round(self._current_spread, 3)

    def info(self) -> dict:
        """Return serializable status dict for live_status.json."""
        try:
            with self._lock:
                staleness = time.time() - self._last_update if self._last_update > 0 else None
                return {
                    "wave": 54,
                    "name": "MaxSpreadPerTrade",
                    "max_spread_pips": self._max_spread,
                    "current_spread_pips": round(self._current_spread, 3),
                    "is_blocked": self._current_spread > self._max_spread,
                    "block_count": self._block_count,
                    "allow_count": self._allow_count,
                    "update_count": self._update_count,
                    "data_staleness_sec": round(staleness, 1) if staleness is not None else None,
                }
        except Exception:
            return {"wave": 54, "name": "MaxSpreadPerTrade", "error": "info_failed"}


# Module-level singleton
max_spread_per_trade = MaxSpreadPerTrade()
