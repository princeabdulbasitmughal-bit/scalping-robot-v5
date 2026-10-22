"""
wave201_order_flow_imbalance_curvature_guard.py
------------------------------------------------
Guard: Order Flow Imbalance (OFI) Higher-Order Curvature & Hydrodynamic Shock Guard

Monitors higher-order order flow imbalance dynamics and non-linear acceleration using the
Cont-Kukanov-Stoikov (2014) L1 OFI formulation:
    OFI_t = I_{P_{b,t} >= P_{b,t-1}} * Q_{b,t} - I_{P_{b,t} <= P_{b,t-1}} * Q_{b,t-1}
          - I_{P_{a,t} <= P_{a,t-1}} * Q_{a,t} + I_{P_{a,t} >= P_{a,t-1}} * Q_{a,t-1}

First discrete derivative (OFI Velocity):
    v_{OFI, t} = OFI_t / dt          (lots/second)

Second discrete derivative (OFI Curvature / Acceleration):
    kappa_{OFI, t} = (v_{OFI, t} - v_{OFI, t-1}) / dt   (lots/second^2)

In balanced double-auction order books, order flow imbalance transitions smoothly:
    |kappa_{OFI}| < 6.0 lots/second^2.

During hydrodynamic book shockwaves—such as aggressive institutional sweeps, sudden quote
stuffing cancellations, or rapid front-running depth extraction—OFI curvature surges non-linearly:
    |kappa_{OFI}| >= MAX_OFI_CURVATURE (default: 12.0 lots/sec^2)
    with instantaneous OFI shock magnitude |OFI_t| >= MIN_OFI_SHOCK (default: 2.0 lots).

This extreme non-linear order flow acceleration indicates impending violent price jump dislocations
and book-clearing sweeps.

When OFI curvature breaches safety limits, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests top-of-book updates (bid_price, bid_depth, ask_price, ask_depth, ts=None).
- Computes single-step Cont-Kukanov-Stoikov OFI.
- Computes OFI velocity and OFI curvature over dt <= 0.50s.
- Evaluates if |kappa_{OFI}| >= MAX_OFI_CURVATURE (12.0 lots/sec^2).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, negative depths, or inverted prices are rejected.

Aliases (required):
  is_entry_blocked()                                                             -> bool
  is_blocked()                                                                   -> bool   (alias)
  record_book(bid_price, bid_depth, ask_price, ask_depth, ts=None)               -> None
  update(bid_price, bid_depth, ask_price, ask_depth, ts=None)                    -> None   (alias)
  get_ofi_metrics()                                                              -> dict
  get_status()                                                                   -> dict
  reset()                                                                        -> None
"""

import math
import threading
import time
from typing import Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_OFI_CURVATURE: float = 12.0        # 12.0 lots/second^2
MIN_OFI_SHOCK: float = 2.0             # 2.0 lots minimum OFI magnitude
MAX_EVAL_DT: float = 0.50              # max interval (seconds) for derivative estimation
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_bp: Optional[float] = None
_prev_bq: Optional[float] = None
_prev_ap: Optional[float] = None
_prev_aq: Optional[float] = None
_prev_ts: Optional[float] = None
_prev_ofi_velocity: Optional[float] = None
_latest_ofi: float = 0.0
_latest_ofi_velocity: float = 0.0
_latest_ofi_curvature: float = 0.0
_blocked_until: float = 0.0


def _is_valid_price(val: Any) -> bool:
    """Validate price is a positive finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val > 0.0


def _is_valid_depth(val: Any) -> bool:
    """Validate depth is a non-negative finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val >= 0.0


