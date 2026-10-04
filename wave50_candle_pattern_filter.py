"""
Wave 50: Candle Pattern Filter
Detects last candle pattern (doji, hammer, bearish_engulfing, bullish_engulfing).
If pattern contradicts signal direction -> block entry.
Pattern    | Bias     | Blocks
-----------|----------|--------------------
Doji       | NEUTRAL  | blocks both (indecision)
Hammer     | BULLISH  | blocks SELL
Inv Hammer | BEARISH  | blocks BUY
Bull Engulf| BULLISH  | blocks SELL
Bear Engulf| BEARISH  | blocks BUY
"""

import threading
import time
from collections import deque


class CandlePatternFilter:
    """Analyses last 2 synthetic candles built from price ticks."""

    def __init__(self):
        # We accumulate ticks into 1-min candles via tick timestamp
        self._ticks: deque = deque(maxlen=500)
        self._last_pattern = "NONE"
        self._last_bias    = "NEUTRAL"   # BULLISH / BEARISH / NEUTRAL / INDECISION
        self._lock         = threading.Lock()
        self._last_update  = 0.0

    # ------------------------------------------------------------------
    def update(self, price: float) -> None:
        """Feed each tick price."""
        with self._lock:
            self._ticks.append((time.time(), price))
            self._last_update = time.time()
            self._analyse()

    def _build_candle(self, ticks):
        """Build O/H/L/C from a list of (ts, price) tuples."""
        if not ticks:
            return None
        prices = [p for _, p in ticks]
        return {
            "o": prices[0],
            "h": max(prices),
            "l": min(prices),
            "c": prices[-1],
        }

    def _analyse(self):
        now = time.time()
        # Split ticks into two 30-sec candles
        c2_ticks = [(t, p) for t, p in self._ticks if now - t <= 30]
        c1_ticks = [(t, p) for t, p in self._ticks if 30 < now - t <= 60]
        c2 = self._build_candle(c2_ticks)
        c1 = self._build_candle(c1_ticks)
        if c2 is None:
            self._last_pattern = "NONE"
            self._last_bias    = "NEUTRAL"
            return
        # Analyse c2 (most recent candle)
        body = abs(c2["c"] - c2["o"])
        rng  = c2["h"] - c2["l"]
        if rng == 0:
            self._last_pattern = "FLAT"
            self._last_bias    = "NEUTRAL"
            return
        body_ratio = body / rng
        upper_wick = c2["h"] - max(c2["o"], c2["c"])
        lower_wick = min(c2["o"], c2["c"]) - c2["l"]
        bullish_candle = c2["c"] > c2["o"]

        # Doji: body < 10% of range
        if body_ratio < 0.10:
            self._last_pattern = "DOJI"
            self._last_bias    = "INDECISION"
            return

        # Hammer: lower wick > 2x body, upper wick small
        if lower_wick > 2 * body and upper_wick < body:
            self._last_pattern = "HAMMER"
            self._last_bias    = "BULLISH"
            return

        # Inverted hammer / shooting star: upper wick > 2x body
        if upper_wick > 2 * body and lower_wick < body:
            self._last_pattern = "INV_HAMMER"
            self._last_bias    = "BEARISH"
            return

        # Engulfing (needs c1)
        if c1 is not None:
            c1_body = abs(c1["c"] - c1["o"])
            # Bullish engulfing: c1 bearish, c2 bullish and body > c1 body
            if c1["c"] < c1["o"] and bullish_candle and body > c1_body:
                self._last_pattern = "BULL_ENGULF"
                self._last_bias    = "BULLISH"
                return
            # Bearish engulfing: c1 bullish, c2 bearish and body > c1 body
            if c1["c"] > c1["o"] and not bullish_candle and body > c1_body:
                self._last_pattern = "BEAR_ENGULF"
                self._last_bias    = "BEARISH"
                return

        self._last_pattern = "NORMAL"
        self._last_bias    = "BULLISH" if bullish_candle else "BEARISH"

    # ------------------------------------------------------------------
    def is_signal_blocked(self, signal: str) -> bool:
        """Return True if candle pattern contradicts the proposed signal direction."""
        with self._lock:
            bias = self._last_bias
        if bias == "INDECISION":
            return True   # doji — block any entry
        if signal == "BUY"  and bias == "BEARISH":
            return True
        if signal == "SELL" and bias == "BULLISH":
            return True
        return False

    def info(self) -> dict:
        with self._lock:
            return {
                "last_pattern":  self._last_pattern,
                "last_bias":     self._last_bias,
                "last_update":   round(self._last_update, 2),
            }


# Module-level singleton
candle_pattern_filter = CandlePatternFilter()
