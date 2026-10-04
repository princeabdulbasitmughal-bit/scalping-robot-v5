"""
Wave 47: ATR Position Sizer
Dynamically adjusts SL and TP pips based on a rolling ATR (14-period).
High ATR -> wider SL/TP; Low ATR -> tighter SL/TP.
Baseline: sl_pips=30, tp_pips=45.  ATR ratio scales proportionally.
"""

from collections import deque
import threading
import time


_ATR_PERIOD = 14
_SL_BASE = 30.0    # pips
_TP_BASE = 45.0    # pips
_SL_MIN  = 15.0
_SL_MAX  = 60.0
_TP_MIN  = 22.0
_TP_MAX  = 90.0


class ATRPositionSizer:
    """Maintains a rolling ATR and exposes get_sl_tp(base_sl, base_tp)."""

    def __init__(self, period: int = _ATR_PERIOD):
        self._period = period
        self._highs: deque = deque(maxlen=period + 1)
        self._lows:  deque = deque(maxlen=period + 1)
        self._closes: deque = deque(maxlen=period + 1)
        self._atr: float = 0.0
        self._atr_baseline: float = 0.0   # calibrated from first N ATR values
        self._atr_history: deque = deque(maxlen=50)
        self._lock = threading.Lock()
        self._last_update = 0.0

    # ------------------------------------------------------------------
    def update(self, high: float, low: float, close: float) -> None:
        """Feed each tick/bar H/L/C to keep ATR current."""
        with self._lock:
            self._highs.append(high)
            self._lows.append(low)
            self._closes.append(close)
            if len(self._closes) >= 2:
                self._atr = self._compute_atr()
                self._atr_history.append(self._atr)
                # update rolling baseline (median of last 50 ATR readings)
                if len(self._atr_history) >= 5:
                    sorted_h = sorted(self._atr_history)
                    self._atr_baseline = sorted_h[len(sorted_h) // 2]
            self._last_update = time.time()

    def _compute_atr(self) -> float:
        highs  = list(self._highs)
        lows   = list(self._lows)
        closes = list(self._closes)
        n = min(len(highs), self._period)
        if n < 2:
            return self._atr or 1.0
        trs = []
        for i in range(1, n + 1):
            if i >= len(highs):
                break
            h = highs[-i]
            l = lows[-i]
            prev_c = closes[-(i + 1)] if (i + 1) <= len(closes) else closes[-i]
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
            trs.append(tr)
        if not trs:
            return self._atr or 1.0
        return sum(trs) / len(trs)

    # ------------------------------------------------------------------
    def get_sl_tp(self, base_sl: float = _SL_BASE, base_tp: float = _TP_BASE):
        """Return (sl_pips, tp_pips) scaled by current ATR vs baseline ATR."""
        with self._lock:
            atr = self._atr
            baseline = self._atr_baseline
        if atr <= 0 or baseline <= 0:
            return base_sl, base_tp
        ratio = atr / baseline
        # clamp ratio to [0.5, 2.0] to avoid extreme outliers
        ratio = max(0.5, min(2.0, ratio))
        sl = round(max(_SL_MIN, min(_SL_MAX, base_sl * ratio)), 1)
        tp = round(max(_TP_MIN, min(_TP_MAX, base_tp * ratio)), 1)
        return sl, tp

    def get_atr(self) -> float:
        with self._lock:
            return round(self._atr, 5)

    def info(self) -> dict:
        with self._lock:
            sl, tp = self.get_sl_tp()
            return {
                "atr": round(self._atr, 5),
                "atr_baseline": round(self._atr_baseline, 5),
                "dynamic_sl_pips": sl,
                "dynamic_tp_pips": tp,
                "last_update": round(self._last_update, 2),
            }


# Module-level singleton
atr_position_sizer = ATRPositionSizer()
