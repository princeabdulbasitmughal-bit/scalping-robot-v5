"""
wave214_order_flow_imbalance_volume_weighted_spread_guard.py
-------------------------------------------------------------
Guard: Volume-Weighted Spread & Depth Liquidity Wedge Guard

Monitors top-of-book volume-weighted price displacement and standing depth liquidity wedges
(Bessembinder 2003; Hasbrouck 2007):
    Midquote:       P_{mid} = (Bid + Ask) / 2
    VW Price:       P_{vw} = (Bid * Q_{bid} + Ask * Q_{ask}) / max(1e-6, Q_{bid} + Q_{ask})
    Spread Wedge:   W_{spread} = |P_{vw} - P_{mid}| / P_{mid} * 10,000 (bps)
    Depth Ratio:    R_{depth} = max(Q_{bid}, Q_{ask}) / max(0.1, min(Q_{bid}, Q_{ask}))

In balanced, healthy limit order books with symmetric liquidity provision:
    - Spread wedge: W_{spread} < 1.0 bp
    - Depth ratio:  R_{depth} < 5.0

During predatory book conditions—such as sudden one-sided depth evaporation, toxic asymmetric quote
stuffing, or hidden liquidity gaps—the volume-weighted center of the book diverges sharply from the posted midquote:
    1) Severe volume-weighted spread wedge:
       W_{spread} >= MAX_WEDGE_SPREAD_BPS (default: 2.5 bps)
    2) Extreme depth asymmetry ratio:
       R_{depth} >= MAX_DEPTH_RATIO (default: 15.0x, meaning one side has evaporated to < 1/15th of the other).

Submitting market or limit scalping orders into these severe liquidity wedges results in instant
predatory slippage and execution adverse selection.

When a volume-weighted spread wedge is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests top-of-book state (bid_price > 0.0, bid_depth >= 0.0, ask_price > bid_price, ask_depth >= 0.0, ts=None).
- Computes midquote, volume-weighted price P_{vw}, spread wedge W_{spread}, and depth ratio R_{depth}.
- Blocks entries for COOLDOWN_SECONDS (45.0s) if W_{spread} >= 2.5 bps or R_{depth} >= 15.0.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, negative depths, or inverted prices are rejected.

Aliases (required):
  is_entry_blocked()                                                             -> bool
  is_blocked()                                                                   -> bool   (alias)
  record_book(bid_price, bid_depth, ask_price, ask_depth, ts=None)               -> None
  update(bid_price, bid_depth, ask_price, ask_depth, ts=None)                    -> None   (alias)
  get_wedge_metrics()                                                            -> dict
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
MAX_WEDGE_SPREAD_BPS: float = 2.5      # 2.5 bps volume-weighted center displacement
MAX_DEPTH_RATIO: float = 15.0          # 15.0x depth asymmetry ratio
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_latest_wedge_bps: float = 0.0
_latest_depth_ratio: float = 1.0
_latest_vw_price: float = 0.0
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
    Ingest a new top-of-book state and calculate volume-weighted spread wedge metrics.
    """
    global _latest_wedge_bps, _latest_depth_ratio, _latest_vw_price, _blocked_until

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

    tot_q = bq + aq
    if tot_q <= 1e-9:
        return

    with _lock:
        now = time.monotonic() if ts is None else float(ts)

        mid = (bp + ap) / 2.0
        p_vw = (bp * bq + ap * aq) / tot_q
        wedge_bps = (abs(p_vw - mid) / mid) * 10_000.0

        min_q = max(0.1, min(bq, aq))
        max_q = max(bq, aq)
        depth_ratio = max_q / min_q

        _latest_wedge_bps = wedge_bps
        _latest_depth_ratio = depth_ratio
        _latest_vw_price = p_vw

        # Condition 1: Volume-weighted spread wedge dislocation
        if wedge_bps >= MAX_WEDGE_SPREAD_BPS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 2: Monopolistic depth asymmetry
        if depth_ratio >= MAX_DEPTH_RATIO and max_q >= 10.0:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


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
    """Check if entry orders are currently blocked due to volume-weighted spread wedge."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_wedge_metrics() -> Dict[str, float]:
    """Return latest calculated spread wedge and depth ratio."""
    with _lock:
        return {
            "spread_wedge_bps": _latest_wedge_bps,
            "depth_ratio": _latest_depth_ratio,
            "vw_price": _latest_vw_price,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the volume-weighted spread guard."""
    with _lock:
        now = time.monotonic()
        return {
            "spread_wedge_bps": _latest_wedge_bps,
            "depth_ratio": _latest_depth_ratio,
            "vw_price": _latest_vw_price,
            "max_wedge_threshold": MAX_WEDGE_SPREAD_BPS,
            "max_depth_ratio_threshold": MAX_DEPTH_RATIO,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset book trackers, wedge metrics, and active cooldown blocks."""
    global _latest_wedge_bps, _latest_depth_ratio, _latest_vw_price, _blocked_until
    with _lock:
        _latest_wedge_bps = 0.0
        _latest_depth_ratio = 1.0
        _latest_vw_price = 0.0
        _blocked_until = 0.0
