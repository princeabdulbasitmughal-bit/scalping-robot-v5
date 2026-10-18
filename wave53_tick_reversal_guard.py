"""
Wave 53: Tick Reversal Guard
If the last N consecutive ticks all move AGAINST the intended signal direction,
block entry — this detects momentum reversals in real-time.

Example: Signal is BUY, but the last 5 ticks are all lower than previous → block.
Default: N=5 consecutive adverse ticks required to trigger a block.
Block expires after BLOCK_DURATION_SEC seconds (default 30).
"""

import math
import time
import logging
import threading
from collections import deque
from typing import Optional, Tuple, Any

logger = logging.getLogger(__name__)

REVERSAL_TICK_COUNT = 5     # Number of consecutive adverse ticks needed
BLOCK_DURATION_SEC  = 30.0  # Seconds to hold the block after detection


class TickReversalGuard:
    """
    Monitors consecutive tick directions. If N ticks in a row all move
    opposite to the intended trade direction, signals a momentum reversal
    and blocks entry for a short cooldown period.
    Thread-safe with RLock and supports deterministic timestamp injection.
    """

    def __init__(
        self,
        n_ticks: int = REVERSAL_TICK_COUNT,
        block_duration: float = BLOCK_DURATION_SEC,
    ):
        try:
            self._n = max(2, int(n_ticks))
        except (ValueError, TypeError):
            self._n = REVERSAL_TICK_COUNT

        try:
            bd = float(block_duration)
            self._block_duration = bd if math.isfinite(bd) and bd >= 0 else BLOCK_DURATION_SEC
        except (ValueError, TypeError):
            self._block_duration = BLOCK_DURATION_SEC

        self._prices: deque[float] = deque(maxlen=self._n + 1)  # store n+1 to compute n deltas
        self._block_until: float = 0.0
        self._block_count: int = 0
        self._update_count: int = 0
        self._last_reversal_direction: str = ""
        self._created_at = time.time()
        self._lock = threading.RLock()

    def reset(self) -> None:
        """Thread-safe reset of tick prices and block states."""
        with self._lock:
            self._prices.clear()
            self._block_until = 0.0
            self._block_count = 0
            self._update_count = 0
            self._last_reversal_direction = ""
            self._last_trigger_update = -1

    def update(self, price: Any) -> None:
        """Feed the latest tick price."""
        if price is None or isinstance(price, bool):
            return
        try:
            p = float(price)
            if not math.isfinite(p) or p <= 0:
                return
            with self._lock:
                self._prices.append(p)
                self._update_count += 1
        except Exception as e:
            logger.debug(f"[W53-TickReversal] update error: {e}")

    def _consecutive_direction(self) -> str:
        """
        Inspect last N tick deltas.
        Returns 'UP' if all N deltas are positive (price rising consecutively),
                'DOWN' if all N deltas are negative,
                'MIXED' otherwise.
        Must be called under self._lock.
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

    def is_signal_blocked(self, signal: Any, now_ts: Optional[float] = None) -> bool:
        """
        Returns True if signal is blocked due to tick-level momentum reversal.
        signal: 'BUY' or 'SELL'
        """
        try:
            sig = str(signal).strip().upper() if signal is not None else ""
            if sig not in ("BUY", "SELL"):
                return False

            current_time = float(now_ts) if now_ts is not None else time.time()

            with self._lock:
                # Cooldown still active
                if current_time < self._block_until:
                    if (self._last_reversal_direction == "DOWN" and sig == "BUY") or (self._last_reversal_direction == "UP" and sig == "SELL"):
                        remaining = self._block_until - current_time
                        logger.debug(
                            f"[W53-TickReversal] {sig} BLOCKED — reversal cooldown "
                            f"({remaining:.0f}s remaining)"
                        )
                        return True
                    # Signal aligns with momentum direction, not blocked
                    return False

                if self._update_count <= getattr(self, "_last_trigger_update", -1):
                    return False

                direction = self._consecutive_direction()

                # BUY into falling market
                if sig == "BUY" and direction == "DOWN":
                    self._block_until = current_time + self._block_duration
                    self._block_count += 1
                    self._last_reversal_direction = "DOWN"
                    self._last_trigger_update = self._update_count
                    logger.warning(
                        f"[W53-TickReversal] BUY BLOCKED — {self._n} consecutive DOWN ticks "
                        f"(reversal block for {self._block_duration:.0f}s)"
                    )
                    return True

                # SELL into rising market
                if sig == "SELL" and direction == "UP":
                    self._block_until = current_time + self._block_duration
                    self._block_count += 1
                    self._last_reversal_direction = "UP"
                    self._last_trigger_update = self._update_count
                    logger.warning(
                        f"[W53-TickReversal] SELL BLOCKED — {self._n} consecutive UP ticks "
                        f"(reversal block for {self._block_duration:.0f}s)"
                    )
                    return True

                return False
        except Exception as e:
            logger.debug(f"[W53-TickReversal] is_signal_blocked error: {e}")
            return True  # fail-closed

    def is_entry_blocked(self, signal: Any = "BUY", now_ts: Optional[float] = None) -> bool:
        """Alias for is_signal_blocked."""
        return self.is_signal_blocked(signal, now_ts=now_ts)

    def is_blocked(self, signal: Any = "BUY", now_ts: Optional[float] = None) -> bool:
        """Alias for is_signal_blocked."""
        return self.is_signal_blocked(signal, now_ts=now_ts)

    def is_trading_allowed(self, signal: Any = "BUY", now_ts: Optional[float] = None) -> Tuple[bool, str]:
        """Returns (True, '') if clear, (False, reason) if blocked."""
        blocked = self.is_signal_blocked(signal, now_ts=now_ts)
        if blocked:
            with self._lock:
                current_time = float(now_ts) if now_ts is not None else time.time()
                rem = max(0.0, self._block_until - current_time)
                return False, f"TICK_REVERSAL: {self._last_reversal_direction} momentum contradicts {signal} ({rem:.0f}s left)"
        return True, ""

    def info(self, now_ts: Optional[float] = None) -> dict:
        current_time = float(now_ts) if now_ts is not None else time.time()
        with self._lock:
            rem = max(0.0, self._block_until - current_time)
            return {
                "wave": 53,
                "name": "TickReversalGuard",
                "n_ticks_threshold": self._n,
                "block_duration_sec": self._block_duration,
                "is_blocked": current_time < self._block_until,
                "cooldown_remaining_sec": round(rem, 1),
                "last_reversal_direction": self._last_reversal_direction,
                "block_count": self._block_count,
                "update_count": self._update_count,
                "prices_in_buffer": len(self._prices),
            }


# Module-level singleton
tick_reversal_guard = TickReversalGuard()

# Module-level aliases for risk orchestrator integration
def is_entry_blocked(signal: Any = "BUY", now_ts: Optional[float] = None) -> bool:
    return tick_reversal_guard.is_entry_blocked(signal=signal, now_ts=now_ts)

def is_blocked(signal: Any = "BUY", now_ts: Optional[float] = None) -> bool:
    return tick_reversal_guard.is_blocked(signal=signal, now_ts=now_ts)

def update(price: Any) -> None:
    tick_reversal_guard.update(price)

def reset() -> None:
    tick_reversal_guard.reset()
