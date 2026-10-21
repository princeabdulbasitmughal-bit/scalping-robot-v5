"""
wave74_realized_vol_guard.py
------------------------------
Risk guard: blocks entries when rolling realized volatility (standard
deviation of tick-to-tick log-returns) exceeds a configurable threshold.

Rules
-----
- Collects the last `window` tick prices in a circular deque.
- Computes std-dev of log-returns: ln(price[i] / price[i-1]).
- If realized_vol >= `vol_threshold`, the gate CLOSES for `cooldown_seconds`.
- Fail-closed: invalid inputs raise; gate stays OPEN during warmup.

Module-level aliases
---------------------
  is_entry_blocked(tick) -> bool
  is_blocked(tick)       -> bool
  update(price)          -> None
  reset()                -> None

Thread-safety
-------------
  All state mutations are guarded by a threading.RLock().
"""

import math
import threading
import time as _time
from collections import deque

DEFAULT_WINDOW:       int   = 20
DEFAULT_VOL_THRESH:   float = 0.001    # ~0.1% log-return std-dev per tick
DEFAULT_MIN_TICKS:    int   = 10
DEFAULT_COOLDOWN_S:   float = 60.0


class RealizedVolGuard:
    """Blocks entries when rolling realized volatility is too high."""

    def __init__(
        self,
        window: int = DEFAULT_WINDOW,
        vol_threshold: float = DEFAULT_VOL_THRESH,
        min_ticks: int = DEFAULT_MIN_TICKS,
        cooldown_seconds: float = DEFAULT_COOLDOWN_S,
    ) -> None:
        for name, val in [("vol_threshold", vol_threshold),
                          ("cooldown_seconds", cooldown_seconds)]:
            if isinstance(val, bool):
                raise TypeError(f"{name} must not be bool")
            if not isinstance(val, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if math.isnan(val) or math.isinf(val):
                raise ValueError(f"{name} must not be NaN/Inf")
            if val <= 0:
                raise ValueError(f"{name} must be > 0")

        for name, val in [("window", window), ("min_ticks", min_ticks)]:
            if isinstance(val, bool) or not isinstance(val, int):
                raise TypeError(f"{name} must be a plain int")
            if val < 2:
                raise ValueError(f"{name} must be >= 2")

        self.window = window
        self.vol_threshold = float(vol_threshold)
        self.min_ticks = min_ticks
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._prices: deque = deque(maxlen=window + 1)
        self._tick_count: int = 0
        self._tripped_at: float = 0.0

    @staticmethod
    def _validate_price(val: object) -> float:
        if isinstance(val, bool):
            raise TypeError("price must not be bool")
        if not isinstance(val, (int, float)):
            raise TypeError("price must be numeric")
        v = float(val)
        if math.isnan(v) or math.isinf(v):
            raise ValueError("price must not be NaN/Inf")
        if v <= 0:
            raise ValueError("price must be > 0 for log-return computation")
        return v

    def _compute_realized_vol(self) -> float:
        """Compute std-dev of log-returns from current price deque (caller holds lock)."""
        prices = list(self._prices)
        if len(prices) < 2:
            return 0.0
        log_returns = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]
        n = len(log_returns)
        if n < 2:
            return 0.0
        mean = sum(log_returns) / n
        variance = sum((r - mean) ** 2 for r in log_returns) / (n - 1)
        return math.sqrt(variance)

    def update(self, price: object) -> None:
        """Feed a new tick price."""
        p = self._validate_price(price)
        with self._lock:
            self._prices.append(p)
            self._tick_count += 1
            if self._tick_count >= self.min_ticks:
                vol = self._compute_realized_vol()
                if vol >= self.vol_threshold and self._tripped_at == 0.0:
                    self._tripped_at = _time.monotonic()

    def is_entry_blocked(self, tick: object = None) -> bool:
        """Return True (BLOCKED) when realized vol cooldown is active."""
        with self._lock:
            if self._tripped_at == 0.0:
                return False
            if _time.monotonic() - self._tripped_at >= self.cooldown_seconds:
                self._tripped_at = 0.0
                return False
            return True

    def get_realized_vol(self) -> float:
        """Return current rolling realized volatility (thread-safe)."""
        with self._lock:
            return self._compute_realized_vol()

    def reset(self) -> None:
        """Hard-reset all state."""
        with self._lock:
            self._prices.clear()
            self._tick_count = 0
            self._tripped_at = 0.0


# ── module-level singleton ──────────────────────────────────────────────────
_guard = RealizedVolGuard()


def is_entry_blocked(tick: object = None) -> bool:
    return _guard.is_entry_blocked(tick)


def is_blocked(tick: object = None) -> bool:
    return _guard.is_entry_blocked(tick)


def update(price: object) -> None:
    _guard.update(price)


def reset() -> None:
    _guard.reset()
