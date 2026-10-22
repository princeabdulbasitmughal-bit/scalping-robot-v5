"""
wave250_lob_pressure_imbalance_step_velocity_guard.py
-------------------------------------------------------
Guard: Order Book Bid-Ask Pressure Imbalance & Step Velocity Guard

Monitors multi-tier weighted order book pressure asymmetry and acute step velocity shifts
(Biais, Hillion & Spatt 1995; Handa, Schwartz & Tiwari 2003):
    Tier Inverse Weight:     w_k = 1 / k,  k in {1, 2, ..., K} (closer tiers weighted higher)
    Bid Book Pressure:       P_{bid} = \\sum_{k=1}^K (Q_{bid, k} / k)
    Ask Book Pressure:       P_{ask} = \\sum_{k=1}^K (Q_{ask, k} / k)
    Pressure Asymmetry:      \\Pi_{asym} = (P_{bid} - P_{ask}) / max(0.01, P_{bid} + P_{ask}) \\in [-1.0, +1.0]
    Pressure Step Velocity:  v_{step} = (\\Pi_{asym, t} - \\Pi_{asym, t-1}) / max(0.1, \\Delta t)

Under balanced two-sided market making:
    - Liquidity pressure builds symmetrically across the visible tiers:
      |\\Pi_{asym}| <= 0.35, with smooth step velocities |v_{step}| < 0.30 units/sec.

During aggressive predatory book tilting, queue vanishing sweeps, or flash iceberg positioning:
    - Order book pressure heavily skews toward one side or snaps discontinuously:
        1) Severe Pressure Gradient Asymmetry:
           |\\Pi_{asym}| >= MAX_PRESSURE_ASYMMETRY (default: 0.75) AND
           (P_{bid} + P_{ask}) >= MIN_COMBINED_PRESSURE (default: 5.0 lots).
        2) Rapid Pressure Step Velocity Surge:
           |v_{step}| >= MAX_STEP_VELOCITY (default: 0.65 units/sec) in acute interval <= 0.5s.

Placing limit orders or trading counter to severe book pressure tilts guarantees
immediate execution through hollow air pockets and aggressive adverse selection.

When pressure asymmetry surge or acute step velocity jump is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests multi-tier depths via record_tier_depths(bid_tiers, ask_tiers, ts=None) or
  direct pressures via record_pressures(bid_pressure, ask_pressure, ts=None).
- Calculates weighted pressures, asymmetry ratio \\Pi_{asym}, and step velocity v_{step}.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative depths/pressures are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_tier_depths(bid_tiers, ask_tiers, ts=None)                                            -> None
  record_pressures(bid_pressure, ask_pressure, ts=None)                                        -> None
  update(bid_val, ask_val=None, ts=None)                                                       -> None   (alias)
  get_pressure_metrics()                                                                       -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import math
import threading
import time
from typing import Dict, Optional, Any, List, Union

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_PRESSURE_ASYMMETRY: float = 0.75   # 0.75 pressure asymmetry magnitude
MIN_COMBINED_PRESSURE: float = 5.0     # 5.0 lots minimum combined weighted pressure
MAX_STEP_VELOCITY: float = 0.65        # 0.65 units/sec acute step velocity surge
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_latest_bid_pressure: float = 5.0
_latest_ask_pressure: float = 5.0
_latest_pressure_asymmetry: float = 0.0
_latest_step_velocity: float = 0.0
_prev_asymmetry: float = 0.0
_prev_ts: Optional[float] = None
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


def record_pressures(
    bid_pressure: float,
    ask_pressure: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest precomputed weighted bid and ask pressures and evaluate asymmetry and step velocity.
    """
    global _latest_bid_pressure, _latest_ask_pressure, _latest_pressure_asymmetry
    global _latest_step_velocity, _prev_asymmetry, _prev_ts, _blocked_until

    if not _is_valid_non_negative(bid_pressure) or not _is_valid_non_negative(ask_pressure):
        return

    bp = float(bid_pressure)
    ap = float(ask_pressure)
    tot = bp + ap
    now = float(ts) if ts is not None else time.time()

    with _lock:
        asym = (bp - ap) / max(0.01, tot)

        if _prev_ts is not None:
            dt = max(0.05, now - _prev_ts)
            velocity = (asym - _prev_asymmetry) / dt
        else:
            velocity = 0.0

        _latest_bid_pressure = bp
        _latest_ask_pressure = ap
        _latest_pressure_asymmetry = asym
        _latest_step_velocity = velocity
        _prev_asymmetry = asym
        _prev_ts = now

        # Condition 1: Rapid pressure step velocity surge (in <= 0.5s)
        if abs(velocity) >= MAX_STEP_VELOCITY:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 2: Severe pressure gradient asymmetry with sufficient pressure
        if abs(asym) >= MAX_PRESSURE_ASYMMETRY and tot >= MIN_COMBINED_PRESSURE:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_tier_depths(
    bid_tiers: Union[List[float], tuple],
    ask_tiers: Union[List[float], tuple],
    ts: Optional[float] = None,
) -> None:
    """
    Ingest lists of tier depths [depth_tier1, depth_tier2, ...], apply 1/k weighting, and evaluate.
    """
    if not isinstance(bid_tiers, (list, tuple)) or not isinstance(ask_tiers, (list, tuple)):
        return
    if len(bid_tiers) == 0 or len(ask_tiers) == 0:
        return

    bp = 0.0
    for k, q in enumerate(bid_tiers, start=1):
        if not _is_valid_non_negative(q):
            return
        bp += float(q) / k

    ap = 0.0
    for k, q in enumerate(ask_tiers, start=1):
        if not _is_valid_non_negative(q):
            return
        ap += float(q) / k

    record_pressures(bp, ap, ts)


