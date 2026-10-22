"""
wave160_order_book_depth_imbalance_acceleration_guard.py
--------------------------------------------------------
Guard: Order Book Depth Imbalance Acceleration (d^2(OBI)/dt^2) Guard

Monitors second-order dynamic acceleration of the Order Book Imbalance (OBI):
    OBI_t = (Bid_Depth - Ask_Depth) / (Bid_Depth + Ask_Depth)  in [-1.0, +1.0]
    Velocity_t = (OBI_t - OBI_{t-1}) / Delta_t
    Acceleration_t = (Velocity_t - Velocity_{t-1}) / Delta_t

Static order book depth imbalance indicates prevailing pressure, but institutional liquidity
cascades (e.g. predatory sweeping or spoof pulling) are characterized by violent *acceleration*
where one side of the book evaporates within milliseconds while the opposite side stacks aggressively.
When |Acceleration| >= MAX_OBI_ACCEL (default: 4.0 s^-2), an impending liquidity void is detected,
triggering an entry block for COOLDOWN_SECONDS (default: 45.0s) to prevent entering in front of
an institutional depth collapse.

Logic:
- Records bid and ask depth and timestamp.
- Validates non-negative depths, non-NaN, non-Inf, non-boolean.
- Computes Order Book Imbalance OBI in [-1.0, +1.0].
- Computes first derivative (velocity) and second derivative (acceleration).
- If |Acceleration| >= MAX_OBI_ACCEL (4.0 s^-2):
    blocks entries for COOLDOWN_SECONDS (45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: invalid depths or degenerate timestamps are ignored.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_depth(bid_depth, ask_depth, ts=None)              -> None
  update(bid_depth, ask_depth, ts=None)                   -> None   (alias)
  get_imbalance_acceleration()                             -> float
  reset()                                                  -> None
"""

import math
import threading
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_OBI_ACCEL: float = 4.0         # 4.0 s^-2 acceleration triggers imbalance runaway guard
MIN_DT: float = 0.005              # 5ms minimum delta time threshold
COOLDOWN_SECONDS: float = 45.0     # Block duration in seconds on acceleration shock


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_obi: Optional[float] = None
_prev_velocity: Optional[float] = None
_prev_ts: Optional[float] = None
_latest_accel: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_depth(bid_depth, ask_depth, ts=None) -> None:
    """Record bid and ask depth, evaluating dynamic imbalance acceleration."""
    for val in (bid_depth, ask_depth):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return
        if math.isnan(val) or math.isinf(val):
            return

    b = float(bid_depth)
    a = float(ask_depth)

    if b < 0.0 or a < 0.0 or (b + a) <= 1e-9:
        return

    obi = (b - a) / (b + a)
    now = float(ts) if (ts is not None and isinstance(ts, (int, float)) and not isinstance(ts, bool)) else time.monotonic()

    global _prev_obi, _prev_velocity, _prev_ts, _latest_accel, _blocked_until
    with _lock:
        if _prev_ts is None or now <= _prev_ts:
            _prev_ts = now
            _prev_obi = obi
            return

        dt = now - _prev_ts
        if dt < MIN_DT:
            return

        velocity = (obi - _prev_obi) / dt
        _prev_ts = now
        _prev_obi = obi

        if _prev_velocity is None:
            _prev_velocity = velocity
            return

        accel = (velocity - _prev_velocity) / dt
        _prev_velocity = velocity
        _latest_accel = accel

        if abs(accel) >= MAX_OBI_ACCEL:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(bid_depth, ask_depth, ts=None) -> None:
    """Alias for record_depth()."""
    record_depth(bid_depth, ask_depth, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if depth imbalance acceleration has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_imbalance_acceleration() -> float:
    """Return the most recently calculated OBI acceleration (s^-2)."""
    with _lock:
        return _latest_accel


def reset() -> None:
    """Reset depth state, velocity, acceleration, and active cooldown."""
    global _prev_obi, _prev_velocity, _prev_ts, _latest_accel, _blocked_until
    with _lock:
        _prev_obi = None
        _prev_velocity = None
        _prev_ts = None
        _latest_accel = 0.0
        _blocked_until = 0.0
