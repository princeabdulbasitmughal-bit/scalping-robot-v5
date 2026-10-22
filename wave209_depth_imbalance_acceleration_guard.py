"""
wave209_depth_imbalance_acceleration_guard.py
----------------------------------------------
Guard: Order Book Depth Imbalance Acceleration Guard

Monitors higher-order acceleration of top-of-book depth imbalance (Cartea, Jaimungal, Ricci 2014):
    Imbalance:     rho_t = (Q_{bid, t} - Q_{ask, t}) / max(1e-6, Q_{bid, t} + Q_{ask, t}) in [-1, +1]
    Velocity:      v_{rho, t} = (rho_t - rho_{t-1}) / dt
    Acceleration:  a_{rho, t} = (v_{rho, t} - v_{rho, t-1}) / dt
where dt <= 0.50 seconds.

In orderly double-auction books with balanced liquidity provision, depth builds and cancels gradually:
    |a_{rho}| < 4.0 s^{-2}.

During predatory order book manipulations—such as rapid quote stuffing, sudden unilateral quote
cancellations, or massive iceberg depth loading on one side:
    |a_{rho, t}| >= MAX_IMBALANCE_ACCELERATION (default: 10.0 s^{-2})
    with significant single-step imbalance shift (|rho_t - rho_{t-1}| >= MIN_IMBALANCE_SHIFT = 0.40).

This violent non-linear depth acceleration signals an imminent order-clearing price jump and
severe adverse selection.

When depth imbalance acceleration breaches safety limits, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests top-of-book depths (bid_depth >= 0.0, ask_depth >= 0.0, ts=None).
- Computes normalized depth imbalance rho_t.
- Computes imbalance velocity and acceleration over dt <= 0.50s.
- Evaluates if |a_{rho, t}| >= MAX_IMBALANCE_ACCELERATION (10.0 s^{-2}).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative depth inputs are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_depth(bid_depth, ask_depth, ts=None)              -> None
  update(bid_depth, ask_depth, ts=None)                    -> None   (alias)
  get_imbalance_metrics()                                  -> dict
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
MAX_IMBALANCE_ACCELERATION: float = 10.0   # 10.0 s^{-2} acceleration
MIN_IMBALANCE_SHIFT: float = 0.40          # 0.40 minimum absolute imbalance shift
MAX_EVAL_DT: float = 0.50                  # 500ms maximum interval for derivative estimation
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_rho: Optional[float] = None
_prev_ts: Optional[float] = None
_prev_velocity: Optional[float] = None
_latest_rho: float = 0.0
_latest_velocity: float = 0.0
_latest_acceleration: float = 0.0
_blocked_until: float = 0.0


def _is_valid_depth(val: Any) -> bool:
    """Validate depth is a non-negative finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val >= 0.0


def record_depth(bid_depth: float, ask_depth: float, ts: Optional[float] = None) -> None:
    """
    Ingest a new depth update and calculate imbalance velocity and acceleration.
    """
    global _prev_rho, _prev_ts, _prev_velocity
    global _latest_rho, _latest_velocity, _latest_acceleration, _blocked_until

    if not _is_valid_depth(bid_depth) or not _is_valid_depth(ask_depth):
        return

    bd = float(bid_depth)
    ad = float(ask_depth)
    tot = bd + ad
    if tot <= 1e-9:
        return

    rho = (bd - ad) / tot

    with _lock:
        now = time.monotonic() if ts is None else float(ts)

        if _prev_rho is None or _prev_ts is None:
            _prev_rho = rho
            _prev_ts = now
            return

        dt = now - _prev_ts
        if 0.0 < dt <= MAX_EVAL_DT:
            shift = rho - _prev_rho
            v_rho = shift / dt
            _latest_rho = rho
            _latest_velocity = v_rho

            if _prev_velocity is not None:
                a_rho = (v_rho - _prev_velocity) / dt
                _latest_acceleration = a_rho

                # Check Condition: Extreme imbalance acceleration with significant shift
                if abs(a_rho) >= MAX_IMBALANCE_ACCELERATION and abs(shift) >= MIN_IMBALANCE_SHIFT:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                    _prev_rho = rho
                    _prev_ts = now
                    _prev_velocity = v_rho
                    return

            _prev_velocity = v_rho

        _prev_rho = rho
        _prev_ts = now


def update(bid_depth: float, ask_depth: float, ts: Optional[float] = None) -> None:
    """Alias for record_depth()."""
    record_depth(bid_depth, ask_depth, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to depth imbalance acceleration."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_imbalance_metrics() -> Dict[str, float]:
    """Return latest calculated imbalance, velocity, and acceleration."""
    with _lock:
        return {
            "imbalance": _latest_rho,
            "velocity": _latest_velocity,
            "acceleration": _latest_acceleration,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the depth imbalance acceleration guard."""
    with _lock:
        now = time.monotonic()
        return {
            "imbalance": _latest_rho,
            "velocity": _latest_velocity,
            "acceleration": _latest_acceleration,
            "max_acceleration_threshold": MAX_IMBALANCE_ACCELERATION,
            "min_imbalance_shift": MIN_IMBALANCE_SHIFT,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset depth history, imbalance metrics, and active cooldown blocks."""
    global _prev_rho, _prev_ts, _prev_velocity
    global _latest_rho, _latest_velocity, _latest_acceleration, _blocked_until
    with _lock:
        _prev_rho = None
        _prev_ts = None
        _prev_velocity = None
        _latest_rho = 0.0
        _latest_velocity = 0.0
        _latest_acceleration = 0.0
        _blocked_until = 0.0