def record_book(
    bid_price: float,
    bid_depth: float,
    ask_price: float,
    ask_depth: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest a new top-of-book state, compute OFI, velocity, and curvature.
    """
    global _prev_bp, _prev_bq, _prev_ap, _prev_aq, _prev_ts, _prev_ofi_velocity
    global _latest_ofi, _latest_ofi_velocity, _latest_ofi_curvature, _blocked_until

    if not _is_valid_price(bid_price) or not _is_valid_price(ask_price):
        return
    if not _is_valid_depth(bid_depth) or not _is_valid_depth(ask_depth):
        return
    if float(ask_price) <= float(bid_price):
        return

    bp = float(bid_price)
    bq = float(bid_depth)
    ap = float(ask_price)
    aq = float(ask_depth)

    with _lock:
        now = time.monotonic() if ts is None else float(ts)

        if _prev_bp is None or _prev_bq is None or _prev_ap is None or _prev_aq is None or _prev_ts is None:
            _prev_bp = bp
            _prev_bq = bq
            _prev_ap = ap
            _prev_aq = aq
            _prev_ts = now
            return

        dt = now - _prev_ts
        if 0.0 < dt <= MAX_EVAL_DT:
            # Cont-Kukanov-Stoikov OFI formulation
            # Bid side contribution
            if bp > _prev_bp:
                delta_bid = bq
            elif bp == _prev_bp:
                delta_bid = bq - _prev_bq
            else:
                delta_bid = -_prev_bq

            # Ask side contribution
            if ap < _prev_ap:
                delta_ask = aq
            elif ap == _prev_ap:
                delta_ask = aq - _prev_aq
            else:
                delta_ask = -_prev_aq

            ofi = delta_bid - delta_ask
            _latest_ofi = ofi

            v_ofi = ofi / dt
            _latest_ofi_velocity = v_ofi

            # Curvature calculation if previous velocity exists
            if _prev_ofi_velocity is not None:
                curvature = (v_ofi - _prev_ofi_velocity) / dt
                _latest_ofi_curvature = curvature

                # Check Condition: Extreme OFI curvature surge
                if abs(curvature) >= MAX_OFI_CURVATURE and abs(ofi) >= MIN_OFI_SHOCK:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                    _prev_bp = bp
                    _prev_bq = bq
                    _prev_ap = ap
                    _prev_aq = aq
                    _prev_ts = now
                    _prev_ofi_velocity = v_ofi
                    return

            _prev_ofi_velocity = v_ofi

        _prev_bp = bp
        _prev_bq = bq
        _prev_ap = ap
        _prev_aq = aq
        _prev_ts = now


def update(
    bid_price: float,
    bid_depth: float,
    ask_price: float,
    ask_depth: float,
    ts: Optional[float] = None,
) -> None:
    """Alias for record_book()."""
    record_book(bid_price, bid_depth, ask_price, ask_depth, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to OFI curvature."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_ofi_metrics() -> Dict[str, float]:
    """Return latest calculated OFI, OFI velocity, and OFI curvature."""
    with _lock:
        return {
            "ofi": _latest_ofi,
            "ofi_velocity": _latest_ofi_velocity,
            "ofi_curvature": _latest_ofi_curvature,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the OFI curvature guard."""
    with _lock:
        now = time.monotonic()
        return {
            "ofi": _latest_ofi,
            "ofi_velocity": _latest_ofi_velocity,
            "ofi_curvature": _latest_ofi_curvature,
            "max_curvature_threshold": MAX_OFI_CURVATURE,
            "min_shock_threshold": MIN_OFI_SHOCK,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset book history, OFI metrics, and active cooldown blocks."""
    global _prev_bp, _prev_bq, _prev_ap, _prev_aq, _prev_ts, _prev_ofi_velocity
    global _latest_ofi, _latest_ofi_velocity, _latest_ofi_curvature, _blocked_until
    with _lock:
        _prev_bp = None
        _prev_bq = None
        _prev_ap = None
        _prev_aq = None
        _prev_ts = None
        _prev_ofi_velocity = None
        _latest_ofi = 0.0
        _latest_ofi_velocity = 0.0
        _latest_ofi_curvature = 0.0
        _blocked_until = 0.0
