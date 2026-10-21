"""
wave76_atr_filter.py
----------------------
Risk guard: blocks entries when the Average True Range (ATR) falls outside
a configurable safe band — either too low (thin/dead market) or too high
(excessive volatility).

Rules
-----
- True Range (TR) per candle = max(high-low, |high-prev_close|, |low-prev_close|)
- ATR = EMA of TR over `period` candles (Wilder's EMA: alpha = 1/period)
- Blocks when ATR < `atr_min` (dead market)  OR  ATR > `atr_max` (overheated)
- Fail-closed: invalid inputs raise. Gate stays OPEN during warmup (< `min_candles`).

Module-level aliases
---------------------
  is_entry_blocked(tick)             -> bool
  is_blocked(tick)                   -> bool
  update(high, low, close)           -> None
  reset()                            -> None

Thread-safety
-------------
  All state mutations are guarded by a threading.RLock().
"""

import math
import threading

DEFAULT_ATR_PERIOD:   int   = 14
DEFAULT_ATR_MIN:      float = 0.5    # pips (too quiet)
DEFAULT_ATR_MAX:      float = 50.0   # pips (too volatile)
DEFAULT_PIP_SIZE:     float = 0.1    # XAUUSD
DEFAULT_MIN_CANDLES:  int   = 14


class AtrFilter:
    """Blocks entries when ATR is outside the configured [atr_min, atr_max] band."""

    def __init__(
        self,
        period: int = DEFAULT_ATR_PERIOD,
        atr_min: float = DEFAULT_ATR_MIN,
        atr_max: float = DEFAULT_ATR_MAX,
        pip_size: float = DEFAULT_PIP_SIZE,
        min_candles: int = DEFAULT_MIN_CANDLES,
    ) -> None:
        # ── validate ─────────────────────────────────────────────────────
        for name, val in [("atr_min", atr_min), ("atr_max", atr_max),
                          ("pip_size", pip_size)]:
            if isinstance(val, bool):
                raise TypeError(f"{name} must not be bool")
            if not isinstance(val, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if math.isnan(val) or math.isinf(val):
                raise ValueError(f"{name} must not be NaN/Inf")
            if val <= 0:
                raise ValueError(f"{name} must be > 0")

        if atr_min >= atr_max:
            raise ValueError("atr_min must be < atr_max")

        for name, val in [("period", period), ("min_candles", min_candles)]:
            if isinstance(val, bool) or not isinstance(val, int):
                raise TypeError(f"{name} must be a plain int")
            if val < 1:
                raise ValueError(f"{name} must be >= 1")

        self.period = period
        self.atr_min = float(atr_min)
        self.atr_max = float(atr_max)
        self.pip_size = float(pip_size)
        self.min_candles = min_candles
        # Wilder's smoothing factor
        self._alpha = 1.0 / period

        self._lock = threading.RLock()
        self._atr: float = 0.0
        self._prev_close: float = 0.0
        self._candle_count: int = 0

    @staticmethod
    def _validate_price(name: str, val: object) -> float:
        if isinstance(val, bool):
            raise TypeError(f"{name} must not be bool")
        if not isinstance(val, (int, float)):
            raise TypeError(f"{name} must be numeric")
        v = float(val)
        if math.isnan(v) or math.isinf(v):
            raise ValueError(f"{name} must not be NaN/Inf")
        return v

    def update(self, high: object, low: object, close: object) -> None:
        """
        Feed a completed candle's high, low, and close prices.

        Parameters
        ----------
        high  : candle high price
        low   : candle low price
        close : candle close price
        """
        h = self._validate_price("high", high)
        l = self._validate_price("low", low)
        c = self._validate_price("close", close)

        if h < l:
            raise ValueError("high must be >= low")

        with self._lock:
            self._candle_count += 1

            if self._candle_count == 1:
                tr = (h - l) / self.pip_size
                self._atr = tr
            else:
                tr = max(
                    h - l,
                    abs(h - self._prev_close),
                    abs(l - self._prev_close),
                ) / self.pip_size
                # Wilder's smoothing: ATR = prev_ATR + alpha * (TR - prev_ATR)
                self._atr = self._atr + self._alpha * (tr - self._atr)

            self._prev_close = c

    def is_entry_blocked(self, tick: object = None) -> bool:
        """Return True (BLOCKED) when ATR is outside the safe band."""
        with self._lock:
            if self._candle_count < self.min_candles:
                return False  # warmup
            return self._atr < self.atr_min or self._atr > self.atr_max

    def get_atr(self) -> float:
        """Return current ATR in pips (thread-safe)."""
        with self._lock:
            return self._atr

    def reset(self) -> None:
        """Hard-reset all state."""
        with self._lock:
            self._atr = 0.0
            self._prev_close = 0.0
            self._candle_count = 0


# ── module-level singleton ──────────────────────────────────────────────────
_filter = AtrFilter()


def is_entry_blocked(tick: object = None) -> bool:
    return _filter.is_entry_blocked(tick)


def is_blocked(tick: object = None) -> bool:
    return _filter.is_entry_blocked(tick)


def update(high: object, low: object, close: object) -> None:
    _filter.update(high, low, close)


def reset() -> None:
    _filter.reset()
