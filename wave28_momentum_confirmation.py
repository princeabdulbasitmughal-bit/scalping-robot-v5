"""
Wave 28: Momentum Confirmation
-------------------------------
Requires price to be actively moving in the signal direction for the last
N ticks before an entry is allowed. This filters out stale signals where
the indicator fired but price has already reversed.

Logic:
- Maintain a rolling buffer of the last `lookback` tick prices.
- BUY  signal: require `min_ticks_in_dir` of the last `lookback` ticks to
  be strictly ascending (each tick > previous tick).
- SELL signal: require `min_ticks_in_dir` of the last `lookback` ticks to
  be strictly descending (each tick < previous tick).
- If momentum does not confirm, the signal is rejected with reason string.

Default parameters (conservative):
  lookback = 5 ticks
  min_ticks_in_dir = 3  (3 out of 5 ticks must move in signal direction)
"""
from __future__ import annotations
import math
import logging
import threading
from collections import deque
from typing import Tuple, Any

logger = logging.getLogger(__name__)


class MomentumConfirmation:
    """
    Validates that recent price ticks align with the proposed trade direction.

    Parameters
    ----------
    lookback          : number of recent ticks to examine (must be >= 1)
    min_ticks_in_dir  : how many of those ticks must move in signal direction
    """

    def __init__(
        self,
        lookback: int = 5,
        min_ticks_in_dir: int = 3,
    ):
        self._lookback = max(1, int(lookback)) if isinstance(lookback, (int, float)) and not isinstance(lookback, bool) and math.isfinite(lookback) else 5
        raw_min = int(min_ticks_in_dir) if isinstance(min_ticks_in_dir, (int, float)) and not isinstance(min_ticks_in_dir, bool) and math.isfinite(min_ticks_in_dir) else 3
        # min_ticks_in_dir cannot exceed lookback
        self._min_ticks_in_dir = max(1, min(raw_min, self._lookback))
        self._price_buffer: deque[float] = deque(maxlen=self._lookback + 1)
        self._total_rejections: int = 0
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ #
    #  Public API                                                        #
    # ------------------------------------------------------------------ #

    def reset(self) -> None:
        """Thread-safe reset of internal price buffer and statistics."""
        with self._lock:
            self._price_buffer.clear()
            self._total_rejections = 0

    def update_price(self, price: Any) -> None:
        """
        Push the latest tick price into the buffer.
        Rejects None, booleans, non-numerics, NaN, Inf, and non-positive prices.
        """
        if price is None or isinstance(price, bool):
            return
        try:
            p = float(price)
        except (ValueError, TypeError):
            return

        if not math.isfinite(p) or p <= 0.0:
            return

        with self._lock:
            self._price_buffer.append(p)

    def is_momentum_confirmed(self, signal: str) -> Tuple[bool, str]:
        """
        Returns (True, "") if momentum aligns with `signal` ("BUY"/"SELL"),
        or (False, reason) if not.

        If there are not enough ticks yet, defaults to allowing the trade.
        """
        if not isinstance(signal, str):
            return True, ""

        sig = signal.strip().upper()
        if sig not in ("BUY", "SELL"):
            return True, ""  # HOLD or unknown — not our concern

        with self._lock:
            prices = list(self._price_buffer)

        # Need at least min_ticks_in_dir + 1 prices to form min_ticks_in_dir intervals
        if len(prices) <= self._min_ticks_in_dir:
            return True, "MOMENTUM: insufficient tick data — allowing"

        # Count ticks moving strictly in the signal direction
        up_ticks = sum(1 for i in range(1, len(prices)) if prices[i] > prices[i - 1])
        down_ticks = sum(1 for i in range(1, len(prices)) if prices[i] < prices[i - 1])
        total_ticks = len(prices) - 1

        if sig == "BUY":
            confirmed = up_ticks >= self._min_ticks_in_dir
            if not confirmed:
                with self._lock:
                    self._total_rejections += 1
                reason = (
                    f"MOMENTUM: BUY rejected — only {up_ticks}/{total_ticks} "
                    f"up-ticks (need {self._min_ticks_in_dir})"
                )
                logger.debug("[WAVE28] %s", reason)
                return False, reason
        else:  # SELL
            confirmed = down_ticks >= self._min_ticks_in_dir
            if not confirmed:
                with self._lock:
                    self._total_rejections += 1
                reason = (
                    f"MOMENTUM: SELL rejected — only {down_ticks}/{total_ticks} "
                    f"down-ticks (need {self._min_ticks_in_dir})"
                )
                logger.debug("[WAVE28] %s", reason)
                return False, reason

        return True, ""

    def is_entry_blocked(self, signal: str = "BUY") -> bool:
        """Unified risk interface check for trade entry blocking."""
        confirmed, _ = self.is_momentum_confirmed(signal=signal)
        return not confirmed

    def is_blocked(self, signal: str = "BUY") -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked(signal=signal)

    def info(self) -> dict:
        """Return status dict for live_status.json."""
        with self._lock:
            prices = list(self._price_buffer)
            total_rejections = self._total_rejections

        if len(prices) >= 2:
            # Consistent strict comparison matching is_momentum_confirmed()
            up_ticks = sum(1 for i in range(1, len(prices)) if prices[i] > prices[i - 1])
            down_ticks = sum(1 for i in range(1, len(prices)) if prices[i] < prices[i - 1])
            total = len(prices) - 1
            flat_ticks = total - up_ticks - down_ticks
        else:
            up_ticks = down_ticks = total = flat_ticks = 0

        return {
            "wave": 28,
            "name": "MomentumConfirmation",
            "buffer_size": len(prices),
            "up_ticks": up_ticks,
            "down_ticks": down_ticks,
            "flat_ticks": flat_ticks,
            "total_ticks": total,
            "min_required": self._min_ticks_in_dir,
            "total_rejections": total_rejections,
        }


# Module-level singleton
momentum_confirmation = MomentumConfirmation()


def is_entry_blocked(signal: str = "BUY") -> bool:
    """Module-level risk interface check."""
    return momentum_confirmation.is_entry_blocked(signal=signal)


def is_blocked(signal: str = "BUY") -> bool:
    """Module-level alias for is_entry_blocked."""
    return momentum_confirmation.is_blocked(signal=signal)


def is_momentum_confirmed(signal: str) -> Tuple[bool, str]:
    """Module-level alias for is_momentum_confirmed."""
    return momentum_confirmation.is_momentum_confirmed(signal=signal)


def update_price(price: Any) -> None:
    """Module-level alias for update_price."""
    return momentum_confirmation.update_price(price=price)

