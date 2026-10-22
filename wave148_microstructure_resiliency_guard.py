"""
wave148_microstructure_resiliency_guard.py
------------------------------------------
Guard: Order Book Depth Resiliency & Replenishment Latency Guard

Monitors order book resiliency / liquidity replenishment speed following
large market order volume consumption.
In healthy resilient markets, after depth is depleted by a market order, limit orders
replenish the book within 1-2 seconds. If depth remains drained beyond the
replenishment deadline (MAX_RECOVERY_TIME_SEC), it indicates liquidity providers have
withdrawn and refused to quote, leaving the venue fragile and exposed to execution slippage.

Logic:
- Evaluates total near-book depth: V_t = bid_vol + ask_vol.
- Tracks rolling baseline depth V_baseline across quiet intervals.
- When a depth shock occurs (V_t < SHOCK_RATIO * V_baseline, default: 0.40):
    Starts a replenishment countdown timer.
- If elapsed time since shock >= MAX_RECOVERY_TIME_SEC (default: 2.0s) and
  depth is still < RECOVERY_RATIO * V_baseline (default: 0.50):
    resiliency failure triggered!
    blocks entries for COOLDOWN_SECONDS (default: 60.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Fail-closed: non-numeric, boolean, NaN, Inf, and non-positive inputs ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()                   -> bool
  is_blocked()                         -> bool   (alias)
  record_depth(bid_vol, ask_vol, ts)   -> None
  update(bid_vol, ask_vol, ts)         -> None   (alias)
  get_resiliency_ratio()               -> float
  reset()                              -> None
"""

import math
import threading
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SHOCK_RATIO: float = 0.40              # depth dropping below 40% of baseline triggers shock
RECOVERY_RATIO: float = 0.50           # failure to recover 50% of baseline constitutes failure
MAX_RECOVERY_TIME_SEC: float = 2.0     # maximum permissible recovery latency
COOLDOWN_SECONDS: float = 60.0         # duration of protective block on resiliency failure
MIN_BASELINE_DEPTH: float = 5.0        # minimum baseline depth in lots


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_baseline_depth: float = 10.0
_shock_timestamp: Optional[float] = None
_last_resiliency_ratio: float = 1.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_depth(bid_vol, ask_vol, ts=None) -> None:
    """Record depth and evaluate liquidity replenishment resiliency."""
    for val in (bid_vol, ask_vol):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return
        if math.isnan(val) or math.isinf(val) or val < 0.0:
            return

    bv = float(bid_vol)
    av = float(ask_vol)
    curr_depth = bv + av
    if curr_depth <= 0.0:
        return

    now = float(ts) if (ts is not None and isinstance(ts, (int, float)) and not isinstance(ts, bool)) else time.monotonic()

    global _baseline_depth, _shock_timestamp, _last_resiliency_ratio, _blocked_until
    with _lock:
        ratio = curr_depth / max(1e-9, _baseline_depth)
        _last_resiliency_ratio = ratio

        if _shock_timestamp is None:
            if curr_depth >= _baseline_depth:
                _baseline_depth = curr_depth  # expand baseline
            elif ratio < SHOCK_RATIO and _baseline_depth >= MIN_BASELINE_DEPTH:
                _shock_timestamp = now
        else:
            # Under active shock evaluation
            if ratio >= RECOVERY_RATIO:
                # Successfully replenished within window
                _shock_timestamp = None
            else:
                elapsed = now - _shock_timestamp
                if elapsed >= MAX_RECOVERY_TIME_SEC:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                    _shock_timestamp = None  # reset shock after triggering block


def update(bid_vol, ask_vol, ts=None) -> None:
    """Alias for record_depth()."""
    record_depth(bid_vol, ask_vol, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if resiliency failure has triggered an entry block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_resiliency_ratio() -> float:
    """Return current depth relative to baseline."""
    with _lock:
        return _last_resiliency_ratio


def reset() -> None:
    """Reset depth baselines, shock timers, and active block."""
    global _baseline_depth, _shock_timestamp, _last_resiliency_ratio, _blocked_until
    with _lock:
        _baseline_depth = 10.0
        _shock_timestamp = None
        _last_resiliency_ratio = 1.0
        _blocked_until = 0.0
