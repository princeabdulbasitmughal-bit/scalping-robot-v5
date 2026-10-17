"""
Wave 31: Reversal Detector
Detects RSI overbought/oversold conditions combined with price divergence
and forces or boosts counter-signal direction.

Logic:
  - RSI > 75 (overbought) while price makes higher highs but RSI makes lower highs
    (bearish divergence) -> SELL bias
  - RSI < 25 (oversold) while price makes lower lows but RSI makes higher lows
    (bullish divergence) -> BUY bias
  - Provides suggested signal override and confidence score (0.0-1.0)
  - Supports tick price updates and OHLC bar/candle list validation and updates
"""

import math
import time
import threading
from collections import deque
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union


class ReversalDetector:
    def __init__(
        self,
        rsi_period: int = 14,
        overbought: float = 75.0,
        oversold: float = 25.0,
        price_window: int = 5,
        cooldown_sec: float = 60.0,
    ):
        # Parameter validation & bounds
        self._rsi_period: int = max(2, int(rsi_period))
        self._overbought: float = float(overbought)
        self._oversold: float = float(oversold)
        if not (50.0 < self._overbought < 100.0):
            self._overbought = 75.0
        if not (0.0 < self._oversold < 50.0):
            self._oversold = 25.0
        if self._overbought <= self._oversold:
            self._overbought, self._oversold = 75.0, 25.0

        self._price_window: int = max(3, int(price_window))
        self._cooldown: float = max(0.0, float(cooldown_sec))

        self._prices: deque = deque(maxlen=self._rsi_period + 1)
        self._rsi_history: deque = deque(maxlen=self._price_window)
        self._price_highs: deque = deque(maxlen=self._price_window)
        self._price_lows: deque = deque(maxlen=self._price_window)

        self._last_signal: str = "HOLD"
        self._last_signal_time: float = 0.0
        self._last_reason: str = "none"
        self._total_reversals: int = 0
        self._created_at: float = time.time()
        
        # Reentrant lock for nested caller safety
        self._lock = threading.RLock()

    # ── Bar Validation Methods ───────────────────────────────────────────
    @staticmethod
    def validate_bar(bar: Any) -> Optional[Tuple[float, float, float, float]]:
        """
        Validates an OHLC bar. Returns (open, high, low, close) if valid, else None.
        Accepts:
          - dict with keys 'open', 'high', 'low', 'close' (or 'o', 'h', 'l', 'c')
          - tuple/list of at least 4 numbers: (open, high, low, close) or (ts, o, h, l, c, ...)
        """
        if bar is None:
            return None
        try:
            if isinstance(bar, dict):
                o_val = bar.get("open", bar.get("o", bar.get("close", bar.get("c"))))
                h_val = bar.get("high", bar.get("h"))
                l_val = bar.get("low", bar.get("l"))
                c_val = bar.get("close", bar.get("c"))
                if h_val is None or l_val is None or c_val is None:
                    return None
                o = float(o_val if o_val is not None else c_val)
                h = float(h_val)
                l = float(l_val)
                c = float(c_val)
            elif isinstance(bar, (list, tuple)):
                if len(bar) == 4:
                    o, h, l, c = (float(x) for x in bar[:4])
                elif len(bar) >= 5:
                    o, h, l, c = (float(x) for x in bar[1:5])
                else:
                    return None
            else:
                return None

            # Numeric & logical sanity checks
            if not (math.isfinite(o) and math.isfinite(h) and math.isfinite(l) and math.isfinite(c)):
                return None
            if h < l or c < 0.0 or h < 0.0 or l < 0.0:
                return None
            # Allow minor floating point tolerance for open/close relative to high/low
            h = max(h, o, c)
            l = min(l, o, c)
            return (o, h, l, c)
        except (ValueError, TypeError, KeyError, IndexError):
            return None

    @classmethod
    def validate_bars(cls, bars: Any) -> List[Tuple[float, float, float, float]]:
        """
        Validates a sequence of OHLC bars. Returns clean (open, high, low, close) tuples.
        Discards invalid/corrupt entries.
        """
        if not bars or not isinstance(bars, (list, tuple, deque)):
            return []
        valid = []
        for b in bars:
            vb = cls.validate_bar(b)
            if vb is not None:
                valid.append(vb)
        return valid

    # ── RSI Computation ──────────────────────────────────────────────────
    def _compute_rsi(self) -> float:
        """
        Compute RSI over stored price series with Cutler's SMA approximation.
        Safe against zero deltas and cold-starts.
        """
        prices = list(self._prices)
        if len(prices) <= self._rsi_period:
            return 50.0

        gains: List[float] = []
        losses: List[float] = []
        for i in range(1, len(prices)):
            delta = prices[i] - prices[i - 1]
            if delta > 0:
                gains.append(delta)
            elif delta < 0:
                losses.append(abs(delta))

        period = max(1, self._rsi_period)
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        if avg_loss == 0.0:
            return 50.0 if avg_gain == 0.0 else 100.0
        rs = avg_gain / avg_loss
        return max(0.0, min(100.0, 100.0 - (100.0 / (1.0 + rs))))

    # ── Update Methods ───────────────────────────────────────────────────
    def update(self, price: float, rsi: Optional[float] = None) -> None:
        """Push latest price tick and optional RSI."""
        try:
            if price is None or isinstance(price, bool):
                return
            p = float(price)
            if not math.isfinite(p) or p <= 0.0:
                return
        except (ValueError, TypeError):
            return

        with self._lock:
            self._prices.append(p)
            if rsi is not None:
                try:
                    f_rsi = float(rsi)
                    if math.isfinite(f_rsi) and 0.0 <= f_rsi <= 100.0:
                        self._rsi_history.append(f_rsi)
                    else:
                        self._rsi_history.append(self._compute_rsi())
                except (ValueError, TypeError):
                    self._rsi_history.append(self._compute_rsi())
            else:
                self._rsi_history.append(self._compute_rsi())

            self._price_highs.append(p)
            self._price_lows.append(p)

    def update_price(self, price: float) -> None:
        """Push latest price tick and refresh RSI."""
        self.update(price)

    def update_bar(self, bar: Any, rsi: Optional[float] = None) -> bool:
        """Feed a single OHLC bar. Returns True if accepted, False otherwise."""
        clean = self.validate_bar(bar)
        if clean is None:
            return False
        _o, h, l, c = clean
        with self._lock:
            self._prices.append(c)
            if rsi is not None:
                try:
                    f_rsi = float(rsi)
                    if math.isfinite(f_rsi) and 0.0 <= f_rsi <= 100.0:
                        self._rsi_history.append(f_rsi)
                    else:
                        self._rsi_history.append(self._compute_rsi())
                except (ValueError, TypeError):
                    self._rsi_history.append(self._compute_rsi())
            else:
                self._rsi_history.append(self._compute_rsi())
            self._price_highs.append(h)
            self._price_lows.append(l)
        return True

    def update_bars(self, bars: Any) -> int:
        """Feed a sequence of bars. Returns number of accepted bars."""
        valid_bars = self.validate_bars(bars)
        if not valid_bars:
            return 0
        with self._lock:
            for _o, h, l, c in valid_bars:
                self._prices.append(c)
                self._rsi_history.append(self._compute_rsi())
                self._price_highs.append(h)
                self._price_lows.append(l)
        return len(valid_bars)

    # ── Signal Generation ────────────────────────────────────────────────
    def get_reversal_signal(self) -> Tuple[str, float, str]:
        """
        Returns (signal: str, confidence: float, reason: str).
        signal is 'BUY', 'SELL', or 'HOLD'.
        """
        with self._lock:
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

            ob_span = max(1.0, 100.0 - self._overbought)
            os_span = max(1.0, self._oversold)

            # Bearish divergence: price higher high but RSI lower high (in overbought zone)
            if latest_rsi > self._overbought and latest_high > prev_high and latest_rsi < prev_rsi:
                norm_excess = (latest_rsi - self._overbought) / ob_span
                confidence = 0.30 + 0.70 * min(max(norm_excess, 0.0), 1.0)
                self._last_signal = "SELL"
                self._last_signal_time = now
                self._last_reason = "bearish_divergence_overbought"
                self._total_reversals += 1
                return ("SELL", round(confidence, 3), "bearish_divergence_overbought")

            # Bullish divergence: price lower low but RSI higher low (in oversold zone)
            if latest_rsi < self._oversold and latest_low < prev_low and latest_rsi > prev_rsi:
                norm_excess = (self._oversold - latest_rsi) / os_span
                confidence = 0.30 + 0.70 * min(max(norm_excess, 0.0), 1.0)
                self._last_signal = "BUY"
                self._last_signal_time = now
                self._last_reason = "bullish_divergence_oversold"
                self._total_reversals += 1
                return ("BUY", round(confidence, 3), "bullish_divergence_oversold")

            # Extreme levels without divergence (lower confidence)
            if latest_rsi > self._overbought:
                norm_excess = (latest_rsi - self._overbought) / ob_span
                confidence = 0.10 + 0.40 * min(max(norm_excess, 0.0), 1.0)
                self._last_signal = "SELL"
                self._last_signal_time = now
                self._last_reason = "overbought_extreme"
                self._total_reversals += 1
                return ("SELL", round(confidence, 3), "overbought_extreme")

            if latest_rsi < self._oversold:
                norm_excess = (self._oversold - latest_rsi) / os_span
                confidence = 0.10 + 0.40 * min(max(norm_excess, 0.0), 1.0)
                self._last_signal = "BUY"
                self._last_signal_time = now
                self._last_reason = "oversold_extreme"
                self._total_reversals += 1
                return ("BUY", round(confidence, 3), "oversold_extreme")

            return ("HOLD", 0.0, "no_reversal_condition")

    # ── State Reset & Info ───────────────────────────────────────────────
    def reset(self) -> None:
        """Reset internal buffers and state."""
        with self._lock:
            self._prices.clear()
            self._rsi_history.clear()
            self._price_highs.clear()
            self._price_lows.clear()
            self._last_signal = "HOLD"
            self._last_signal_time = 0.0
            self._last_reason = "none"

    def info(self) -> Dict[str, Any]:
        with self._lock:
            now = time.time()
            rsi_vals = list(self._rsi_history)
            current_rsi = rsi_vals[-1] if rsi_vals else 50.0
            is_cooldown = (now - self._last_signal_time) < self._cooldown
            remaining_cooldown = max(0.0, self._cooldown - (now - self._last_signal_time)) if is_cooldown else 0.0
            return {
                "wave": 31,
                "name": "ReversalDetector",
                "current_rsi": round(current_rsi, 2),
                "overbought_threshold": self._overbought,
                "oversold_threshold": self._oversold,
                "last_signal": self._last_signal,
                "last_reason": self._last_reason,
                "is_cooldown_active": is_cooldown,
                "cooldown_remaining_sec": round(remaining_cooldown, 1),
                "total_reversals": self._total_reversals,
                "cooldown_sec": self._cooldown,
                "buffer_size": len(self._prices),
                "highs_buffer_size": len(self._price_highs),
                "lows_buffer_size": len(self._price_lows),
            }


# Module-level singleton
reversal_detector = ReversalDetector(
    rsi_period=14,
    overbought=75.0,
    oversold=25.0,
    price_window=5,
    cooldown_sec=60.0,
)
