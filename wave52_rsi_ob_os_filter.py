"""
Wave 52: RSI Overbought/Oversold Filter
Tracks tick RSI (14-period default).
Blocks BUY if RSI > 75 (overbought).
Blocks SELL if RSI < 25 (oversold).
Advisory warning at 70/30.
"""

import logging
import math
import threading
import time
from collections import deque

logger = logging.getLogger(__name__)

RSI_PERIOD = 14
RSI_OB_BLOCK = 75.0   # Hard block BUY above this
RSI_OS_BLOCK = 25.0   # Hard block SELL below this
RSI_OB_WARN  = 70.0   # Advisory log BUY
RSI_OS_WARN  = 30.0   # Advisory log SELL


class RSIOverboughtOversold:
    """
    Computes Wilder's RSI incrementally on tick closes.
    Blocks BUY at overbought and SELL at oversold extremes.
    """

    def __init__(
        self,
        period: int = RSI_PERIOD,
        ob_block: float = RSI_OB_BLOCK,
        os_block: float = RSI_OS_BLOCK,
        ob_warn: float = RSI_OB_WARN,
        os_warn: float = RSI_OS_WARN,
    ):
        # Validate period (must be integer >= 2)
        try:
            p = int(period)
            self._period = p if p >= 2 else RSI_PERIOD
        except (TypeError, ValueError):
            self._period = RSI_PERIOD

        # Validate block thresholds (0 <= os_block < ob_block <= 100)
        try:
            ob = float(ob_block)
            os_val = float(os_block)
            if math.isfinite(ob) and math.isfinite(os_val) and 0.0 <= os_val < ob <= 100.0:
                self._ob_block = ob
                self._os_block = os_val
            else:
                self._ob_block = RSI_OB_BLOCK
                self._os_block = RSI_OS_BLOCK
        except (TypeError, ValueError):
            self._ob_block = RSI_OB_BLOCK
            self._os_block = RSI_OS_BLOCK

        # Advisory thresholds
        try:
            ob_w = float(ob_warn)
            os_w = float(os_warn)
            self._ob_warn = ob_w if (math.isfinite(ob_w) and self._os_block < ob_w <= self._ob_block) else max(self._os_block, self._ob_block - 5.0)
            self._os_warn = os_w if (math.isfinite(os_w) and self._os_block <= os_w < self._ob_block) else min(self._ob_block, self._os_block + 5.0)
        except (TypeError, ValueError):
            self._ob_warn = RSI_OB_WARN
            self._os_warn = RSI_OS_WARN

        # We need period+1 prices to get period price changes
        self._prices: deque = deque(maxlen=self._period + 1)
        self._rsi: float = 50.0   # neutral default
        self._avg_gain: float = 0.0
        self._avg_loss: float = 0.0
        self._initialized: bool = False
        self._last_update: float = 0.0
        self._update_count: int = 0
        self._created_at = time.time()
        self._lock = threading.RLock()

    def reset(self) -> None:
        """Reset internal filter state."""
        with self._lock:
            self._prices.clear()
            self._rsi = 50.0
            self._avg_gain = 0.0
            self._avg_loss = 0.0
            self._initialized = False
            self._last_update = 0.0
            self._update_count = 0

    def update(self, price: float):
        """Feed a new tick price. Recomputes RSI incrementally."""
        if price is None or isinstance(price, bool):
            return
        try:
            p = float(price)
        except (TypeError, ValueError):
            return
        if not math.isfinite(p) or p <= 0.0:
            return

        try:
            with self._lock:
                self._prices.append(p)
                self._update_count += 1
                self._last_update = time.time()

                n = len(self._prices)
                if n < self._period + 1:
                    return  # Not enough prices to compute full RSI yet

                if not self._initialized:
                    # Initial SMA of gains and losses
                    gains = []
                    losses = []
                    prices = list(self._prices)
                    for i in range(1, len(prices)):
                        diff = prices[i] - prices[i - 1]
                        gains.append(max(diff, 0.0))
                        losses.append(abs(min(diff, 0.0)))

                    self._avg_gain = sum(gains[-self._period:]) / self._period
                    self._avg_loss = sum(losses[-self._period:]) / self._period
                    self._initialized = True
                else:
                    # Wilder's exponential smoothing
                    change = self._prices[-1] - self._prices[-2]
                    gain = max(change, 0.0)
                    loss = abs(min(change, 0.0))
                    self._avg_gain = (self._avg_gain * (self._period - 1) + gain) / self._period
                    self._avg_loss = (self._avg_loss * (self._period - 1) + loss) / self._period

                # Flat market / near-zero delta handling
                if self._avg_loss <= 1e-12:
                    self._rsi = 50.0 if self._avg_gain <= 1e-12 else 100.0
                elif self._avg_gain <= 1e-12:
                    self._rsi = 0.0
                else:
                    rs = self._avg_gain / self._avg_loss
                    self._rsi = 100.0 - (100.0 / (1.0 + rs))

                # Clamp & sanitize
                if not math.isfinite(self._rsi):
                    self._rsi = 50.0
                else:
                    self._rsi = max(0.0, min(100.0, self._rsi))

        except Exception as e:
            logger.debug(f"[W52-RSI] update error: {e}")

    def get_rsi(self) -> float:
        """Return current RSI value (50.0 if not yet initialized)."""
        with self._lock:
            val = self._rsi if math.isfinite(self._rsi) else 50.0
            return round(val, 2)

    @property
    def rsi(self) -> float:
        """Current RSI value."""
        return self.get_rsi()

    def is_signal_blocked(self, signal: str) -> bool:
        """
        Return True if signal should be blocked due to extreme RSI.
        signal: 'BUY' or 'SELL'
        """
        try:
            sig = str(signal).strip().upper()
            if sig not in ("BUY", "SELL"):
                return False

            with self._lock:
                if not self._initialized:
                    return False  # Allow trading before RSI is ready
                rsi_val = self._rsi
                ob_block = self._ob_block
                os_block = self._os_block
                ob_warn = self._ob_warn
                os_warn = self._os_warn

            # Evaluations and logging executed OUTSIDE the lock
            if sig == "BUY" and rsi_val > ob_block:
                logger.warning(
                    f"[W52-RSI] BUY BLOCKED — RSI={rsi_val:.1f} > {ob_block} (overbought)"
                )
                return True

            if sig == "SELL" and rsi_val < os_block:
                logger.warning(
                    f"[W52-RSI] SELL BLOCKED — RSI={rsi_val:.1f} < {os_block} (oversold)"
                )
                return True

            # Advisory warnings (not blocking)
            if sig == "BUY" and rsi_val > ob_warn:
                logger.debug(f"[W52-RSI] BUY warning — RSI={rsi_val:.1f} in overbought zone ({ob_warn}-{ob_block})")
            elif sig == "SELL" and rsi_val < os_warn:
                logger.debug(f"[W52-RSI] SELL warning — RSI={rsi_val:.1f} in oversold zone ({os_block}-{os_warn})")

            return False
        except Exception as e:
            logger.error(f"[W52-RSI] is_signal_blocked error: {e}")
            return True  # fail-closed

    def is_entry_blocked(self, signal: str) -> bool:
        """Alias for is_signal_blocked."""
        return self.is_signal_blocked(signal)

    def is_blocked(self, signal: str) -> bool:
        """Alias for is_signal_blocked."""
        return self.is_signal_blocked(signal)

    def info(self) -> dict:
        """Return serializable status dict for live_status.json."""
        try:
            with self._lock:
                rsi_val = round(self._rsi, 2) if math.isfinite(self._rsi) else 50.0
                return {
                    "wave": 52,
                    "name": "RSIOverboughtOversold",
                    "rsi": rsi_val,
                    "period": self._period,
                    "ob_block_threshold": self._ob_block,
                    "os_block_threshold": self._os_block,
                    "initialized": self._initialized,
                    "update_count": self._update_count,
                    "last_update": self._last_update,
                    "status": (
                        "OVERBOUGHT" if rsi_val > self._ob_block else
                        "OVERSOLD" if rsi_val < self._os_block else
                        "NEUTRAL"
                    ),
                }
        except Exception:
            return {"wave": 52, "name": "RSIOverboughtOversold", "error": "info_failed"}


# Module-level singleton
rsi_filter = RSIOverboughtOversold()

# Module-level aliases for risk orchestrator integration
def is_entry_blocked(signal: str) -> bool:
    return rsi_filter.is_entry_blocked(signal=signal)

def is_blocked(signal: str) -> bool:
    return rsi_filter.is_blocked(signal=signal)

def update(price: float) -> None:
    rsi_filter.update(price)

def get_rsi() -> float:
    return rsi_filter.get_rsi()

def reset() -> None:
    rsi_filter.reset()
