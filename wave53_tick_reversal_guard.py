"""
Wave 53: Tick Reversal Guard
If the last N consecutive ticks all move AGAINST the intended signal direction,
block entry — this detects momentum reversals in real-time.

Example: Signal is BUY, but the last 5 ticks are all lower than previous → block.
Default: N=5 consecutive adverse ticks required to trigger a block.
Block expires after BLOCK_DURATION_SEC seconds (default 30).
"""

import time
import logging
from collections import deque

logger = logging.getLogger(__name__)

REVERSAL_TICK_COUNT = 5     # Number of consecutive adverse ticks needed
BLOCK_DURATION_SEC  = 30    # Seconds to hold the block after detection


class TickReversalGuard:
    """
    Monitors consecutive tick directions. If N ticks in a row all move
    opposite to the intended trade direction, signals a momentum reversal
    and blocks entry for a short cooldown period.
    """

    def __init__(
        self,
        n_ticks: int = REVERSAL_TICK_COUNT,
        block_duration: float = BLOCK_DURATION_SEC,
    ):
        self._n = n_ticks
        self._block_duration = block_duration
        self._prices: deque = deque(maxlen=n_ticks + 1)  # store n+1 to compute n deltas
        self._block_until: float = 0.0
        self._block_count: int = 0
        self._update_count: int = 0
        self._last_reversal_direction: str = ""
        self._created_at = time.time()

    def update(self, price: float):
        """Feed the latest tick price."""
        try:
            self._prices.append(float(price))
            self._update_count += 1
        except Exception as e:
            logger.debug(f"[W53-TickReversal] update error: {e}")

    def _consecutive_direction(self) -> str:
        """
        Inspect last N tick deltas.
        Returns 'UP' if all N deltas are positive (price rising consecutively),
                'DOWN' if all N deltas are negative,
                'MIXED' otherwise.
        """
        prices = list(self._prices)
        if len(prices) < self._n + 1:
            return "MIXED"
        deltas = [prices[i] - prices[i - 1] for i in range(len(prices) - self._n, len(prices))]
        if all(d > 0 for d in deltas):
            return "UP"
        if all(d < 0 for d in deltas):
            return "DOWN"
        return "MIXED"

    def is_signal_blocked(self, signal: str) -> bool:
        """
        Returns True if signal is blocked due to tick-level momentum reversal.
        signal: 'BUY' or 'SELL'
        """
        try:
            now = time.time()

            # Cooldown still active
            if now < self._block_until:
                remaining = self._block_until - now
                logger.debug(
                    f"[W53-TickReversal] {signal} BLOCKED — reversal cooldown "
                    f"({remaining:.0f}s remaining)"
                )
                return True

            direction = self._consecutive_direction()

            # BUY into falling market
            if signal == "BUY" and direction == "DOWN":
                self._block_until = now + self._block_duration
                self._block_count += 1
                self._last_reversal_direction = "DOWN"
                logger.warning(
                    f"[W53-TickReversal] BUY BLOCKED — {self._n} consecutive DOWN ticks "
                    f"(counter-trend). Block for {self._block_duration}s."
                )
                return True

            # SELL into rising market
            if signal == "SELL" and direction == "UP":
                self._block_until = now + self._block_duration
                self._block_count += 1
                self._last_reversal_direction = "UP"
                logger.warning(
                    f"[W53-TickReversal] SELL BLOCKED — {self._n} consecutive UP ticks "
                    f"(counter-trend). Block for {self._block_duration}s."
                )
                return True

            return False
        except Exception as e:
            logger.debug(f"[W53-TickReversal] is_signal_blocked error: {e}")
            return False

    def info(self) -> dict:
        """Return serializable status dict for live_status.json."""
        try:
            now = time.time()
            remaining = max(0.0, self._block_until - now)
            return {
                "n_ticks": self._n,
                "block_duration_sec": self._block_duration,
                "is_blocked": remaining > 0,
                "block_remaining_sec": round(remaining, 1),
                "block_count": self._block_count,
                "last_reversal_direction": self._last_reversal_direction,
                "current_tick_direction": self._consecutive_direction(),
                "update_count": self._update_count,
                "price_buffer_size": len(self._prices),
            }
        except Exception:
            return {}


# Module-level singleton
tick_reversal_guard = TickReversalGuard()
