"""
Wave 31: Reversal Detector
Detects RSI overbought/oversold conditions combined with price divergence
and forces or boosts counter-signal direction.

Logic:
  - RSI > 75 (overbought) while price making higher highs → bearish reversal → SELL bias
  - RSI < 25 (oversold)   while price making lower lows   → bullish reversal → BUY bias
  - Provides a suggested signal override and confidence score (0.0–1.0)
"""

import time
from collections import deque


class ReversalDetector:
    def __init__(
        self,
        rsi_period: int = 14,
        overbought: float = 75.0,
        oversold: float = 25.0,
        price_window: int = 5,
        cooldown_sec: float = 60.0,
    ):
        self._rsi_period = rsi_period
        self._overbought = overbought
        self._oversold = oversold
        self._price_window = price_window
        self._cooldown = cooldown_sec

        self._prices: deque = deque(maxlen=rsi_period + 1)
        self._rsi_history: deque = deque(maxlen=price_window)
        self._price_highs: deque = deque(maxlen=price_window)
        self._price_lows: deque = deque(maxlen=price_window)

        self._last_signal: str = "HOLD"
        self._last_signal_time: float = 0.0
        self._total_reversals: int = 0
        self._created_at: float = time.time()

    def _compute_rsi(self) -> float:
        """Simple Wilder RSI from stored price series."""
        prices = list(self._prices)
        if len(prices) < 2:
            return 50.0
        gains, losses = [], []
        for i in range(1, len(prices)):
            delta = prices[i] - prices[i - 1]
            (gains if delta > 0 else losses).append(abs(delta))
        avg_gain = sum(gains) / max(len(gains), 1)
        avg_loss = sum(losses) / max(len(losses), 1)
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def update(self, price: float, rsi: float = None) -> None:
        """Push latest price tick and optional RSI."""
        self._prices.append(float(price))
        if rsi is not None:
            self._rsi_history.append(float(rsi))
        else:
            self._rsi_history.append(self._compute_rsi())
        self._price_highs.append(float(price))
        self._price_lows.append(float(price))

    def update_price(self, price: float) -> None:
        """Push latest price tick and refresh RSI."""
        self.update(price)

    def get_reversal_signal(self) -> tuple:
        """
        Returns (signal: str, confidence: float, reason: str).
        signal is 'BUY', 'SELL', or 'HOLD'.
        """
        now = time.time()
        if now - self._last_signal_time < self._cooldown:
            return ("HOLD", 0.0, "cooldown_active")

        rsi_vals = list(self._rsi_history)
        highs = list(self._price_highs)
        lows = list(self._price_lows)

        if len(rsi_vals) < 3 or len(highs) < 3:
            return ("HOLD", 0.0, "insufficient_data")

        latest_rsi = rsi_vals[-1]
        prev_rsi = rsi_vals[-2]
        latest_high = highs[-1]
        prev_high = highs[-2]
        latest_low = lows[-1]
        prev_low = lows[-2]

        # Bearish divergence: price higher high but RSI lower high (overbought zone)
        if latest_rsi > self._overbought and latest_high > prev_high and latest_rsi < prev_rsi:
            confidence = min((latest_rsi - self._overbought) / 25.0, 1.0)
            self._last_signal = "SELL"
            self._last_signal_time = now
            self._total_reversals += 1
            return ("SELL", round(confidence, 3), "bearish_divergence_overbought")

        # Bullish divergence: price lower low but RSI higher low (oversold zone)
        if latest_rsi < self._oversold and latest_low < prev_low and latest_rsi > prev_rsi:
            confidence = min((self._oversold - latest_rsi) / 25.0, 1.0)
            self._last_signal = "BUY"
            self._last_signal_time = now
            self._total_reversals += 1
            return ("BUY", round(confidence, 3), "bullish_divergence_oversold")

        # Extreme levels without divergence (lower confidence)
        if latest_rsi > self._overbought:
            confidence = min((latest_rsi - self._overbought) / 50.0, 0.5)
            return ("SELL", round(confidence, 3), "overbought_extreme")
        if latest_rsi < self._oversold:
            confidence = min((self._oversold - latest_rsi) / 50.0, 0.5)
            return ("BUY", round(confidence, 3), "oversold_extreme")

        return ("HOLD", 0.0, "no_reversal_condition")

    def info(self) -> dict:
        rsi_vals = list(self._rsi_history)
        current_rsi = rsi_vals[-1] if rsi_vals else 50.0
        return {
            "current_rsi": round(current_rsi, 2),
            "overbought_threshold": self._overbought,
            "oversold_threshold": self._oversold,
            "last_signal": self._last_signal,
            "total_reversals": self._total_reversals,
            "cooldown_sec": self._cooldown,
            "buffer_size": len(self._prices),
        }


# Module-level singleton
reversal_detector = ReversalDetector(
    rsi_period=14,
    overbought=75.0,
    oversold=25.0,
    price_window=5,
    cooldown_sec=60.0,
)
