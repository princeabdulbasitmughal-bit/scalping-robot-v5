"""
Wave 52: RSI Overbought/Oversold Filter
Computes RSI(14) on rolling tick prices.
Blocks BUY signals when RSI > 75 (overbought).
Blocks SELL signals when RSI < 25 (oversold).
Advisory log only when RSI is in warning zone (70-75 / 25-30).
"""

import time
import logging
from collections import deque

logger = logging.getLogger(__name__)

RSI_PERIOD = 14
RSI_OB_BLOCK = 75.0   # Block BUY above this
RSI_OS_BLOCK = 25.0   # Block SELL below this
RSI_OB_WARN  = 70.0   # Warn zone upper
RSI_OS_WARN  = 30.0   # Warn zone lower


class RSIOverboughtOversold:
    """
    Computes RSI from tick close prices and blocks counter-trend entries
    at extreme overbought/oversold levels.
    """

    def __init__(
        self,
        period: int = RSI_PERIOD,
        ob_block: float = RSI_OB_BLOCK,
        os_block: float = RSI_OS_BLOCK,
    ):
        self._period = period
        self._ob_block = ob_block
        self._os_block = os_block
        # We need period+1 prices to get period price changes
        self._prices: deque = deque(maxlen=period + 2)
        self._rsi: float = 50.0   # neutral default
        self._avg_gain: float = 0.0
        self._avg_loss: float = 0.0
        self._initialized: bool = False
        self._last_update: float = 0.0
        self._update_count: int = 0
        self._created_at = time.time()

    def update(self, price: float):
        """Feed a new tick price. Recomputes RSI incrementally."""
        try:
            self._prices.append(float(price))
            self._update_count += 1
            self._last_update = time.time()

            n = len(self._prices)
            if n < self._period + 1:
                return  # Not enough data yet

            if not self._initialized:
                # First-time: calculate SMA-seeded avg gain/loss
                changes = [self._prices[i] - self._prices[i - 1] for i in range(1, n)]
                gains = [max(c, 0.0) for c in changes]
                losses = [abs(min(c, 0.0)) for c in changes]
                self._avg_gain = sum(gains[-self._period:]) / self._period
                self._avg_loss = sum(losses[-self._period:]) / self._period
                self._initialized = True
            else:
                # Wilder's smoothing (EMA-style)
                change = self._prices[-1] - self._prices[-2]
                gain = max(change, 0.0)
                loss = abs(min(change, 0.0))
                self._avg_gain = (self._avg_gain * (self._period - 1) + gain) / self._period
                self._avg_loss = (self._avg_loss * (self._period - 1) + loss) / self._period

            if self._avg_loss == 0.0:
                self._rsi = 100.0
            else:
                rs = self._avg_gain / self._avg_loss
                self._rsi = 100.0 - (100.0 / (1.0 + rs))

        except Exception as e:
            logger.debug(f"[W52-RSI] update error: {e}")

    def get_rsi(self) -> float:
        """Return current RSI value (50.0 if not yet initialized)."""
        return round(self._rsi, 2)

    def is_signal_blocked(self, signal: str) -> bool:
        """
        Return True if signal should be blocked due to extreme RSI.
        signal: 'BUY' or 'SELL'
        """
        try:
            if not self._initialized:
                return False  # Allow trading before RSI is ready

            if signal == "BUY" and self._rsi > self._ob_block:
                logger.warning(
                    f"[W52-RSI] BUY BLOCKED — RSI={self._rsi:.1f} > {self._ob_block} (overbought)"
                )
                return True

            if signal == "SELL" and self._rsi < self._os_block:
                logger.warning(
                    f"[W52-RSI] SELL BLOCKED — RSI={self._rsi:.1f} < {self._os_block} (oversold)"
                )
                return True

            # Advisory warnings (not blocking)
            if signal == "BUY" and self._rsi > RSI_OB_WARN:
                logger.debug(f"[W52-RSI] BUY warning — RSI={self._rsi:.1f} in overbought zone ({RSI_OB_WARN}-{self._ob_block})")
            elif signal == "SELL" and self._rsi < RSI_OS_WARN:
                logger.debug(f"[W52-RSI] SELL warning — RSI={self._rsi:.1f} in oversold zone ({self._os_block}-{RSI_OS_WARN})")

            return False
        except Exception as e:
            logger.debug(f"[W52-RSI] is_signal_blocked error: {e}")
            return False

    def info(self) -> dict:
        """Return serializable status dict for live_status.json."""
        try:
            return {
                "rsi": round(self._rsi, 2),
                "period": self._period,
                "ob_block_threshold": self._ob_block,
                "os_block_threshold": self._os_block,
                "initialized": self._initialized,
                "update_count": self._update_count,
                "status": (
                    "OVERBOUGHT" if self._rsi > self._ob_block else
                    "OVERSOLD" if self._rsi < self._os_block else
                    "NEUTRAL"
                ),
            }
        except Exception:
            return {}


# Module-level singleton
rsi_ob_os_filter = RSIOverboughtOversold()
