"""
Wave 47: ATR Position Sizer
Dynamically adjusts SL and TP pips based on a rolling ATR (14-period).
High ATR -> wider SL/TP; Low ATR -> tighter SL/TP.
Baseline: sl_pips=30, tp_pips=45. ATR ratio scales proportionally.
"""

import math
from collections import deque
import threading
import time
from typing import Optional, Tuple, Any


_ATR_PERIOD = 14
_SL_BASE = 30.0    # pips
_TP_BASE = 45.0    # pips
_SL_MIN  = 15.0
_SL_MAX  = 60.0
_TP_MIN  = 22.0
_TP_MAX  = 90.0


class ATRPositionSizer:
    """
    Maintains a rolling ATR and exposes:
      - get_sl_tp(base_sl, base_tp)
      - get_lot_size(account_balance, risk_pct, sl_pips, pip_value)
    Thread-safe with RLock and strict bounds protection.
    """

    def __init__(self, period: int = _ATR_PERIOD):
        try:
            p = int(period)
            self._period = p if p >= 2 else _ATR_PERIOD
        except (ValueError, TypeError):
            self._period = _ATR_PERIOD

        self._highs: deque[float] = deque(maxlen=self._period + 1)
        self._lows:  deque[float] = deque(maxlen=self._period + 1)
        self._closes: deque[float] = deque(maxlen=self._period + 1)
        self._atr: float = 0.0
        self._atr_baseline: float = 0.0   # calibrated from first N ATR values
        self._atr_history: deque[float] = deque(maxlen=50)
        self._lock = threading.RLock()
        self._last_update = 0.0

    def reset(self) -> None:
        """Thread-safe reset of internal price and ATR buffers."""
        with self._lock:
            self._highs.clear()
            self._lows.clear()
            self._closes.clear()
            self._atr = 0.0
            self._atr_baseline = 0.0
            self._atr_history.clear()
            self._last_update = 0.0

    # ------------------------------------------------------------------
    def update(self, high: Any, low: Any, close: Optional[Any] = None) -> None:
        """Feed each tick/bar H/L/C to keep ATR current."""
        if high is None or low is None or isinstance(high, bool) or isinstance(low, bool):
            return
        try:
            h = float(high)
            l = float(low)
            if not (math.isfinite(h) and math.isfinite(l)) or h < 0 or l < 0:
                return
            if h < l:
                return  # High cannot be less than low

            if close is None or isinstance(close, bool):
                c = (h + l) / 2.0
            else:
                c = float(close)
                if not math.isfinite(c) or c < 0:
                    c = (h + l) / 2.0
        except (ValueError, TypeError):
            return

        try:
            with self._lock:
                self._highs.append(h)
                self._lows.append(l)
                self._closes.append(c)
                if len(self._closes) >= 2:
                    self._atr = self._compute_atr()
                    self._atr_history.append(self._atr)
                    # update rolling baseline (median of last 50 ATR readings)
                    if len(self._atr_history) >= 5:
                        sorted_h = sorted(self._atr_history)
                        self._atr_baseline = sorted_h[len(sorted_h) // 2]
                self._last_update = time.time()
        except Exception:
            pass

    def _compute_atr(self) -> float:
        highs  = list(self._highs)
        lows   = list(self._lows)
        closes = list(self._closes)
        n = min(len(highs), self._period)
        if n < 2:
            return self._atr or 1.0
        trs = []
        for i in range(1, n + 1):
            if i > len(highs):
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
    def get_sl_tp(self, base_sl: float = _SL_BASE, base_tp: float = _TP_BASE) -> Tuple[float, float]:
        """Return (sl_pips, tp_pips) scaled by current ATR vs baseline ATR."""
        with self._lock:
            atr = self._atr
            baseline = self._atr_baseline
        if not math.isfinite(atr) or not math.isfinite(baseline) or atr <= 0 or baseline <= 0:
            return float(base_sl), float(base_tp)
        ratio = atr / baseline
        # clamp ratio to [0.5, 2.0] to avoid extreme outliers
        ratio = max(0.5, min(2.0, ratio))
        sl = round(max(_SL_MIN, min(_SL_MAX, float(base_sl) * ratio)), 1)
        tp = round(max(_TP_MIN, min(_TP_MAX, float(base_tp) * ratio)), 1)
        return sl, tp

    def get_lot_size(
        self,
        account_balance: Any,
        risk_pct: float = 0.01,
        sl_pips: Optional[float] = None,
        pip_value: float = 10.0,
        min_lot: float = 0.01,
        max_lot: float = 100.0,
        lot_step: float = 0.01,
    ) -> float:
        """
        Calculates position lot size based on account balance, risk percent, and dynamic SL.
        Clamps to [min_lot, max_lot] in lot_step increments.
        """
        if account_balance is None or isinstance(account_balance, bool):
            return min_lot
        try:
            bal = float(account_balance)
            if not math.isfinite(bal) or bal <= 0:
                return min_lot
        except (ValueError, TypeError):
            return min_lot

        r_pct = max(0.001, min(0.10, float(risk_pct))) if math.isfinite(risk_pct) else 0.01
        risk_usd = bal * r_pct

        effective_sl = sl_pips if sl_pips is not None and sl_pips > 0 else self.get_sl_tp()[0]
        p_val = max(0.01, float(pip_value))

        # Risk per lot = SL (in pips) * Pip Value per lot
        risk_per_lot = effective_sl * p_val
        if risk_per_lot <= 0:
            return min_lot

        raw_lot = risk_usd / risk_per_lot
        steps = math.floor((raw_lot / lot_step) + 1e-9)
        quantized = round(steps * lot_step, 2)
        return max(min_lot, min(max_lot, quantized))

    def get_atr(self) -> float:
        with self._lock:
            return round(self._atr, 5)

    def info(self) -> dict:
        sl, tp = self.get_sl_tp()
        with self._lock:
            return {
                "wave": 47,
                "name": "ATRPositionSizer",
                "atr": round(self._atr, 5),
                "atr_baseline": round(self._atr_baseline, 5),
                "dynamic_sl_pips": sl,
                "dynamic_tp_pips": tp,
                "buffer_len": len(self._closes),
                "last_update": round(self._last_update, 2),
            }


# Module-level singleton
atr_position_sizer = ATRPositionSizer()
