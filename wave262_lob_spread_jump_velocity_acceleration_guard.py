"""
wave262_lob_spread_jump_velocity_acceleration_guard.py
------------------------------------------------------
Guard: LOB Bid-Ask Spread Expansion Velocity & Acceleration Guard

Monitors dynamic expansion velocity and second-derivative acceleration of quoted bid-ask spread
(Wyart et al. 2008; Hasbrouck 2009; Cont, Kukanov & Stoikov 2014):
    Spread (bps):               S_{bps} = ((P_{ask} - P_{bid}) / P_{mid}) * 10^4
    Spread Expansion Velocity:  v_S = (S_{bps}(t) - S_{bps}(t-1)) / max(Delta t, 0.05)  (bps / sec)
    Spread Acceleration:        a_S = (v_S(t) - v_S(t-1)) / max(Delta t, 0.05)          (bps / sec^2)

Under orderly double-auction market conditions:
    - Bid-ask spread fluctuates mildly around a stable regime (v_S ~ 0, a_S ~ 0; |v_S| < 1.0 bps/s).
    - Market makers continuously replace filled quotes without sudden gap widening.

During liquidity shocks, quote cancellations, or predatory sweep front-running:
    - Both bid and ask liquidity withdraw rapidly, causing explosive spread dilation:
        1) High Spread Expansion Velocity:
           v_S >= MAX_SPREAD_VELOCITY (default: 3.50 bps/s) AND S_{bps} >= MIN_SPREAD_BPS (2.50 bps).
        2) Spread Explosion Acceleration Surge:
           a_S >= MAX_SPREAD_ACCEL (default: 6.00 bps/sec^2).
        3) Acute Spread Flash Jump:
           Delta S_{bps} >= MAX_ACUTE_SPREAD_JUMP (default: 4.50 bps) within Delta t <= 1.0s.

Entering trades into an accelerating or high-velocity expanding spread exposes executions to severe
broker slippage, wide spread penalties, and instantaneous adverse markouts.

When spread expansion velocity or acceleration surge is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests quotes via record_quote(bid_price, ask_price, ts=None) or
  direct kinematics via record_spread(spread_bps, velocity=None, accel=None, ts=None).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive prices, or crossed quotes (bid >= ask) are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_quote(bid_price, ask_price, ts=None)                                                  -> None
  record_spread(spread_bps, velocity=None, accel=None, ts=None)                                -> None
  update(bid_price, ask_price=None, ts=None)                                                   -> None   (alias)
  get_velocity_metrics()                                                                       -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import math
import threading
import time
from typing import Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_SPREAD_VELOCITY: float = 3.50       # 3.50 bps/sec spread expansion velocity threshold
MIN_SPREAD_BPS: float = 2.50            # 2.50 bps minimum spread for velocity trigger
MAX_SPREAD_ACCEL: float = 6.00          # 6.00 bps/sec^2 acceleration threshold
MAX_ACUTE_SPREAD_JUMP: float = 4.50     # 4.50 bps acute jump threshold
MIN_DELTA_T_SEC: float = 0.05           # 0.05s minimum delta t floor
COOLDOWN_SECONDS: float = 45.0          # 45.0s block duration

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_spread_bps: Optional[float] = None
_prev_spread_ts: Optional[float] = None
_prev_velocity: Optional[float] = None
_latest_spread_bps: float = 1.0
_latest_velocity: float = 0.0
_latest_acceleration: float = 0.0
_blocked_until: float = 0.0


def _is_valid_positive(val: Any) -> bool:
    """Validate value is a positive finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val > 0.0


