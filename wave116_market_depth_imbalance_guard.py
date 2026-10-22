"""
wave116_market_depth_imbalance_guard.py
-----------------------------------------
Guard: Market Depth (Order Book) Imbalance Guard

Monitors top-of-book or Level-2 aggregate bid vs ask volume to detect extreme
order book imbalances that precede large institutional sweeps or liquidity vacuums.

Logic:
- Records bid_volume and ask_volume on order book snapshots.
- Computes imbalance ratio = max(bid_vol, ask_vol) / max(min(bid_vol, ask_vol), 1e-6).
- If imbalance ratio >= MAX_IMBALANCE_RATIO (default: 4.0, representing 4:1 volume skew),
  blocks entries for COOLDOWN_SECONDS (default: 45.0s).
- Fail-closed: invalid, negative, or zero volume ignored (state preserved).
- Thread-safe: threading.RLock() on all shared state.

Aliases (required):
  is_entry_blocked()              -> bool
  is_blocked()                    -> bool   (alias)
  record_depth(bid_vol, ask_vol)  -> None
  update(bid_vol, ask_vol)        -> None   (alias)
  reset()                         -> None
"""

import math
import threading
import time

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_IMBALANCE_RATIO: float = 4.0    # 4:1 volume imbalance threshold
COOLDOWN_SECONDS: float = 45.0      # block duration on extreme book skew


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_depth(bid_vol, ask_vol) -> None:
    """Record bid and ask volume from L2/order book snapshot."""
    if isinstance(bid_vol, bool) or isinstance(ask_vol, bool):
        return
    if not isinstance(bid_vol, (int, float)) or not isinstance(ask_vol, (int, float)):
        return
    if math.isnan(bid_vol) or math.isinf(bid_vol) or bid_vol <= 0.0:
        return
    if math.isnan(ask_vol) or math.isinf(ask_vol) or ask_vol <= 0.0:
        return

    bv = float(bid_vol)
    av = float(ask_vol)

    imbalance = max(bv, av) / max(min(bv, av), 1e-6)

    global _blocked_until
    with _lock:
        if imbalance >= MAX_IMBALANCE_RATIO:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(bid_vol, ask_vol) -> None:
    """Alias for record_depth()."""
    record_depth(bid_vol, ask_vol)


def is_entry_blocked() -> bool:
    """Return True if an order book depth imbalance block is active."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Reset active block."""
    global _blocked_until
    with _lock:
        _blocked_until = 0.0
