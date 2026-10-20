"""
wave68_tick_velocity_guard.py
------------------------------
Risk guard: blocks trading when the tick arrival rate drops below a minimum
threshold, indicating a thin/illiquid market.

Rules
-----
- Measures ticks-per-second using a sliding time window (default 10 seconds).
- Maintains a deque of tick arrival timestamps (monotonic clock).
- If velocity < `min_ticks_per_second`, the gate CLOSES (blocked).
- Fail-closed: gate is OPEN only after enough ticks arrive above threshold.
- Before `min_warmup_ticks` have been received, gate stays OPEN (no penalty
  for cold start).

Module-level aliases
---------------------
  is_entry_blocked(tick) -> bool
  is_blocked(tick)       -> bool   (alias)
  update(tick)           -> None   (call on every incoming tick)
  reset()                -> None

Thread-safety
-------------
  All state mutations are guarded by a threading.RLock().
"""

import math
import threading
import time as _time
from collections import deque

# ── tuneable constants ──────────────────────────────────────────────────────
DEFAULT_WINDOW_S:          float = 10.0   # sliding window in seconds
DEFAULT_MIN_TICKS_PER_S:   float = 0.5   # below this = thin market
DEFAULT_MIN_WARMUP_TICKS:  int   = 5     # warmup ticks before blocking


class TickVelocityGuard:
    """Blocks entries when tick arrival rate falls below min_ticks_per_second."""

    def __init__(
        self,
        window_seconds: float = DEFAULT_WINDOW_S,
        min_ticks_per_second: float = DEFAULT_MIN_TICKS_PER_S,
        min_warmup_ticks: int = DEFAULT_MIN_WARMUP_TICKS,
    ) -> None:
        # ── parameter validation ──────────────────────────────────────────
        for name, val in [("window_seconds", window_seconds),
                          ("min_ticks_per_second", min_ticks_per_second)]:
            if isinstance(val, bool):
                raise TypeError(f"{name} must not be bool")
            if not isinstance(val, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if math.isnan(val) or math.isinf(val):
                raise ValueError(f"{name} must not be NaN/Inf")
            if val <= 0:
                raise ValueError(f"{name} must be > 0")

        if isinstance(min_warmup_ticks, bool) or not isinstance(min_warmup_ticks, int):
            raise TypeError("min_warmup_ticks must be a plain int")
        if min_warmup_ticks < 1:
            raise ValueError("min_warmup_ticks must be >= 1")

        self.window_seconds = float(window_seconds)
        self.min_ticks_per_second = float(min_ticks_per_second)
        self.min_warmup_ticks = min_warmup_ticks

        self._lock = threading.RLock()
        self._timestamps: deque = deque()
        self._total_ticks: int = 0

    # ── public API ──────────────────────────────────────────────────────────
    def update(self, tick: object = None) -> None:
        """Record a new tick arrival (call once per incoming tick)."""
        now = _time.monotonic()
        with self._lock:
            self._timestamps.append(now)
            self._total_ticks += 1
            # Purge timestamps outside the sliding window
            cutoff = now - self.window_seconds
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()

    def _current_velocity(self) -> float:
        """Return ticks/second in the current window (caller holds lock)."""
        now = _time.monotonic()
        cutoff = now - self.window_seconds
        # Re-purge in case update() wasn't called recently
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()
        count = len(self._timestamps)
        if count == 0:
            return 0.0
        # Actual elapsed = window_seconds (or time since first tick if shorter)
        elapsed = now - self._timestamps[0] if count > 1 else self.window_seconds
        elapsed = max(elapsed, 1e-9)
        return count / elapsed

    def is_entry_blocked(self, tick: object = None) -> bool:
        """
        Return True (BLOCKED) when tick velocity is below the minimum threshold.

        During warmup (< min_warmup_ticks total), returns False.
        """
        with self._lock:
            if self._total_ticks < self.min_warmup_ticks:
                return False  # still warming up
            velocity = self._current_velocity()
            return velocity < self.min_ticks_per_second

    def get_velocity(self) -> float:
        """Return current tick velocity (ticks/second) — thread-safe."""
        with self._lock:
            return self._current_velocity()

    def reset(self) -> None:
        """Hard-reset all state."""
        with self._lock:
            self._timestamps.clear()
            self._total_ticks = 0


# ── module-level singleton ──────────────────────────────────────────────────
_guard = TickVelocityGuard(
    window_seconds=DEFAULT_WINDOW_S,
    min_ticks_per_second=DEFAULT_MIN_TICKS_PER_S,
    min_warmup_ticks=DEFAULT_MIN_WARMUP_TICKS,
)


def is_entry_blocked(tick: object = None) -> bool:
    """Module-level alias → TickVelocityGuard.is_entry_blocked()."""
    return _guard.is_entry_blocked(tick)


def is_blocked(tick: object = None) -> bool:
    """Alias for is_entry_blocked (uniform wave interface)."""
    return _guard.is_entry_blocked(tick)


def update(tick: object = None) -> None:
    """Module-level alias → TickVelocityGuard.update()."""
    _guard.update(tick)


def reset() -> None:
    """Module-level alias → TickVelocityGuard.reset()."""
    _guard.reset()
