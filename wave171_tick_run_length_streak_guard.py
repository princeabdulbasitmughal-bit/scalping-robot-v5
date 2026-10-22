"""
wave171_tick_run_length_streak_guard.py
---------------------------------------
Guard: Monotonic Tick Directional Run Length Streak Guard

Monitors consecutive monotonic price tick movements to detect aggressive institutional sweeps:
    d_t = sign(P_t - P_{t-1}) in {+1, -1}
    Streak_t = Streak_{t-1} + 1  if d_t == d_{t-1}  else 1

In liquid two-sided markets, prices advance with frequent micro-pullbacks and bid-ask alternating prints.
When an aggressive institutional sweeping algorithm cleans out the limit order book, prices tick
in an unbroken monotonic streak (e.g. >= 8 consecutive ticks in one direction without an opposing print).
Placing limit orders or counter-trend scalps in front of a monotonic sweep algorithm results
in immediate adverse fills as momentum continues through the level.
When Streak >= MAX_STREAK (default: 8 monotonic ticks), an entry block is engaged for
COOLDOWN_SECONDS (default: 30.0s).

Logic:
- Records price ticks and computes direction sign (+1 up, -1 down; ignores flat 0).
- Tracks consecutive identical direction run length.
- Resets streak counter upon opposing tick.
- If streak >= MAX_STREAK (8 ticks):
    blocks entries for COOLDOWN_SECONDS (30.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive prices are ignored.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_price(price, ts=None)                             -> None
  update(price, ts=None)                                   -> None   (alias)
  get_streak_length()                                      -> int
  get_streak_direction()                                   -> int
  reset()                                                  -> None
"""

import math
import threading
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_STREAK: int = 8                # 8 consecutive monotonic ticks trigger sweeping guard
COOLDOWN_SECONDS: float = 30.0     # Block duration in seconds on monotonic sweep


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_price: Optional[float] = None
_current_dir: int = 0
_streak: int = 0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_price(price, ts=None) -> None:
    """Record an incoming price tick and evaluate monotonic directional streak length."""
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return

    p = float(price)

    global _prev_price, _current_dir, _streak, _blocked_until
    with _lock:
        if _prev_price is None:
            _prev_price = p
            return

        diff = p - _prev_price
        _prev_price = p

        if abs(diff) < 1e-9:
            # Flat tick: do not alter directional streak
            return

        direction = 1 if diff > 0.0 else -1

        if direction == _current_dir:
            _streak += 1
        else:
            _current_dir = direction
            _streak = 1

        if _streak >= MAX_STREAK:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(price, ts=None) -> None:
    """Alias for record_price()."""
    record_price(price, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if monotonic tick streak has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_streak_length() -> int:
    """Return the current consecutive monotonic run length."""
    with _lock:
        return _streak


def get_streak_direction() -> int:
    """Return the current monotonic run direction (+1 up, -1 down, 0 neutral)."""
    with _lock:
        return _current_dir


def reset() -> None:
    """Reset price state, direction, streak counter, and active cooldown."""
    global _prev_price, _current_dir, _streak, _blocked_until
    with _lock:
        _prev_price = None
        _current_dir = 0
        _streak = 0
        _blocked_until = 0.0
