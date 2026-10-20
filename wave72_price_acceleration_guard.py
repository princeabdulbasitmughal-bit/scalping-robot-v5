"""
wave72_price_acceleration_guard.py
------------------------------------
Risk guard: blocks entries when tick-to-tick price change is accelerating
beyond a safe threshold, indicating a momentum runaway / flash move.

Rules
-----
- Tracks the rolling EMA of absolute tick-to-tick price deltas (velocity).
- On each new tick, computes acceleration = |current_velocity - prev_velocity|.
- If acceleration exceeds `accel_threshold` pips, the gate CLOSES for
  `cooldown_seconds`.
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

DEFAULT_PIP_SIZE:       float = 0.1
DEFAULT_ACCEL_THRESH:   float = 5.0    # pips/tick acceleration to trigger
DEFAULT_EMA_PERIOD:     int   = 10
DEFAULT_MIN_TICKS:      int   = 5
DEFAULT_COOLDOWN_S:     float = 45.0


class PriceAccelerationGuard:
    """Blocks entries when price acceleration exceeds a configurable threshold."""

    def __init__(
        self,
        accel_threshold: float = DEFAULT_ACCEL_THRESH,
        ema_period: int = DEFAULT_EMA_PERIOD,
        min_ticks: int = DEFAULT_MIN_TICKS,
        cooldown_seconds: float = DEFAULT_COOLDOWN_S,
        pip_size: float = DEFAULT_PIP_SIZE,
    ) -> None:
        for name, val in [("accel_threshold", accel_threshold),
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

        for name, val in [("ema_period", ema_period), ("min_ticks", min_ticks)]:
            if isinstance(val, bool) or not isinstance(val, int):
                raise TypeError(f"{name} must be a plain int")
            if val < 1:
                raise ValueError(f"{name} must be >= 1")

        self.accel_threshold = float(accel_threshold)
        self.cooldown_seconds = float(cooldown_seconds)
        self.pip_size = float(pip_size)
        self.ema_period = ema_period
        self.min_ticks = min_ticks
        self._alpha = 2.0 / (ema_period + 1)

        self._lock = threading.RLock()
        self._last_price: float = 0.0
        self._ema_velocity: float = 0.0   # EMA of |delta| in pips
        self._prev_velocity: float = 0.0  # previous EMA value
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
        return v

    def update(self, price: object) -> None:
        """Feed a new tick price."""
        p = self._validate_price(price)
        with self._lock:
            self._tick_count += 1
            if self._tick_count == 1:
                self._last_price = p
                return

            delta_pips = abs(p - self._last_price) / self.pip_size
            self._last_price = p

            prev_ema = self._ema_velocity
            if self._tick_count == 2:
                self._ema_velocity = delta_pips
            else:
                self._ema_velocity = (self._alpha * delta_pips
                                      + (1.0 - self._alpha) * self._ema_velocity)

            if self._tick_count >= self.min_ticks:
                acceleration = abs(self._ema_velocity - prev_ema)
                if acceleration >= self.accel_threshold and self._tripped_at == 0.0:
                    self._tripped_at = _time.monotonic()

            self._prev_velocity = prev_ema

    def is_entry_blocked(self, tick: object = None) -> bool:
        """Return True (BLOCKED) during cooldown after a price acceleration spike."""
        with self._lock:
            if self._tripped_at == 0.0:
                return False
            if _time.monotonic() - self._tripped_at >= self.cooldown_seconds:
                self._tripped_at = 0.0
                return False
            return True

    def get_ema_velocity(self) -> float:
        """Return current EMA velocity in pips/tick (thread-safe)."""
        with self._lock:
            return self._ema_velocity

    def reset(self) -> None:
        """Hard-reset all state."""
        with self._lock:
            self._last_price = 0.0
            self._ema_velocity = 0.0
            self._prev_velocity = 0.0
            self._tick_count = 0
            self._tripped_at = 0.0


# ── module-level singleton ──────────────────────────────────────────────────
_guard = PriceAccelerationGuard()


def is_entry_blocked(tick: object = None) -> bool:
    return _guard.is_entry_blocked(tick)


def is_blocked(tick: object = None) -> bool:
    return _guard.is_entry_blocked(tick)


def update(price: object) -> None:
    _guard.update(price)


def reset() -> None:
    _guard.reset()
