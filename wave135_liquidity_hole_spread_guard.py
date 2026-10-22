"""
wave135_liquidity_hole_spread_guard.py
---------------------------------------
Guard: Order Book Liquidity Hole & Flash Spread Widening Guard

Monitors instantaneous bid-ask spread expansion against the rolling median spread.
A sudden blowout in the bid-ask spread signals that market makers have pulled
liquidity, creating an order book "liquidity hole" vulnerable to severe slippage.

Logic:
- Validates bid and ask quotes (requires ask > bid > 0, numeric, non-NaN/Inf).
- Computes instantaneous spread:
    spread = ask - bid
- Stores spread in rolling buffer of WINDOW_SIZE (default: 30 quotes).
- When buffer contains at least MIN_QUOTES (default: 15):
    median_spread = median(buffer)
    spread_ratio = current_spread / median_spread
- If spread_ratio >= MAX_SPREAD_MULTIPLIER (default: 3.5x) OR
  current_spread >= ABSOLUTE_MAX_SPREAD (default: 0.0050):
    blocks entries for COOLDOWN_SECONDS (default: 45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Fail-closed: crossed markets (ask <= bid), boolean, NaN, and negative values ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()                           -> bool
  is_blocked()                                 -> bool   (alias)
  record_quote(bid, ask, ts=None)              -> None
  update(bid, ask, ts=None)                    -> None   (alias)
  get_current_spread_ratio()                   -> float
  reset()                                      -> None
"""

import collections
import math
import threading
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 30                  # rolling quotes buffer size
MIN_QUOTES: int = 15                   # minimum observations to establish median spread
MAX_SPREAD_MULTIPLIER: float = 3.5     # multiplier over median spread triggering block
ABSOLUTE_MAX_SPREAD: float = 0.0050    # absolute ceiling on spread (50 pips in FX)
COOLDOWN_SECONDS: float = 45.0         # duration of protective block on liquidity hole


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_spreads = collections.deque(maxlen=WINDOW_SIZE)
_blocked_until: float = 0.0
_last_ratio: float = 1.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_quote(bid, ask, ts=None) -> None:
    """Record top-of-book bid and ask and evaluate spread ratio vs median."""
    for p in (bid, ask):
        if isinstance(p, bool) or not isinstance(p, (int, float)):
            return
        if math.isnan(p) or math.isinf(p) or p <= 0.0:
            return

    b = float(bid)
    a = float(ask)

    # Reject crossed or locked book
    if a <= b:
        return

    spread = a - b

    global _blocked_until, _last_ratio
    with _lock:
        _spreads.append(spread)

        if len(_spreads) >= MIN_QUOTES:
            sorted_s = sorted(_spreads)
            median_s = sorted_s[len(sorted_s) // 2]

            if median_s > 1e-9:
                ratio = spread / median_s
            else:
                ratio = 1.0

            _last_ratio = ratio

            if ratio >= MAX_SPREAD_MULTIPLIER or spread >= ABSOLUTE_MAX_SPREAD:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(bid, ask, ts=None) -> None:
    """Alias for record_quote()."""
    record_quote(bid, ask, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if liquidity hole spread blowout has triggered protection."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_current_spread_ratio() -> float:
    """Return the most recently computed spread multiplier ratio."""
    with _lock:
        return _last_ratio


def reset() -> None:
    """Reset spread history, ratio metrics, and active block."""
    global _blocked_until, _last_ratio
    with _lock:
        _spreads.clear()
        _blocked_until = 0.0
        _last_ratio = 1.0
