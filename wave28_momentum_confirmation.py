"""
Wave 28: Momentum Confirmation
-------------------------------
Requires price to be actively moving in the signal direction for the last
N ticks before an entry is allowed.  This filters out stale signals where
the indicator fired but price has already reversed.

Logic:
- Maintain a rolling buffer of the last `lookback` tick prices.
- BUY  signal: require `min_ticks_in_dir` of the last `lookback` ticks to
  be strictly ascending (each tick >= previous tick).
- SELL signal: require `min_ticks_in_dir` of the last `lookback` ticks to
  be strictly descending.
- If momentum does not confirm, the signal is rejected with reason string.

Default parameters (conservative):
  lookback = 5 ticks
  min_ticks_in_dir = 3  (3 out of 5 ticks must move in signal direction)
"""
from __future__ import annotations
import logging
from collections import deque
from typing import Tuple

logger = logging.getLogger(__name__)


class MomentumConfirmation:
    """
    Validates that recent price ticks align with the proposed trade direction.

    Parameters
    ----------
    lookback          : number of recent ticks to examine
    min_ticks_in_dir  : how many of those ticks must move in signal direction
    """

    def __init__(
        self,
        lookback: int = 5,
        min_ticks_in_dir: int = 3,
    ):
        self._lookback          = lookback
        self._min_ticks_in_dir  = min_ticks_in_dir
        self._price_buffer: deque[float] = deque(maxlen=lookback + 1)
        self._total_rejections: int = 0

    # ------------------------------------------------------------------ #
    #  Public API                                                           #
    # ------------------------------------------------------------------ #

    def update_price(self, price: float) -> None:
        """Push the latest tick price into the buffer."""
        self._price_buffer.append(float(price))

    def is_momentum_confirmed(self, signal: str) -> Tuple[bool, str]:
        """
        Returns (True, "") if momentum aligns with `signal` ("BUY"/"SELL"),
        or (False, reason) if not.

        If there are not enough ticks yet, defaults to allowing the trade.
        """
        if signal not in ("BUY", "SELL"):
            return True, ""  # HOLD or unknown — not our concern

        prices = list(self._price_buffer)
        if len(prices) < 2:
            return True, "MOMENTUM: insufficient tick data — allowing"

        # Count ticks moving in the signal direction
        up_ticks   = sum(1 for i in range(1, len(prices)) if prices[i] >= prices[i - 1])
        down_ticks = sum(1 for i in range(1, len(prices)) if prices[i] <= prices[i - 1])
        total_ticks = len(prices) - 1

        if signal == "BUY":
            confirmed = up_ticks >= self._min_ticks_in_dir
            if not confirmed:
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
                self._total_rejections += 1
                reason = (
                    f"MOMENTUM: SELL rejected — only {down_ticks}/{total_ticks} "
                    f"down-ticks (need {self._min_ticks_in_dir})"
                )
                logger.debug("[WAVE28] %s", reason)
                return False, reason

        return True, ""

    def info(self) -> dict:
        """Return status dict for live_status.json."""
        prices = list(self._price_buffer)
        if len(prices) >= 2:
            up_ticks   = sum(1 for i in range(1, len(prices)) if prices[i] >= prices[i - 1])
            down_ticks = sum(1 for i in range(1, len(prices)) if prices[i] <= prices[i - 1])
            total      = len(prices) - 1
        else:
            up_ticks = down_ticks = total = 0

        return {
            "buffer_size": len(prices),
            "up_ticks": up_ticks,
            "down_ticks": down_ticks,
            "total_ticks": total,
            "min_required": self._min_ticks_in_dir,
            "total_rejections": self._total_rejections,
        }


# Module-level singleton
momentum_confirmation = MomentumConfirmation()
