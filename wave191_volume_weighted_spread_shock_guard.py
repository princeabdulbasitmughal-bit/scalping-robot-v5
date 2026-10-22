"""
wave191_volume_weighted_spread_shock_guard.py
----------------------------------------------
Guard: Volume-Weighted Spread (VWS) Adverse Selection Shock Guard

Monitors the Volume-Weighted Spread (VWS) across multiple order book depth levels:
    P_ask_vw = sum(P_{A,k} * Q_{A,k}) / sum(Q_{A,k})
    P_bid_vw = sum(P_{B,k} * Q_{B,k}) / sum(Q_{B,k})
    VWS = P_ask_vw - P_bid_vw
    VWS_bps = VWS / Mid
    VWS_Ratio = VWS / max(1e-6, S_top)

In healthy, deep order books, liquidity is robustly layered behind top-of-book quotes.
The volume-weighted depth spread is tightly anchored to the touch spread (VWS_Ratio ~ 1.05 to 1.60).
However, during predatory liquidity vacuums or phantom quoting regimes, market makers display paper-thin
dust size at top-of-book, while the actual book depth is hollowed out multiple pips away:
1. Hard Depth Spread Ceiling: VWS_bps >= MAX_VWS_BPS (default: 6.0 bps / 0.00060)
2. Hollow Book Shock: VWS_Ratio >= MAX_VWS_RATIO (default: 2.50, meaning depth spread is 2.5x wider
   than touch spread, indicating phantom liquidity at Level-1 backed by empty depth).

When an order executes into a hollow book, market orders or aggressive limit fills sweep through
multiple price levels, suffering catastrophic slippage.

When excessive volume-weighted spread or hollow book shock is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s) until solid multi-level depth replenishes.

Logic:
- Ingests multiple book depth levels via record_two_tier_book or record_book_levels.
- Validates strictly against booleans, NaNs, Infs, non-positive prices/sizes, and crossed quotes.
- Computes volume-weighted bid/ask prices, VWS, VWS_bps, and VWS_Ratio.
- If VWS_bps >= MAX_VWS_BPS (0.00060) or VWS_Ratio >= MAX_VWS_RATIO (2.50):
    blocks entries for COOLDOWN_SECONDS (45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: invalid quotes or crossed books (bid > ask) are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_two_tier_book(...)                                -> None
  record_book_levels(bids, asks, ts=None)                  -> None
  update(...)                                              -> None   (alias)
  get_vws_bps()                                            -> float
  get_vws_ratio()                                          -> float
  get_status()                                             -> dict
  reset()                                                  -> None
"""

import math
import threading
import time
from typing import Dict, List, Optional, Tuple, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_VWS_BPS: float = 0.00060          # 6.0 basis points hard volume-weighted spread ceiling
MAX_VWS_RATIO: float = 2.50           # 2.5x touch spread indicates hollow / phantom depth
COOLDOWN_SECONDS: float = 45.0        # Block duration on hollow book shock


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_latest_vws_bps: float = 0.0
_latest_vws_ratio: float = 1.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_book_levels(
    bids: List[Tuple[float, float]],
    asks: List[Tuple[float, float]],
    ts=None,
) -> None:
    """Record multi-tier order book levels and evaluate volume-weighted spread."""
    if not bids or not asks:
        return

    # Validate elements
    clean_bids = []
    for b in bids:
        if not isinstance(b, (tuple, list)) or len(b) < 2:
            return
        p, q = b[0], b[1]
        if isinstance(p, bool) or not isinstance(p, (int, float)) or \
           isinstance(q, bool) or not isinstance(q, (int, float)):
            return
        if math.isnan(p) or math.isinf(p) or p <= 0.0 or \
           math.isnan(q) or math.isinf(q) or q <= 0.0:
            return
        clean_bids.append((float(p), float(q)))

    clean_asks = []
    for a in asks:
        if not isinstance(a, (tuple, list)) or len(a) < 2:
            return
        p, q = a[0], a[1]
        if isinstance(p, bool) or not isinstance(p, (int, float)) or \
           isinstance(q, bool) or not isinstance(q, (int, float)):
            return
        if math.isnan(p) or math.isinf(p) or p <= 0.0 or \
           math.isnan(q) or math.isinf(q) or q <= 0.0:
            return
        clean_asks.append((float(p), float(q)))

    # Best bid and ask
    b1, _ = clean_bids[0]
    a1, _ = clean_asks[0]

    if b1 >= a1:  # Crossed book
        return

    mid = 0.5 * (b1 + a1)
    touch_spread = a1 - b1

    total_b_vol = sum(q for _, q in clean_bids)
    total_a_vol = sum(q for _, q in clean_asks)

    if total_b_vol <= 0.0 or total_a_vol <= 0.0:
        return

    vw_bid = sum(p * q for p, q in clean_bids) / total_b_vol
    vw_ask = sum(p * q for p, q in clean_asks) / total_a_vol

    vws = vw_ask - vw_bid
    if vws <= 0.0:
        return

    vws_bps = vws / mid
    vws_ratio = vws / max(1e-6, touch_spread)

    global _latest_vws_bps, _latest_vws_ratio, _blocked_until
    with _lock:
        _latest_vws_bps = vws_bps
        _latest_vws_ratio = vws_ratio

        if vws_bps >= MAX_VWS_BPS or vws_ratio >= MAX_VWS_RATIO:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def record_two_tier_book(
    bid1, ask1, qb1, qa1,
    bid2, ask2, qb2, qa2,
    ts=None,
) -> None:
    """Record two-tier order book levels convenience helper."""
    record_book_levels(
        bids=[(bid1, qb1), (bid2, qb2)],
        asks=[(ask1, qa1), (ask2, qa2)],
        ts=ts,
    )


def update(*args, **kwargs) -> None:
    """Alias for record_two_tier_book or record_book_levels."""
    if len(args) == 8:
        record_two_tier_book(*args, **kwargs)
    elif len(args) >= 2 and isinstance(args[0], list) and isinstance(args[1], list):
        record_book_levels(args[0], args[1], **kwargs)


def is_entry_blocked() -> bool:
    """Return True if volume-weighted spread shock has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_vws_bps() -> float:
    """Return the most recently computed relative Volume-Weighted Spread in basis points."""
    with _lock:
        return _latest_vws_bps


def get_vws_ratio() -> float:
    """Return the most recently computed ratio of VWS to touch spread."""
    with _lock:
        return _latest_vws_ratio


def get_status() -> Dict[str, Any]:
    """Return a diagnostic snapshot of the volume-weighted spread guard state."""
    with _lock:
        now = time.monotonic()
        return {
            "latest_vws_bps": _latest_vws_bps,
            "latest_vws_ratio": _latest_vws_ratio,
            "max_vws_bps_threshold": MAX_VWS_BPS,
            "max_vws_ratio_threshold": MAX_VWS_RATIO,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset spread metrics, depth tracking, and active blocks."""
    global _latest_vws_bps, _latest_vws_ratio, _blocked_until
    with _lock:
        _latest_vws_bps = 0.0
        _latest_vws_ratio = 1.0
        _blocked_until = 0.0
