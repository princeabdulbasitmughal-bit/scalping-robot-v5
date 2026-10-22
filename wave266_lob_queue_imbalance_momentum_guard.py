"""
wave266_lob_queue_imbalance_momentum_guard.py
----------------------------------------------
Guard: LOB Top-of-Book Queue Imbalance Momentum & Flow Velocity Guard

Monitors static queue volume disparity and dynamic imbalance flow velocity at the top of the limit order book
(Cont, Kukanov & Stoikov 2014; Cartea, Jaimungal & Penalva 2015):
    Total Top Depth:            Q_{total} = Q_{bid} + Q_{ask}
    Queue Imbalance:            I = (Q_{bid} - Q_{ask}) / max(Q_{total}, 0.10) in [-1.0, 1.0]
    Imbalance Velocity:         v_I = (I(t) - I(t-1)) / max(Delta t, 0.05) (units / sec)
    Dynamic Swing:              Delta I = |I(t) - I(t-1)|

Under balanced, symmetrical continuous double-auction conditions:
    - Order book queues are roughly balanced on both sides: |I| <= 0.40.
    - Imbalance changes smoothly with low velocity (|v_I| < 0.50 units/sec).

During predatory book tilting, one-sided quote pulling, or directional liquidity draining:
    - Queue depth tilts heavily and shifts with explosive velocity:
        1) Severe Directional Queue Imbalance:
           |I| >= MAX_QUEUE_IMBALANCE (default: 0.80) with Q_{total} >= MIN_COMBINED_DEPTH (5.0 lots).
        2) Explosive Imbalance Flow Velocity:
           |v_I| >= MAX_IMBALANCE_VELOCITY (default: 1.50 units/s) with Delta I >= MIN_IMBALANCE_SWING (0.60).
        3) Acute Flank Liquidity Blanking:
           One side <= 0.15 lots while opposing side >= 6.0 lots (ratio >= 40x).

Submitting orders into a severely tilted or rapidly tilting order book results in immediate price-step
slippage, adverse fill selection, and predatory front-running.

When severe queue imbalance or rapid flow velocity is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests top depths via record_depths(bid_depth, ask_depth, ts=None) or
  direct kinematics via record_imbalance(imbalance, velocity=None, total_depth=None, ts=None).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative depths are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_depths(bid_depth, ask_depth, ts=None)                                                 -> None
  record_imbalance(imbalance, velocity=None, total_depth=None, ts=None)                        -> None
  update(bid_depth, ask_depth=None, ts=None)                                                   -> None   (alias)
  get_imbalance_metrics()                                                                      -> dict
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
MAX_QUEUE_IMBALANCE: float = 0.80       # 80% directional imbalance threshold
MIN_COMBINED_DEPTH: float = 5.0         # 5.0 lots minimum combined depth for static trigger
MAX_IMBALANCE_VELOCITY: float = 1.50    # 1.50 units/sec dynamic imbalance velocity
MIN_IMBALANCE_SWING: float = 0.60       # 0.60 minimum dynamic swing for velocity trigger
MIN_DELTA_T_SEC: float = 0.05           # 0.05s minimum delta t floor
COOLDOWN_SECONDS: float = 45.0          # 45.0s block duration

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_imbalance: Optional[float] = None
_prev_imbalance_ts: Optional[float] = None
_latest_imbalance: float = 0.0
_latest_velocity: float = 0.0
_latest_total_depth: float = 10.0
_blocked_until: float = 0.0


def _is_valid_non_negative(val: Any) -> bool:
    """Validate value is a non-negative finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val >= 0.0


