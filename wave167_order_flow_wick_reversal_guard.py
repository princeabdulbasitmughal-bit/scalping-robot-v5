"""
wave167_order_flow_wick_reversal_guard.py
-----------------------------------------
Guard: Order Flow Absorption & Pin-Bar Wick Exhaustion Guard

Monitors extreme wick rejection ratios on micro-bars to detect institutional limit order absorption:
    Total Range = High - Low
    Upper Wick = High - max(Open, Close)
    Lower Wick = min(Open, Close) - Low
    Upper Wick Ratio = Upper Wick / Total Range
    Lower Wick Ratio = Lower Wick / Total Range

When an attempted momentum breakout or breakdown is aggressively met with opposing institutional
limit orders, the bar forms an extreme wick (Upper or Lower Wick Ratio >= MAX_WICK_RATIO, default: 0.65).
Entering continuation scalp trades immediately following such aggressive absorption traps retail
traders at the extreme wick tip before an immediate mean-reversion snapback occurs.
When an absorbed pin-bar wick ratio >= 0.65 is detected on significant range (Range >= 0.0010),
trade entries are blocked for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Records micro-bars (open, high, low, close).
- Validates OHLC ordering (high >= max(open, close), low <= min(open, close), low > 0).
- Filters out micro-noise bars below MIN_RANGE (0.0010).
- Computes Upper and Lower Wick ratios.
- If max(Upper_Ratio, Lower_Ratio) >= MAX_WICK_RATIO (0.65):
    blocks entries for COOLDOWN_SECONDS (45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: invalid or corrupted OHLC geometries are ignored.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_bar(open_p, high_p, low_p, close_p, ts=None)      -> None
  update(open_p, high_p, low_p, close_p, ts=None)          -> None   (alias)
  get_wick_ratio()                                         -> float
  reset()                                                  -> None
"""

import math
import threading
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_WICK_RATIO: float = 0.65       # 65% wick-to-range ratio indicates aggressive limit order absorption
MIN_RANGE: float = 0.0010          # 10 bps minimum bar range to filter out tick noise
COOLDOWN_SECONDS: float = 45.0     # Block duration in seconds on wick absorption trap


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_latest_wick_ratio: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_bar(open_p, high_p, low_p, close_p, ts=None) -> None:
    """Record an OHLC micro-bar and evaluate wick rejection absorption ratios."""
    for val in (open_p, high_p, low_p, close_p):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return
        if math.isnan(val) or math.isinf(val):
            return

    o = float(open_p)
    h = float(high_p)
    l = float(low_p)
    c = float(close_p)

    if o <= 0.0 or h <= 0.0 or l <= 0.0 or c <= 0.0:
        return
    if h < l or h < o or h < c or l > o or l > c:
        return

    tot_range = h - l
    if tot_range < MIN_RANGE:
        return

    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    upper_ratio = upper_wick / tot_range
    lower_ratio = lower_wick / tot_range
    max_ratio = max(upper_ratio, lower_ratio)

    global _latest_wick_ratio, _blocked_until
    with _lock:
        _latest_wick_ratio = max_ratio
        if max_ratio >= MAX_WICK_RATIO:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(open_p, high_p, low_p, close_p, ts=None) -> None:
    """Alias for record_bar()."""
    record_bar(open_p, high_p, low_p, close_p, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if wick rejection absorption has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_wick_ratio() -> float:
    """Return the most recently calculated maximum wick ratio."""
    with _lock:
        return _latest_wick_ratio


def reset() -> None:
    """Reset wick ratio and active cooldown."""
    global _latest_wick_ratio, _blocked_until
    with _lock:
        _latest_wick_ratio = 0.0
        _blocked_until = 0.0
