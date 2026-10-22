"""
wave187_order_flow_imbalance_curvature_guard.py
------------------------------------------------
Guard: Order Flow Imbalance Curvature & Non-Linear Convexity Guard

Measures the second-order derivative (curvature/acceleration) of Cont & Kukanov (2014) Level-1
Order Flow Imbalance (OFI):
    OFI_t = delta_L1_bid - delta_L1_ask
    Velocity_OFI = OFI_t / dt
    Curvature_OFI = d(Velocity_OFI) / dt

In stable two-sided market making regimes, order flow imbalance evolves linearly with low curvature
(|Curvature_OFI| < 2.0 lots/sec^2), allowing market makers to comfortably lean against incoming flow.
When large institutional algorithmic execution engines (e.g. predatory book sweepers, liquidity
vacuum drains, or sudden stops cascades) trigger, OFI exhibits extreme non-linear parabolic curvature:
    |Curvature_OFI| >= MAX_CURVATURE (default: 5.0 lots/sec^2)

This sharp curvature indicates that one side of the order book is rapidly accelerating in absorption
or evaporation, immediately preceding a catastrophic liquidity gap fill.

When OFI curvature exceeds MAX_CURVATURE, the guard blocks entry orders for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests top-of-book quotes and depth (bid, ask, bid_depth, ask_depth, ts=None).
- Calculates Cont-Kukanov Level-1 Order Flow Imbalance (OFI).
- Computes OFI velocity and acceleration across high-frequency time steps dt (0.005s <= dt <= 2.0s).
- Evaluates curvature: kappa = a / (1.0 + (0.01 * v)^2)^1.5.
- If |kappa| >= MAX_CURVATURE (5.0 lots/sec^2):
    blocks entries for COOLDOWN_SECONDS (45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive prices/depths, or crossed quotes are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_book(bid, ask, bid_depth, ask_depth, ts=None)      -> None
  update(bid, ask, bid_depth, ask_depth, ts=None)          -> None   (alias)
  get_ofi_curvature()                                      -> float
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
MAX_CURVATURE: float = 5.0            # 5.0 lots/sec^2 curvature indicates non-linear book collapse
MIN_DT_SEC: float = 0.005             # 5 milliseconds minimum interval
MAX_DT_SEC: float = 2.000             # 2.0 seconds maximum interval
COOLDOWN_SECONDS: float = 45.0        # Block duration on OFI curvature surge


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_bid: Optional[float] = None
_prev_ask: Optional[float] = None
_prev_b_depth: Optional[float] = None
_prev_a_depth: Optional[float] = None
_prev_ts: Optional[float] = None
_prev_velocity: Optional[float] = None
_latest_curvature: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_book(bid, ask, bid_depth, ask_depth, ts=None) -> None:
    """Record Level-1 quotes and evaluate Order Flow Imbalance curvature."""
    for val in (bid, ask, bid_depth, ask_depth):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return
        if math.isnan(val) or math.isinf(val) or val <= 0.0:
            return

    b = float(bid)
    a = float(ask)
    qb = float(bid_depth)
    qa = float(ask_depth)

    if b > a:
        return

    if ts is not None:
        if isinstance(ts, bool) or not isinstance(ts, (int, float)):
            return
        if math.isnan(ts) or math.isinf(ts) or ts < 0.0:
            return
        current_ts = float(ts)
    else:
        current_ts = time.monotonic()

    global _prev_bid, _prev_ask, _prev_b_depth, _prev_a_depth, _prev_ts, _prev_velocity, _latest_curvature, _blocked_until
    with _lock:
        if _prev_bid is None or _prev_ask is None or _prev_b_depth is None or _prev_a_depth is None or _prev_ts is None:
            _prev_bid = b
            _prev_ask = a
            _prev_b_depth = qb
            _prev_a_depth = qa
            _prev_ts = current_ts
            return

        dt = current_ts - _prev_ts

        # Calculate Cont-Kukanov Level-1 OFI
        # Bid side
        if b > _prev_bid:
            delta_b = qb
        elif abs(b - _prev_bid) < 1e-9:
            delta_b = qb - _prev_b_depth
        else:
            delta_b = -_prev_b_depth

        # Ask side
        if a < _prev_ask:
            delta_a = qa
        elif abs(a - _prev_ask) < 1e-9:
            delta_a = qa - _prev_a_depth
        else:
            delta_a = -_prev_a_depth

        ofi = delta_b - delta_a

        if MIN_DT_SEC <= dt <= MAX_DT_SEC:
            velocity = ofi / dt

            if _prev_velocity is not None:
                accel = (velocity - _prev_velocity) / dt
                # Curvature with moderate scaling
                scale = 1.0 + (0.01 * velocity) ** 2
                curvature = accel / (scale ** 1.5)
                _latest_curvature = curvature

                if abs(curvature) >= MAX_CURVATURE:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS

            _prev_velocity = velocity
        else:
            _prev_velocity = None

        _prev_bid = b
        _prev_ask = a
        _prev_b_depth = qb
        _prev_a_depth = qa
        _prev_ts = current_ts


def update(bid, ask, bid_depth, ask_depth, ts=None) -> None:
    """Alias for record_book()."""
    record_book(bid, ask, bid_depth, ask_depth, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if OFI curvature has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_ofi_curvature() -> float:
    """Return the most recently computed OFI curvature."""
    with _lock:
        return _latest_curvature


def get_status() -> Dict[str, Any]:
    """Return a diagnostic snapshot of the OFI curvature guard state."""
    with _lock:
        now = time.monotonic()
        return {
            "ofi_curvature": _latest_curvature,
            "max_curvature_threshold": MAX_CURVATURE,
            "prev_velocity": _prev_velocity,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset book state, OFI velocity, curvature metrics, and active blocks."""
    global _prev_bid, _prev_ask, _prev_b_depth, _prev_a_depth, _prev_ts, _prev_velocity, _latest_curvature, _blocked_until
    with _lock:
        _prev_bid = None
        _prev_ask = None
        _prev_b_depth = None
        _prev_a_depth = None
        _prev_ts = None
        _prev_velocity = None
        _latest_curvature = 0.0
        _blocked_until = 0.0
