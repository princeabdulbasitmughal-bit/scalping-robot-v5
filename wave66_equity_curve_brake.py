"""
wave66_equity_curve_brake.py
------------------------------
Risk guard: pauses trading when account equity drops too far below its
rolling peak (drawdown brake).

Rules
-----
- Tracks a rolling equity high-water mark.
- If current equity drops more than `max_drawdown_pct` percent below the
  peak, the gate CLOSES (blocked) for a configurable `cooldown_seconds`.
- After the cooldown expires the gate reopens and the peak resets to the
  current equity value so recovery can continue.
- Fail-closed: invalid inputs (bool, None, NaN, Inf, negative, zero) are
  rejected and the gate stays OPEN (safe default before any valid tick).

Module-level aliases
---------------------
  is_entry_blocked(tick) -> bool
  is_blocked(tick)       -> bool   (alias)
  update(equity)         -> None   (feed new equity value)
  reset()                -> None

Thread-safety
-------------
  All state mutations are guarded by a threading.RLock().
"""

import math
import threading
import time as _time

# ── tuneable constants ──────────────────────────────────────────────────────
DEFAULT_MAX_DD_PCT: float = 5.0      # percent below peak that trips the brake
DEFAULT_COOLDOWN_S: float = 300.0    # seconds to remain blocked (5 min)
DEFAULT_MIN_TICKS:  int   = 10       # warmup ticks before brake can fire


class EquityCurveBrake:
    """Pauses trading when equity drawdown exceeds a configurable threshold."""

    def __init__(
        self,
        max_drawdown_pct: float = DEFAULT_MAX_DD_PCT,
        cooldown_seconds: float = DEFAULT_COOLDOWN_S,
        min_ticks: int = DEFAULT_MIN_TICKS,
    ) -> None:
        # ── parameter validation ──────────────────────────────────────────
        for name, val in [("max_drawdown_pct", max_drawdown_pct),
                          ("cooldown_seconds", cooldown_seconds)]:
            if isinstance(val, bool):
                raise TypeError(f"{name} must not be bool")
            if not isinstance(val, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if math.isnan(val) or math.isinf(val):
                raise ValueError(f"{name} must not be NaN/Inf")
            if val <= 0:
                raise ValueError(f"{name} must be > 0")

        if isinstance(min_ticks, bool) or not isinstance(min_ticks, int):
            raise TypeError("min_ticks must be a plain int")
        if min_ticks < 1:
            raise ValueError("min_ticks must be >= 1")

        self.max_drawdown_pct = float(max_drawdown_pct)
        self.cooldown_seconds = float(cooldown_seconds)
        self.min_ticks = min_ticks

        self._lock = threading.RLock()
        self._peak: float = 0.0
        self._tick_count: int = 0
        self._tripped_at: float = 0.0   # monotonic timestamp when brake fired

    # ── private ────────────────────────────────────────────────────────────
    @staticmethod
    def _validate_equity(equity: object) -> float:
        if isinstance(equity, bool):
            raise TypeError("equity must not be bool")
        if not isinstance(equity, (int, float)):
            raise TypeError("equity must be numeric")
        v = float(equity)
        if math.isnan(v) or math.isinf(v):
            raise ValueError("equity must not be NaN/Inf")
        if v <= 0:
            raise ValueError("equity must be > 0")
        return v

    # ── public API ──────────────────────────────────────────────────────────
    def update(self, equity: object) -> None:
        """
        Feed a new equity value.  Updates the high-water mark and may trip
        the brake.  Invalid inputs raise; they do NOT silently no-op because
        callers must not pass garbage equity values.
        """
        eq = self._validate_equity(equity)
        with self._lock:
            self._tick_count += 1
            # update peak
            if eq > self._peak:
                self._peak = eq
            # check whether drawdown threshold is breached
            if self._tick_count >= self.min_ticks and self._peak > 0:
                dd_pct = (self._peak - eq) / self._peak * 100.0
                if dd_pct >= self.max_drawdown_pct and self._tripped_at == 0.0:
                    self._tripped_at = _time.monotonic()

    def is_entry_blocked(self, tick: object = None) -> bool:
        """
        Return True (BLOCKED) if the equity drawdown brake is currently active.

        Parameters
        ----------
        tick : optional; accepted for API uniformity but not used.
        """
        with self._lock:
            if self._tick_count < self.min_ticks:
                return False   # still warming up
            if self._tripped_at == 0.0:
                return False   # brake not tripped
            # check if cooldown has expired
            elapsed = _time.monotonic() - self._tripped_at
            if elapsed >= self.cooldown_seconds:
                # reset brake and high-water mark
                self._tripped_at = 0.0
                self._peak = 0.0   # will rebuild from next tick
                return False
            return True

    def reset(self) -> None:
        """Hard-reset all state."""
        with self._lock:
            self._peak = 0.0
            self._tick_count = 0
            self._tripped_at = 0.0

    def get_drawdown_pct(self, equity: float) -> float:
        """Return current drawdown % from peak (read-only, no state change)."""
        with self._lock:
            if self._peak <= 0:
                return 0.0
            return max(0.0, (self._peak - equity) / self._peak * 100.0)


# ── module-level singleton ──────────────────────────────────────────────────
_brake = EquityCurveBrake(
    max_drawdown_pct=DEFAULT_MAX_DD_PCT,
    cooldown_seconds=DEFAULT_COOLDOWN_S,
    min_ticks=DEFAULT_MIN_TICKS,
)


def is_entry_blocked(tick: object = None) -> bool:
    """Module-level alias → EquityCurveBrake.is_entry_blocked()."""
    return _brake.is_entry_blocked(tick)


def is_blocked(tick: object = None) -> bool:
    """Alias for is_entry_blocked (uniform wave interface)."""
    return _brake.is_entry_blocked(tick)


def update(equity: object) -> None:
    """Module-level alias → EquityCurveBrake.update()."""
    _brake.update(equity)


def reset() -> None:
    """Module-level alias → EquityCurveBrake.reset()."""
    _brake.reset()