def _is_valid_numeric(val: Any) -> bool:
    """Validate value is a finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return True


def record_spread(
    spread_bps: float,
    velocity: Optional[float] = None,
    accel: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Directly ingest precomputed spread basis points, velocity, and acceleration.
    """
    global _latest_spread_bps, _latest_velocity, _latest_acceleration, _blocked_until

    if not _is_valid_numeric(spread_bps):
        return

    s = float(spread_bps)
    v = float(velocity) if (velocity is not None and _is_valid_numeric(velocity)) else 0.0
    a = float(accel) if (accel is not None and _is_valid_numeric(accel)) else 0.0

    with _lock:
        _latest_spread_bps = s
        _latest_velocity = v
        _latest_acceleration = a

        # Condition 3: Acute spread jump
        if s >= MAX_ACUTE_SPREAD_JUMP:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 2: Spread acceleration surge
        if a >= MAX_SPREAD_ACCEL:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 1: High spread expansion velocity
        if v >= MAX_SPREAD_VELOCITY and s >= MIN_SPREAD_BPS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_quote(
    bid_price: float,
    ask_price: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest bid and ask quotes, calculate spread, expansion velocity, and acceleration.
    """
    global _prev_spread_bps, _prev_spread_ts, _prev_velocity
    global _latest_spread_bps, _latest_velocity, _latest_acceleration, _blocked_until

    if not (_is_valid_positive(bid_price) and _is_valid_positive(ask_price)):
        return

    bp = float(bid_price)
    ap = float(ask_price)

    # Reject crossed or inverted quote
    if bp >= ap:
        return

    mid = (bp + ap) / 2.0
    if mid <= 0.0:
        return

    spread_bps = ((ap - bp) / mid) * 10000.0
    now = float(ts) if (ts is not None and _is_valid_numeric(ts)) else time.time()

    with _lock:
        _latest_spread_bps = spread_bps

        if _prev_spread_bps is not None and _prev_spread_ts is not None:
            dt = max(MIN_DELTA_T_SEC, now - _prev_spread_ts)
            d_spread = spread_bps - _prev_spread_bps
            velocity = d_spread / dt
            _latest_velocity = velocity

            # Condition 3: Acute spread flash jump within 1.0s
            if dt <= 1.0 and d_spread >= MAX_ACUTE_SPREAD_JUMP:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                _prev_spread_bps = spread_bps
                _prev_spread_ts = now
                return

            if _prev_velocity is not None:
                accel = (velocity - _prev_velocity) / dt
                _latest_acceleration = accel

                # Condition 2: Spread acceleration surge
                if accel >= MAX_SPREAD_ACCEL:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                    _prev_spread_bps = spread_bps
                    _prev_spread_ts = now
                    _prev_velocity = velocity
                    return

            _prev_velocity = velocity

            # Condition 1: High spread expansion velocity
            if velocity >= MAX_SPREAD_VELOCITY and spread_bps >= MIN_SPREAD_BPS:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                _prev_spread_bps = spread_bps
                _prev_spread_ts = now
                return

        _prev_spread_bps = spread_bps
        _prev_spread_ts = now


def update(
    bid_price: float,
    ask_price: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """Module alias for record_quote or record_spread."""
    if ask_price is None:
        record_spread(bid_price, ts=ts)
    else:
        record_quote(bid_price, ask_price, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if entry is currently blocked by spread velocity guard."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked."""
    return is_entry_blocked()


def get_velocity_metrics() -> Dict[str, Any]:
    """Return dictionary of current spread velocity and acceleration metrics."""
    with _lock:
        return {
            "latest_spread_bps": round(_latest_spread_bps, 4),
            "latest_velocity": round(_latest_velocity, 4),
            "latest_acceleration": round(_latest_acceleration, 4),
            "max_spread_velocity": MAX_SPREAD_VELOCITY,
            "min_spread_bps": MIN_SPREAD_BPS,
            "max_spread_accel": MAX_SPREAD_ACCEL,
            "max_acute_spread_jump": MAX_ACUTE_SPREAD_JUMP,
            "is_blocked": is_entry_blocked(),
        }


def get_status() -> Dict[str, Any]:
    """Return complete status dictionary."""
    with _lock:
        remaining_cd = max(0.0, _blocked_until - time.monotonic())
        metrics = get_velocity_metrics()
        metrics["cooldown_remaining_sec"] = round(remaining_cd, 2)
        return metrics


def reset() -> None:
    """Reset all state to initial defaults."""
    global _prev_spread_bps, _prev_spread_ts, _prev_velocity
    global _latest_spread_bps, _latest_velocity, _latest_acceleration, _blocked_until
    with _lock:
        _prev_spread_bps = None
        _prev_spread_ts = None
        _prev_velocity = None
        _latest_spread_bps = 1.0
        _latest_velocity = 0.0
        _latest_acceleration = 0.0
        _blocked_until = 0.0