def _is_valid_numeric(val: Any) -> bool:
    """Validate value is a finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return True


def record_imbalance(
    imbalance: float,
    velocity: Optional[float] = None,
    total_depth: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Directly ingest precomputed queue imbalance, velocity, and combined depth.
    """
    global _latest_imbalance, _latest_velocity, _latest_total_depth, _blocked_until

    if not _is_valid_numeric(imbalance):
        return

    imb = max(-1.0, min(1.0, float(imbalance)))
    v = float(velocity) if (velocity is not None and _is_valid_numeric(velocity)) else 0.0
    tot = float(total_depth) if (total_depth is not None and _is_valid_non_negative(total_depth)) else 10.0

    with _lock:
        _latest_imbalance = imb
        _latest_velocity = v
        _latest_total_depth = tot

        # Condition 2: Explosive Imbalance Flow Velocity
        if abs(v) >= MAX_IMBALANCE_VELOCITY:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 1: Severe Directional Queue Imbalance
        if abs(imb) >= MAX_QUEUE_IMBALANCE and tot >= MIN_COMBINED_DEPTH:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_depths(
    bid_depth: float,
    ask_depth: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest bid and ask depths, compute queue imbalance and imbalance velocity.
    """
    global _prev_imbalance, _prev_imbalance_ts
    global _latest_imbalance, _latest_velocity, _latest_total_depth, _blocked_until

    if not (_is_valid_non_negative(bid_depth) and _is_valid_non_negative(ask_depth)):
        return

    bq = float(bid_depth)
    aq = float(ask_depth)
    tot = bq + aq
    now = float(ts) if (ts is not None and _is_valid_numeric(ts)) else time.time()

    with _lock:
        _latest_total_depth = tot

        # Condition 3: Acute Flank Liquidity Blanking
        if (bq <= 0.15 and aq >= 6.0) or (aq <= 0.15 and bq >= 6.0):
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        if tot <= 0.0:
            return

        imb = (bq - aq) / tot
        _latest_imbalance = imb

        # Condition 1: Severe Directional Queue Imbalance
        if abs(imb) >= MAX_QUEUE_IMBALANCE and tot >= MIN_COMBINED_DEPTH:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            _prev_imbalance = imb
            _prev_imbalance_ts = now
            return

        if _prev_imbalance is not None and _prev_imbalance_ts is not None:
            dt = max(MIN_DELTA_T_SEC, now - _prev_imbalance_ts)
            d_imb = imb - _prev_imbalance
            velocity = d_imb / dt
            _latest_velocity = velocity

            # Condition 2: Explosive Imbalance Flow Velocity
            if abs(velocity) >= MAX_IMBALANCE_VELOCITY and abs(d_imb) >= MIN_IMBALANCE_SWING:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                _prev_imbalance = imb
                _prev_imbalance_ts = now
                return

        _prev_imbalance = imb
        _prev_imbalance_ts = now


def update(
    bid_depth: float,
    ask_depth: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """Module alias for record_depths or record_imbalance."""
    if ask_depth is None:
        record_imbalance(bid_depth, ts=ts)
    else:
        record_depths(bid_depth, ask_depth, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if entry is currently blocked by imbalance momentum guard."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked."""
    return is_entry_blocked()


def get_imbalance_metrics() -> Dict[str, Any]:
    """Return dictionary of current queue imbalance and velocity metrics."""
    with _lock:
        return {
            "latest_imbalance": round(_latest_imbalance, 4),
            "latest_velocity": round(_latest_velocity, 4),
            "latest_total_depth": round(_latest_total_depth, 4),
            "max_queue_imbalance": MAX_QUEUE_IMBALANCE,
            "min_combined_depth": MIN_COMBINED_DEPTH,
            "max_imbalance_velocity": MAX_IMBALANCE_VELOCITY,
            "is_blocked": is_entry_blocked(),
        }


def get_status() -> Dict[str, Any]:
    """Return complete status dictionary."""
    with _lock:
        remaining_cd = max(0.0, _blocked_until - time.monotonic())
        metrics = get_imbalance_metrics()
        metrics["cooldown_remaining_sec"] = round(remaining_cd, 2)
        return metrics


def reset() -> None:
    """Reset all state to initial defaults."""
    global _prev_imbalance, _prev_imbalance_ts
    global _latest_imbalance, _latest_velocity, _latest_total_depth, _blocked_until
    with _lock:
        _prev_imbalance = None
        _prev_imbalance_ts = None
        _latest_imbalance = 0.0
        _latest_velocity = 0.0
        _latest_total_depth = 10.0
        _blocked_until = 0.0
