"""
wave145_drawdown_velocity_expansion_guard.py
--------------------------------------------
Guard: Drawdown Velocity Expansion & Acceleration Guard

Monitors the second derivative of account drawdown from High-Water Mark (HWM):
    DD_t = max(0, HWM - Equity_t)
    v_t = d(DD)/dt  (loss accumulation rate, USD/s)
    a_t = d(v)/dt = d^2(DD)/dt^2  (drawdown acceleration, USD/s^2)
When loss velocity rapidly expands, it signals cascading stop triggers across multiple
active positions or runaway market expansion against open inventory.

Logic:
- Records timestamped account equity values.
- Updates high-water mark (HWM) and evaluates absolute drawdown.
- Calculates loss velocity and velocity expansion acceleration:
    v = (DD_curr - DD_prev) / dt
    a = (v - v_prev) / dt
- If a >= MAX_DD_ACCELERATION (default: 4.0 USD/s^2) with dt >= 0.01s:
    blocks entries for COOLDOWN_SECONDS (default: 90.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Fail-closed: invalid, non-numeric, boolean, NaN, and Inf equity values ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()             -> bool
  is_blocked()                   -> bool   (alias)
  record_equity(equity, ts=None) -> None
  update(equity, ts=None)        -> None   (alias)
  get_drawdown_acceleration()    -> float
  reset()                        -> None
"""

import math
import threading
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_DD_ACCELERATION: float = 4.0       # loss acceleration limit in USD / sec^2
COOLDOWN_SECONDS: float = 90.0         # duration of protective block on drawdown spike
MIN_DT: float = 0.01                   # minimum time delta to avoid microsecond noise


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_hwm: Optional[float] = None
_prev_dd: float = 0.0
_prev_time: Optional[float] = None
_prev_velocity: float = 0.0
_current_acceleration: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_equity(equity, ts=None) -> None:
    """Record equity snapshot and evaluate drawdown velocity expansion."""
    if isinstance(equity, bool) or not isinstance(equity, (int, float)):
        return
    if math.isnan(equity) or math.isinf(equity):
        return

    eq = float(equity)
    now = float(ts) if (ts is not None and isinstance(ts, (int, float)) and not isinstance(ts, bool)) else time.monotonic()

    global _hwm, _prev_dd, _prev_time, _prev_velocity, _current_acceleration, _blocked_until
    with _lock:
        if _hwm is None or eq > _hwm:
            _hwm = eq

        dd = max(0.0, _hwm - eq)

        if _prev_time is None:
            _prev_time = now
            _prev_dd = dd
            _prev_velocity = 0.0
            _current_acceleration = 0.0
            return

        dt = now - _prev_time
        if dt >= MIN_DT:
            velocity = (dd - _prev_dd) / dt
            accel = (velocity - _prev_velocity) / dt
            _current_acceleration = accel
            _prev_velocity = velocity
            _prev_dd = dd
            _prev_time = now

            if accel >= MAX_DD_ACCELERATION:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(equity, ts=None) -> None:
    """Alias for record_equity()."""
    record_equity(equity, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if drawdown acceleration has activated an entry block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_drawdown_acceleration() -> float:
    """Return the most recently computed drawdown acceleration."""
    with _lock:
        return _current_acceleration


def reset() -> None:
    """Reset HWM, drawdown tracking, acceleration, and active block."""
    global _hwm, _prev_dd, _prev_time, _prev_velocity, _current_acceleration, _blocked_until
    with _lock:
        _hwm = None
        _prev_dd = 0.0
        _prev_time = None
        _prev_velocity = 0.0
        _current_acceleration = 0.0
        _blocked_until = 0.0