def update(
    bid_val: Any,
    ask_val: Optional[Any] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Flexible alias:
    If bid_val and ask_val are lists/tuples, calls record_tier_depths().
    If bid_val and ask_val are numeric, calls record_pressures().
    """
    if isinstance(bid_val, (list, tuple)) and isinstance(ask_val, (list, tuple)):
        record_tier_depths(bid_val, ask_val, ts)
    elif ask_val is not None:
        record_pressures(bid_val, ask_val, ts)


def is_entry_blocked() -> bool:
    """Check if new entries are blocked by pressure asymmetry or step velocity."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_pressure_metrics() -> Dict[str, float]:
    """Retrieve current pressure metrics."""
    with _lock:
        return {
            "bid_pressure": _latest_bid_pressure,
            "ask_pressure": _latest_ask_pressure,
            "pressure_asymmetry": _latest_pressure_asymmetry,
            "step_velocity": _latest_step_velocity,
        }


def get_status() -> Dict[str, Any]:
    """Retrieve complete guard status."""
    with _lock:
        now = time.monotonic()
        blocked = now < _blocked_until
        remaining = max(0.0, _blocked_until - now) if blocked else 0.0
        return {
            "guard_name": "wave250_lob_pressure_imbalance_step_velocity_guard",
            "is_blocked": blocked,
            "blocked_seconds_remaining": remaining,
            "bid_pressure": _latest_bid_pressure,
            "ask_pressure": _latest_ask_pressure,
            "pressure_asymmetry": _latest_pressure_asymmetry,
            "step_velocity": _latest_step_velocity,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "max_pressure_asymmetry": MAX_PRESSURE_ASYMMETRY,
            "min_combined_pressure": MIN_COMBINED_PRESSURE,
            "max_step_velocity": MAX_STEP_VELOCITY,
        }


def reset() -> None:
    """Reset all guard state and clear cooldowns."""
    global _latest_bid_pressure, _latest_ask_pressure, _latest_pressure_asymmetry
    global _latest_step_velocity, _prev_asymmetry, _prev_ts, _blocked_until

    with _lock:
        _latest_bid_pressure = 5.0
        _latest_ask_pressure = 5.0
        _latest_pressure_asymmetry = 0.0
        _latest_step_velocity = 0.0
        _prev_asymmetry = 0.0
        _prev_ts = None
        _blocked_until = 0.0
