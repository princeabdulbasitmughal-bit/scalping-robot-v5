"""
wave185_signed_volume_acceleration_guard.py
--------------------------------------------
Guard: Signed Order Flow Volume Acceleration & Jerk Guard

Monitors the second derivative (acceleration) of signed order flow:
    V_signed = sign * volume
    Velocity_flow = V_signed / dt       (lots per second)
    Acceleration_flow = d(Velocity) / dt (lots per second^2)

In steady continuous trading, order flow arrival rates are relatively uniform or evolve smoothly
(acceleration |a| <= 5.0 lots/sec^2).
However, when aggressive institutional algorithms (e.g. predatory Percentage of Volume [POV],
TWAP ramps, or stops clearing sweeps) aggressively accelerate their participation rate into the book,
the order flow rate exhibits massive convex non-linear expansion (jerk surge):
    |Acceleration_flow| >= MAX_ACCELERATION (default: 15.0 lots/sec^2)

This sudden flow acceleration indicates that an institutional predator is aggressively steamrolling
standing limit orders at an increasing velocity. Counter-trend scalping into an accelerating
institutional surge is hazardous.

When signed flow acceleration exceeds MAX_ACCELERATION, the guard blocks entry orders for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade executions (price, volume, optional ts, optional sign).
- Derives trade sign via tick rule if not explicitly provided.
- Computes instantaneous flow velocity (lots/sec) and flow acceleration (lots/sec^2).
- Validates dt interval to avoid division by zero or stale multi-minute gaps (0.005s <= dt <= 2.0s).
- If |Acceleration_flow| >= MAX_ACCELERATION (15.0 lots/sec^2):
    blocks entries for COOLDOWN_SECONDS (45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive values are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_trade(price, volume, ts=None, sign=None)          -> None
  update(price, volume, ts=None, sign=None)               -> None   (alias)
  get_flow_acceleration()                                  -> float
  get_status()                                             -> dict
  reset()                                                  -> None
"""

import math
import threading
import time
from typing import Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_ACCELERATION: float = 15.0        # 15.0 lots/sec^2 acceleration indicates predatory flow surge
MIN_DT_SEC: float = 0.005             # 5 milliseconds minimum interval
MAX_DT_SEC: float = 2.000             # 2.0 seconds maximum interval
COOLDOWN_SECONDS: float = 45.0        # Block duration on flow acceleration surge


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_price: Optional[float] = None
_prev_sign: int = 1
_prev_ts: Optional[float] = None
_prev_velocity: Optional[float] = None
_latest_acceleration: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_trade(price, volume, ts=None, sign=None) -> None:
    """Record an incoming trade execution and evaluate signed volume flow acceleration."""
    for val in (price, volume):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return
        if math.isnan(val) or math.isinf(val) or val <= 0.0:
            return

    p = float(price)
    v = float(volume)

    if ts is not None:
        if isinstance(ts, bool) or not isinstance(ts, (int, float)):
            return
        if math.isnan(ts) or math.isinf(ts) or ts < 0.0:
            return
        current_ts = float(ts)
    else:
        current_ts = time.monotonic()

    global _prev_price, _prev_sign, _prev_ts, _prev_velocity, _latest_acceleration, _blocked_until
    with _lock:
        if sign is not None:
            if isinstance(sign, bool) or not isinstance(sign, (int, float)):
                s = 1
            else:
                s = 1 if float(sign) > 0.0 else -1
        elif _prev_price is not None:
            if p > _prev_price:
                s = 1
            elif p < _prev_price:
                s = -1
            else:
                s = _prev_sign
        else:
            s = 1

        _prev_price = p
        _prev_sign = s

        if _prev_ts is not None:
            dt = current_ts - _prev_ts

            if MIN_DT_SEC <= dt <= MAX_DT_SEC:
                # Signed volume rate for this trade: lots/sec
                signed_vol = float(s) * v
                current_velocity = signed_vol / dt

                if _prev_velocity is not None:
                    # Acceleration: d(velocity) / dt in lots/sec^2
                    accel = (current_velocity - _prev_velocity) / dt
                    _latest_acceleration = accel

                    if abs(accel) >= MAX_ACCELERATION:
                        _blocked_until = time.monotonic() + COOLDOWN_SECONDS

                _prev_velocity = current_velocity
            else:
                _prev_velocity = None

        _prev_ts = current_ts


def update(price, volume, ts=None, sign=None) -> None:
    """Alias for record_trade()."""
    record_trade(price, volume, ts=ts, sign=sign)


def is_entry_blocked() -> bool:
    """Return True if signed flow acceleration has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_flow_acceleration() -> float:
    """Return the most recently computed signed volume flow acceleration."""
    with _lock:
        return _latest_acceleration


def get_status() -> Dict[str, Any]:
    """Return a diagnostic snapshot of the signed volume acceleration guard state."""
    with _lock:
        now = time.monotonic()
        return {
            "latest_acceleration": _latest_acceleration,
            "max_acceleration_threshold": MAX_ACCELERATION,
            "prev_velocity": _prev_velocity,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset price state, velocity, acceleration metrics, and active blocks."""
    global _prev_price, _prev_sign, _prev_ts, _prev_velocity, _latest_acceleration, _blocked_until
    with _lock:
        _prev_price = None
        _prev_sign = 1
        _prev_ts = None
        _prev_velocity = None
        _latest_acceleration = 0.0
        _blocked_until = 0.0
