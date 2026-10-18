"""
Wave 50: Candle Pattern Filter
Detects last candle pattern (doji, hammer, bearish_engulfing, bullish_engulfing).
If pattern contradicts signal direction -> block entry.
Pattern    | Bias     | Blocks
-----------|----------|--------------------
Doji       | INDECISION | blocks both (indecision)
Hammer     | BULLISH  | blocks SELL
Inv Hammer | BEARISH  | blocks BUY
Bull Engulf| BULLISH  | blocks SELL
Bear Engulf| BEARISH  | blocks BUY
"""

import math
import threading
import time
import logging
from collections import deque
from typing import Optional, Tuple, Any, Dict

logger = logging.getLogger(__name__)


class CandlePatternFilter:
    """
    Analyses last 2 synthetic candles built from price ticks or explicit OHLC bars.
    Thread-safe with RLock and supports deterministic timestamp injection.
    """

    def __init__(self):
        # We accumulate ticks into 1-min candles via tick timestamp
        self._ticks: deque[Tuple[float, float]] = deque(maxlen=500)
        self._last_pattern = "NONE"
        self._last_bias    = "NEUTRAL"   # BULLISH / BEARISH / NEUTRAL / INDECISION
        self._total_blocks = 0
        self._lock         = threading.RLock()
        self._last_update  = 0.0

    def reset(self) -> None:
        """Thread-safe reset of pattern detector state."""
        with self._lock:
            self._ticks.clear()
            self._last_pattern = "NONE"
            self._last_bias = "NEUTRAL"
            self._total_blocks = 0
            self._last_update = 0.0

    # ------------------------------------------------------------------
    def update(self, price: Any, now_ts: Optional[float] = None) -> None:
        """Feed each tick price."""
        if price is None or isinstance(price, bool):
            return
        try:
            p = float(price)
            if not math.isfinite(p) or p <= 0:
                return
        except (ValueError, TypeError):
            return

        ts = float(now_ts) if now_ts is not None else time.time()
        with self._lock:
            self._ticks.append((ts, p))
            self._last_update = ts
            self._analyse(now_ts=ts)

    def update_candle(self, o: float, h: float, l: float, c: float) -> None:
        """Directly inject an OHLC candle and analyze its pattern."""
        if not (math.isfinite(o) and math.isfinite(h) and math.isfinite(l) and math.isfinite(c)):
            return
        if h < l or o <= 0 or c <= 0 or h <= 0 or l <= 0:
            return

        with self._lock:
            c2 = {"o": float(o), "h": float(h), "l": float(l), "c": float(c)}
            self._classify_candle(c2, None)
            self._last_update = time.time()

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

    def _classify_candle(self, c2: Dict[str, float], c1: Optional[Dict[str, float]]) -> None:
        """Internal candle pattern classifier."""
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

    def _analyse(self, now_ts: Optional[float] = None) -> None:
        now = float(now_ts) if now_ts is not None else time.time()
        # Split ticks into two 30-sec candles
        c2_ticks = [(t, p) for t, p in self._ticks if now - t <= 30]
        c1_ticks = [(t, p) for t, p in self._ticks if 30 < now - t <= 60]
        c2 = self._build_candle(c2_ticks)
        c1 = self._build_candle(c1_ticks)
        if c2 is None:
            self._last_pattern = "NONE"
            self._last_bias    = "NEUTRAL"
            return

        self._classify_candle(c2, c1)

    # ------------------------------------------------------------------
    def is_signal_blocked(self, signal: Any) -> bool:
        """Return True if candle pattern contradicts the proposed signal direction."""
        sig = str(signal).strip().upper() if signal is not None else ""
        with self._lock:
            bias = self._last_bias
            pattern = self._last_pattern

        if bias == "INDECISION":
            with self._lock:
                self._total_blocks += 1
            logger.info(f"[WAVE50] Entry BLOCKED — DOJI pattern indecision")
            return True   # doji — block any entry

        if sig == "BUY" and bias == "BEARISH":
            with self._lock:
                self._total_blocks += 1
            logger.info(f"[WAVE50] BUY BLOCKED — bearish {pattern} pattern")
            return True

        if sig == "SELL" and bias == "BULLISH":
            with self._lock:
                self._total_blocks += 1
            logger.info(f"[WAVE50] SELL BLOCKED — bullish {pattern} pattern")
            return True

        return False

    def get_bias(self) -> str:
        with self._lock:
            return self._last_bias

    def is_entry_blocked(self, signal: Any = "BUY") -> bool:
        """Alias for is_signal_blocked."""
        return self.is_signal_blocked(signal)

    def is_blocked(self, signal: Any = "BUY") -> bool:
        """Alias for is_signal_blocked."""
        return self.is_signal_blocked(signal)

    def is_trading_allowed(self, signal: Any = "BUY") -> Tuple[bool, str]:
        """Returns (True, '') if allowed, (False, reason) if blocked."""
        blocked = self.is_signal_blocked(signal)
        if blocked:
            with self._lock:
                return False, f"CANDLE_PATTERN: {self._last_pattern} contradicts {signal}"
        return True, ""

    def info(self) -> dict:
        with self._lock:
            return {
                "wave": 50,
                "name": "CandlePatternFilter",
                "last_pattern":  self._last_pattern,
                "last_bias":     self._last_bias,
                "last_update":   round(self._last_update, 2),
                "total_blocks":  self._total_blocks,
                "ticks_buffered": len(self._ticks),
            }


# Module-level singleton
candle_pattern_filter = CandlePatternFilter()

# Module-level aliases for risk orchestrator integration
def is_entry_blocked(signal: Any = "BUY") -> bool:
    return candle_pattern_filter.is_entry_blocked(signal=signal)

def is_blocked(signal: Any = "BUY") -> bool:
    return candle_pattern_filter.is_blocked(signal=signal)

def update(price: Any, now_ts: Optional[float] = None) -> None:
    candle_pattern_filter.update(price, now_ts=now_ts)

def update_candle(o: float, h: float, l: float, c: float) -> None:
    candle_pattern_filter.update_candle(o, h, l, c)

def reset() -> None:
    candle_pattern_filter.reset()
