"""
wave244_lob_depth_imbalance_acceleration_guard.py
---------------------------------------------------
Guard: Level 2 Depth Imbalance Acceleration & Flank Exhaustion Guard

Monitors second-derivative acceleration in limit order book cumulative depth imbalance
and acute flank depletion (Biais, Hillion & Spatt 1995; Cao, Chen & Griffin 2005):
    Depth Imbalance:         I_{depth} = (Q_{bid} - Q_{ask}) / max(0.01, Q_{bid} + Q_{ask}) \\in [-1.0, +1.0]
    Imbalance Velocity:      v_{imb, t} = I_{depth, t} - I_{depth, t-1}
    Imbalance Acceleration:  a_{imb, t} = v_{imb, t} - v_{imb, t-1}

In balanced, healthy two-sided order books:
    - Depths on both sides are comparable:
      |I_{depth}| <= 0.30, with smooth adjustments |a_{imb}| < 0.25.

During aggressive predatory book leaning, queue evaporation, or sudden flank exhaustion:
    - Liquidity rapidly vanishes from one side while piling into the other:
        1) Severe Imbalance Acceleration:
           |a_{imb}| >= MAX_ACCELERATION (default: 0.60 units) AND
           |I_{depth}| >= MIN_IMBALANCE_THRESHOLD (default: 0.70).
        2) Flank Exhaustion Collapse:
           min(Q_{bid}, Q_{ask}) <= MIN_FLANK_DEPTH (default: 0.50 lots) AND
           max(Q_{bid}, Q_{ask}) >= DOMINANT_FLANK_DEPTH (default: 8.00 lots).
        3) Extreme Static Imbalance:
           |I_{depth}| >= MAX_STATIC_IMBALANCE (default: 0.90) with total depth >= 5.0 lots.

Entering market or limit orders into an accelerating imbalance or collapsed flank guarantees
immediate execution through air pockets, severe slippage, and adverse fill selection.

When imbalance acceleration surge or flank exhaustion is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests depths via record_depths(bid_depth_lots, ask_depth_lots, ts=None) or
  direct imbalance via record_imbalance(imbalance, ts=None).
- Tracks rolling imbalance, velocity, and acceleration.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative depths are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_depths(bid_depth_lots, ask_depth_lots, ts=None)                                       -> None
  record_imbalance(imbalance, total_depth=None, ts=None)                                       -> None
  update(bid_depth_lots, ask_depth_lots=None, ts=None)                                         -> None   (alias)
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
MAX_ACCELERATION: float = 0.60         # 0.60 units second-derivative acceleration
MIN_IMBALANCE_THRESHOLD: float = 0.70  # 0.70 imbalance magnitude for acceleration block
MIN_FLANK_DEPTH: float = 0.50          # 0.50 lots flank exhaustion floor
DOMINANT_FLANK_DEPTH: float = 8.00     # 8.00 lots opposing dominant depth
MAX_STATIC_IMBALANCE: float = 0.90     # 0.90 static imbalance ceiling
MIN_TOTAL_DEPTH: float = 5.00          # 5.00 lots total depth for static ceiling
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_latest_bid_depth: float = 5.0
_latest_ask_depth: float = 5.0
_latest_imbalance: float = 0.0
_prev_imbalance: float = 0.0
_prev_velocity: float = 0.0
_latest_velocity: float = 0.0
_latest_acceleration: float = 0.0
_blocked_until: float = 0.0


def _is_valid_non_negative(val: Any) -> bool:
    """Validate value is a non-negative finite numeric float or int."""
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
    total_depth: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Directly ingest depth imbalance ratio [-1.0, +1.0] and evaluate acceleration.
    """
    global _latest_imbalance, _prev_imbalance, _prev_velocity, _latest_velocity
    global _latest_acceleration, _blocked_until

    if not _is_valid_numeric(imbalance):
        return

    imb = max(-1.0, min(1.0, float(imbalance)))

    with _lock:
        v_imb = imb - _latest_imbalance
        a_imb = v_imb - _latest_velocity

        _prev_imbalance = _latest_imbalance
        _prev_velocity = _latest_velocity
        _latest_imbalance = imb
        _latest_velocity = v_imb
        _latest_acceleration = a_imb

        # Condition 1: Severe imbalance acceleration
        if abs(a_imb) >= MAX_ACCELERATION and abs(imb) >= MIN_IMBALANCE_THRESHOLD:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 2: Extreme static imbalance with sufficient depth
        tot = float(total_depth) if (total_depth is not None and _is_valid_non_negative(total_depth)) else 10.0
        if abs(imb) >= MAX_STATIC_IMBALANCE and tot >= MIN_TOTAL_DEPTH:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_depths(
    bid_depth_lots: float,
    ask_depth_lots: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest bid and ask cumulative depths and evaluate imbalance, acceleration, and flank exhaustion.
    """
    global _latest_bid_depth, _latest_ask_depth, _blocked_until

    if not _is_valid_non_negative(bid_depth_lots) or not _is_valid_non_negative(ask_depth_lots):
        return

    b_depth = float(bid_depth_lots)
    a_depth = float(ask_depth_lots)
    tot = b_depth + a_depth

    with _lock:
        _latest_bid_depth = b_depth
        _latest_ask_depth = a_depth

        # Condition: Flank exhaustion collapse
        min_flank = min(b_depth, a_depth)
        max_flank = max(b_depth, a_depth)
        if min_flank <= MIN_FLANK_DEPTH and max_flank >= DOMINANT_FLANK_DEPTH:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

    imb = (b_depth - a_depth) / max(0.01, tot)
    record_imbalance(imb, total_depth=tot, ts=ts)


def update(
    bid_depth_lots: float,
    ask_depth_lots: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Flexible alias:
    If ask_depth_lots is provided, computes imbalance from bid and ask depths.
    If ask_depth_lots is None, treats bid_depth_lots as direct imbalance ratio.
    """
    if ask_depth_lots is not None:
        record_depths(bid_depth_lots, ask_depth_lots, ts)
    else:
        record_imbalance(bid_depth_lots, ts=ts)


def is_entry_blocked() -> bool:
    """Check if new entries are blocked by depth imbalance acceleration or flank exhaustion."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_imbalance_metrics() -> Dict[str, float]:
    """Retrieve current depth imbalance metrics."""
    with _lock:
        return {
            "bid_depth": _latest_bid_depth,
            "ask_depth": _latest_ask_depth,
            "depth_imbalance": _latest_imbalance,
            "imbalance_velocity": _latest_velocity,
            "imbalance_acceleration": _latest_acceleration,
        }


def get_status() -> Dict[str, Any]:
    """Retrieve complete guard status."""
    with _lock:
        now = time.monotonic()
        blocked = now < _blocked_until
        remaining = max(0.0, _blocked_until - now) if blocked else 0.0
        return {
            "guard_name": "wave244_lob_depth_imbalance_acceleration_guard",
            "is_blocked": blocked,
            "blocked_seconds_remaining": remaining,
            "bid_depth": _latest_bid_depth,
            "ask_depth": _latest_ask_depth,
            "depth_imbalance": _latest_imbalance,
            "imbalance_velocity": _latest_velocity,
            "imbalance_acceleration": _latest_acceleration,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "max_acceleration": MAX_ACCELERATION,
            "min_imbalance_threshold": MIN_IMBALANCE_THRESHOLD,
            "min_flank_depth": MIN_FLANK_DEPTH,
            "dominant_flank_depth": DOMINANT_FLANK_DEPTH,
            "max_static_imbalance": MAX_STATIC_IMBALANCE,
        }


def reset() -> None:
    """Reset all guard state and clear cooldowns."""
    global _latest_bid_depth, _latest_ask_depth, _latest_imbalance
    global _prev_imbalance, _prev_velocity, _latest_velocity, _latest_acceleration, _blocked_until

    with _lock:
        _latest_bid_depth = 5.0
        _latest_ask_depth = 5.0
        _latest_imbalance = 0.0
        _prev_imbalance = 0.0
        _prev_velocity = 0.0
        _latest_velocity = 0.0
        _latest_acceleration = 0.0
        _blocked_until = 0.0
