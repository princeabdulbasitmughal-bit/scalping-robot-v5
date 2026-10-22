"""
wave142_order_book_slope_guard.py
---------------------------------
Guard: Level-2 Order Book Liquidity Slope & Depth Elasticity Guard

Monitors the order book liquidity gradient / slope:
    Slope = Spread / Near_Book_Depth = (P_ask - P_bid) / (V_bid + V_ask)
In deep, resilient liquid markets, tight spreads and thick depth yield flat slopes.
When liquidity evaporates or large market orders hollow out depth, the slope
steepens sharply, signifying that any incremental trade will suffer severe market
impact and execution slippage.

Logic:
- Validates bid and ask quotes and depth volumes (requires ask > bid > 0, vol > 0).
- Computes instantaneous order book slope:
    slope = (ask_price - bid_price) / (bid_vol + ask_vol)
- If slope >= MAX_BOOK_SLOPE (default: 0.0010):
    blocks entries for COOLDOWN_SECONDS (default: 45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Fail-closed: crossed markets (ask <= bid), boolean, NaN, Inf, and non-positive values ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()                                         -> bool
  is_blocked()                                               -> bool   (alias)
  record_depth(bid_price, ask_price, bid_vol, ask_vol, ts)   -> None
  update(bid_price, ask_price, bid_vol, ask_vol, ts)         -> None   (alias)
  get_current_slope()                                        -> float
  reset()                                                    -> None
"""

import math
import threading
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_BOOK_SLOPE: float = 0.0010         # steep slope threshold triggering block (0.0010 price/lot)
COOLDOWN_SECONDS: float = 45.0         # duration of protective block on hollow book


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_last_slope: float = 0.00005           # default to flat resilient book
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_depth(bid_price, ask_price, bid_vol, ask_vol, ts=None) -> None:
    """Record quote prices and depth volumes, evaluate order book slope."""
    for val in (bid_price, ask_price, bid_vol, ask_vol):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return
        if math.isnan(val) or math.isinf(val) or val <= 0.0:
            return

    bp = float(bid_price)
    ap = float(ask_price)
    bv = float(bid_vol)
    av = float(ask_vol)

    if ap <= bp:
        return

    spread = ap - bp
    depth = bv + av

    global _last_slope, _blocked_until
    with _lock:
        if depth > 1e-9:
            slope = spread / depth
        else:
            slope = 1.0

        _last_slope = slope

        if slope >= MAX_BOOK_SLOPE:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(bid_price, ask_price, bid_vol, ask_vol, ts=None) -> None:
    """Alias for record_depth()."""
    record_depth(bid_price, ask_price, bid_vol, ask_vol, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if steep order book slope has activated an entry block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_current_slope() -> float:
    """Return the most recently computed order book slope."""
    with _lock:
        return _last_slope


def reset() -> None:
    """Reset slope tracking and active block."""
    global _last_slope, _blocked_until
    with _lock:
        _last_slope = 0.00005
        _blocked_until = 0.0
