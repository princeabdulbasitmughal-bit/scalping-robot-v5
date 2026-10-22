"""
wave151_effective_spread_adverse_selection_guard.py
----------------------------------------------------
Guard: Roll / Hasbrouck Effective Spread Adverse Selection Guard

Monitors execution price slippage relative to prevailing bid/ask quotes:
    P_mid = (bid + ask) / 2.0
    Quoted Spread = ask - bid
    Effective Spread = 2.0 * |trade_price - P_mid|
    Spread Ratio = Effective Spread / Quoted Spread

Under normal liquid conditions, fills execute at touch (Ratio = 1.0) or with price
improvement within the quote (Ratio < 1.0).
When trades systematically execute outside the quote (Ratio >= MAX_SPREAD_RATIO, default: 2.0),
it indicates severe adverse selection, walking book liquidity exhaustion, or toxic fill routing,
which destroys scalping expectancy.

Logic:
- Records execution price and prevailing top-of-book (bid, ask).
- Validates quote validity (ask > bid > 0, trade_price > 0).
- Computes effective spread and ratio to quoted spread.
- Maintains rolling window (WINDOW_SIZE = 5) of spread ratios.
- If current ratio >= MAX_SPREAD_RATIO (2.0) OR rolling average ratio >= MAX_SPREAD_RATIO (2.0):
    blocks entry for COOLDOWN_SECONDS (default: 45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Fail-closed: non-numeric, boolean, NaN, Inf, or crossed/inverted quotes are rejected.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_execution(trade_price, bid, ask, ts=None)         -> None
  update(trade_price, bid, ask, ts=None)                   -> None   (alias)
  get_effective_spread_ratio()                             -> float
  reset()                                                  -> None
"""

import collections
import math
import threading
import time
from typing import Deque, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_SPREAD_RATIO: float = 2.0      # Effective spread >= 2.0x quoted spread indicates adverse selection
WINDOW_SIZE: int = 5               # Rolling window of recent trade executions
COOLDOWN_SECONDS: float = 45.0     # Block duration in seconds on adverse selection shock


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_history: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_latest_ratio: float = 1.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_execution(trade_price, bid, ask, ts=None) -> None:
    """Record a trade execution against prevailing bid/ask and check adverse selection."""
    for val in (trade_price, bid, ask):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return
        if math.isnan(val) or math.isinf(val):
            return

    tp = float(trade_price)
    b = float(bid)
    a = float(ask)

    # Validate logical quote ordering and non-negative values
    if b <= 0.0 or a <= 0.0 or tp <= 0.0 or a <= b:
        return

    mid = (b + a) / 2.0
    quoted_spread = a - b
    if quoted_spread <= 1e-9:
        return

    effective_spread = 2.0 * abs(tp - mid)
    ratio = effective_spread / quoted_spread

    global _latest_ratio, _blocked_until
    with _lock:
        _latest_ratio = ratio
        _history.append(ratio)

        avg_ratio = sum(_history) / len(_history)
        if ratio >= MAX_SPREAD_RATIO or avg_ratio >= MAX_SPREAD_RATIO:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(trade_price, bid, ask, ts=None) -> None:
    """Alias for record_execution()."""
    record_execution(trade_price, bid, ask, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if adverse selection effective spread has triggered a cooldown block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_effective_spread_ratio() -> float:
    """Return the most recent effective-to-quoted spread ratio."""
    with _lock:
        return _latest_ratio


def reset() -> None:
    """Reset execution history, latest ratio, and active block."""
    global _latest_ratio, _blocked_until
    with _lock:
        _history.clear()
        _latest_ratio = 1.0
        _blocked_until = 0.0
