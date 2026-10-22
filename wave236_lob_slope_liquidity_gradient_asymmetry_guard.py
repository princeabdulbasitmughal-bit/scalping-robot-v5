"""
wave236_lob_slope_liquidity_gradient_asymmetry_guard.py
---------------------------------------------------------
Guard: Order Book Slope & Liquidity Gradient Asymmetry Guard

Monitors limit order book depth slope / accumulation gradient as a function of price distance
from the touch (Biais, Hillion & Spatt 1995; Daníelsson & Payne 2012):
    Bid Depth Slope:       beta_{bid} = Delta Q_{bid} / Delta P_{bid} (lots / bp)
    Ask Depth Slope:       beta_{ask} = Delta Q_{ask} / Delta P_{ask} (lots / bp)
    Slope Asymmetry Ratio: R_{slope} = max(beta_{bid}, beta_{ask}) / max(0.1, min(beta_{bid}, beta_{ask}))

In balanced, healthy limit order book provision:
    - Liquidity accumulates symmetrically on both sides of the book:
      beta_{bid} ~ beta_{ask} >= 2.0 lots/bp, with R_{slope} < 3.0x.

During asymmetric book skew, structural order book tilting, or pre-breakout depletion:
    - One side presents dense standing barriers while the other side is flat and hollow:
        1) Severe Slope Asymmetry:
           R_{slope} >= MAX_SLOPE_ASYMMETRY (default: 8.0x) AND
           max(beta_{bid}, beta_{ask}) >= DOMINANT_SLOPE_THRESHOLD (default: 5.0 lots/bp) AND
           min(beta_{bid}, beta_{ask}) <= LAGGING_SLOPE_THRESHOLD (default: 0.5 lots/bp).
        2) Bilateral Shallow Air Pocket:
           Both beta_{bid} <= SHALLOW_SLOPE_THRESHOLD (default: 0.20 lots/bp) AND
           beta_{ask} <= SHALLOW_SLOPE_THRESHOLD (0.20 lots/bp).

Posting limit orders or attempting to fade into an asymmetric book slope guarantees
immediate price slippage in the direction of the hollow gradient.

When severe slope asymmetry or bilateral shallow air pocket is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests slopes via record_book_slopes(bid_slope_lots_per_bp, ask_slope_lots_per_bp, ts=None)
  or record_book_tiers(bid_depth_touch, bid_depth_outer, bid_spread_bps, ask_depth_touch, ask_depth_outer, ask_spread_bps, ts=None).
- Evaluates R_{slope} and shallow thresholds.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative slopes are rejected.

Aliases (required):
  is_entry_blocked()                                                                   -> bool
  is_blocked()                                                                         -> bool   (alias)
  record_book_slopes(bid_slope, ask_slope, ts=None)                                    -> None
  record_book_tiers(b_touch, b_outer, b_bps, a_touch, a_outer, a_bps, ts=None)          -> None
  update(bid_slope, ask_slope, ts=None)                                                -> None   (alias)
  get_slope_metrics()                                                                  -> dict
  get_status()                                                                         -> dict
  reset()                                                                              -> None
"""

import math
import threading
import time
from typing import Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_SLOPE_ASYMMETRY: float = 8.0          # 8.0x slope asymmetry ratio
DOMINANT_SLOPE_THRESHOLD: float = 5.0     # 5.0 lots/bp dominant slope threshold
LAGGING_SLOPE_THRESHOLD: float = 0.50     # 0.50 lots/bp lagging slope threshold
SHALLOW_SLOPE_THRESHOLD: float = 0.20     # 0.20 lots/bp bilateral shallow air pocket
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_latest_bid_slope: float = 2.0
_latest_ask_slope: float = 2.0
_latest_slope_asymmetry: float = 1.0
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


def record_book_slopes(
    bid_slope_lots_per_bp: float,
    ask_slope_lots_per_bp: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest bid and ask liquidity slopes and evaluate asymmetry.
    """
    global _latest_bid_slope, _latest_ask_slope, _latest_slope_asymmetry, _blocked_until

    if not _is_valid_non_negative(bid_slope_lots_per_bp) or not _is_valid_non_negative(ask_slope_lots_per_bp):
        return

    b_slope = float(bid_slope_lots_per_bp)
    a_slope = float(ask_slope_lots_per_bp)

    with _lock:
        dom_slope = max(b_slope, a_slope)
        lag_slope = min(b_slope, a_slope)
        asym = dom_slope / max(0.1, lag_slope)

        _latest_bid_slope = b_slope
        _latest_ask_slope = a_slope
        _latest_slope_asymmetry = asym

        # Condition 1: Severe slope asymmetry
        if (
            asym >= MAX_SLOPE_ASYMMETRY
            and dom_slope >= DOMINANT_SLOPE_THRESHOLD
            and lag_slope <= LAGGING_SLOPE_THRESHOLD
        ):
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 2: Bilateral shallow air pocket
        if b_slope <= SHALLOW_SLOPE_THRESHOLD and a_slope <= SHALLOW_SLOPE_THRESHOLD:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_book_tiers(
    bid_depth_touch: float,
    bid_depth_outer: float,
    bid_spread_bps: float,
    ask_depth_touch: float,
    ask_depth_outer: float,
    ask_spread_bps: float,
    ts: Optional[float] = None,
) -> None:
    """
    Compute slopes from two-tier order book depths and spreads.
    """
    if not _is_valid_non_negative(bid_depth_touch) or not _is_valid_non_negative(bid_depth_outer):
        return
    if not _is_valid_non_negative(ask_depth_touch) or not _is_valid_non_negative(ask_depth_outer):
        return
    if not _is_valid_non_negative(bid_spread_bps) or not _is_valid_non_negative(ask_spread_bps):
        return

    b_slope = max(0.0, bid_depth_outer - bid_depth_touch) / max(0.1, float(bid_spread_bps))
    a_slope = max(0.0, ask_depth_outer - ask_depth_touch) / max(0.1, float(ask_spread_bps))

    record_book_slopes(b_slope, a_slope, ts)


def update(
    bid_slope: float,
    ask_slope: float,
    ts: Optional[float] = None,
) -> None:
    """Alias for record_book_slopes()."""
    record_book_slopes(bid_slope, ask_slope, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to book slope asymmetry."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_slope_metrics() -> Dict[str, float]:
    """Return latest calculated bid slope, ask slope, and asymmetry ratio."""
    with _lock:
        return {
            "bid_slope": _latest_bid_slope,
            "ask_slope": _latest_ask_slope,
            "slope_asymmetry": _latest_slope_asymmetry,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the book slope guard."""
    with _lock:
        now = time.monotonic()
        return {
            "bid_slope": _latest_bid_slope,
            "ask_slope": _latest_ask_slope,
            "slope_asymmetry": _latest_slope_asymmetry,
            "max_slope_asymmetry": MAX_SLOPE_ASYMMETRY,
            "dominant_slope_threshold": DOMINANT_SLOPE_THRESHOLD,
            "lagging_slope_threshold": LAGGING_SLOPE_THRESHOLD,
            "shallow_slope_threshold": SHALLOW_SLOPE_THRESHOLD,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset slope trackers, metrics, and active cooldown blocks."""
    global _latest_bid_slope, _latest_ask_slope, _latest_slope_asymmetry, _blocked_until
    with _lock:
        _latest_bid_slope = 2.0
        _latest_ask_slope = 2.0
        _latest_slope_asymmetry = 1.0
        _blocked_until = 0.0
