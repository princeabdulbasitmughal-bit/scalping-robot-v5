"""
wave70_candle_size_guard.py
----------------------------
Risk guard: blocks entries when recent candle bodies are abnormally large,
indicating a volatility shock / news spike that makes entry risky.

Rules
-----
- Tracks a rolling baseline of candle body sizes (|close - open| in pips).
- If the latest candle body exceeds `spike_multiplier × baseline_avg`, the
  gate CLOSES (blocked) for `cooldown_seconds`.
- Baseline uses a simple EMA (Exponential Moving Average) over the last N
  candles for responsiveness.
- Fail-closed: invalid inputs are rejected. Gate stays OPEN during warmup
  (before `min_candles` have been seen).

Module-level aliases
---------------------
  is_entry_blocked(tick) -> bool
  is_blocked(tick)       -> bool   (alias)
  update(open_price, close_price) -> None
  reset()                -> None

Thread-safety
-------------
  All state mutations are guarded by a threading.RLock().
"""

import math
import threading
import time as _time

# ── tuneable constants ──────────────────────────────────────────────────────
DEFAULT_PIP_SIZE:        float = 0.1     # XAUUSD: 1 pip = 0.1 price units
DEFAULT_SPIKE_MULT:      float = 3.0     # candle body > 3× EMA → spike
DEFAULT_EMA_PERIOD:      int   = 20      # EMA smoothing period
DEFAULT_MIN_CANDLES:     int   = 10      # warmup candles before blocking
DEFAULT_COOLDOWN_S:      float = 60.0   # seconds blocked after spike


class CandleSizeGuard:
    """Blocks entries when the most recent candle body is an outlier spike."""

    def __init__(
        self,
        spike_multiplier: float = DEFAULT_SPIKE_MULT,
        ema_period: int = DEFAULT_EMA_PERIOD,
        min_candles: int = DEFAULT_MIN_CANDLES,
        cooldown_seconds: float = DEFAULT_COOLDOWN_S,
        pip_size: float = DEFAULT_PIP_SIZE,
    ) -> None:
        # ── validate ─────────────────────────────────────────────────────
        for name, val in [("spike_multiplier", spike_multiplier),
                          ("cooldown_seconds", cooldown_seconds),
                          ("pip_size", pip_size)]:
            if isinstance(val, bool):
                raise TypeError(f"{name} must not be bool")
            if not isinstance(val, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if math.isnan(val) or math.isinf(val):
                raise ValueError(f"{name} must not be NaN/Inf")
            if val <= 0:
                raise ValueError(f"{name} must be > 0")

        for name, val in [("ema_period", ema_period), ("min_candles", min_candles)]:
            if isinstance(val, bool) or not isinstance(val, int):
                raise TypeError(f"{name} must be a plain int")
            if val < 1:
                raise ValueError(f"{name} must be >= 1")

        self.spike_multiplier = float(spike_multiplier)
        self.cooldown_seconds = float(cooldown_seconds)
        self.pip_size = float(pip_size)
        self.ema_period = ema_period
        self.min_candles = min_candles

        # EMA smoothing factor
        self._alpha = 2.0 / (ema_period + 1)

        self._lock = threading.RLock()
        self._ema_body: float = 0.0        # EMA of candle body sizes (in pips)
        self._candle_count: int = 0
        self._tripped_at: float = 0.0     # monotonic timestamp of last spike

    # ── private ────────────────────────────────────────────────────────────
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

    # ── public API ──────────────────────────────────────────────────────────
    def update(self, open_price: object, close_price: object) -> None:
        """
        Feed a completed candle's open and close prices.

        Parameters
        ----------
        open_price  : candle open price
        close_price : candle close price
        """
        op = self._validate_price("open_price", open_price)
        cp = self._validate_price("close_price", close_price)

        body_pips = abs(cp - op) / self.pip_size

        with self._lock:
            self._candle_count += 1
            if self._candle_count == 1:
                # Seed EMA with first candle body
                self._ema_body = body_pips
            else:
                self._ema_body = (self._alpha * body_pips
                                  + (1.0 - self._alpha) * self._ema_body)

            # Check for spike after warmup
            if (self._candle_count >= self.min_candles
                    and self._ema_body > 0
                    and body_pips >= self.spike_multiplier * self._ema_body):
                if self._tripped_at == 0.0:
                    self._tripped_at = _time.monotonic()

    def is_entry_blocked(self, tick: object = None) -> bool:
        """Return True (BLOCKED) when a volatility spike cooldown is active."""
        with self._lock:
            if self._tripped_at == 0.0:
                return False
            elapsed = _time.monotonic() - self._tripped_at
            if elapsed >= self.cooldown_seconds:
                self._tripped_at = 0.0
                return False
            return True

    def get_ema_body_pips(self) -> float:
        """Return current EMA body size in pips (thread-safe)."""
        with self._lock:
            return self._ema_body

    def reset(self) -> None:
        """Hard-reset all state."""
        with self._lock:
            self._ema_body = 0.0
            self._candle_count = 0
            self._tripped_at = 0.0


# ── module-level singleton ──────────────────────────────────────────────────
_guard = CandleSizeGuard(
    spike_multiplier=DEFAULT_SPIKE_MULT,
    ema_period=DEFAULT_EMA_PERIOD,
    min_candles=DEFAULT_MIN_CANDLES,
    cooldown_seconds=DEFAULT_COOLDOWN_S,
    pip_size=DEFAULT_PIP_SIZE,
)


def is_entry_blocked(tick: object = None) -> bool:
    """Module-level alias → CandleSizeGuard.is_entry_blocked()."""
    return _guard.is_entry_blocked(tick)


def is_blocked(tick: object = None) -> bool:
    """Alias for is_entry_blocked (uniform wave interface)."""
    return _guard.is_entry_blocked(tick)


def update(open_price: object, close_price: object) -> None:
    """Module-level alias → CandleSizeGuard.update()."""
    _guard.update(open_price, close_price)


def reset() -> None:
    """Module-level alias → CandleSizeGuard.reset()."""
    _guard.reset()
