"""
wave177_queue_depletion_velocity_guard.py
------------------------------------------
Guard: Level-1 Order Queue Depletion Velocity & Phantom Liquidity Pull Guard

Monitors top-of-book (Level-1) order queue depth changes over high-frequency time intervals.

In healthy continuous double auction markets, order queues are replenished as market makers and
resting limit orders absorb liquidity.
However, during predatory spoofing routines or preceding flash crashes, toxic liquidity providers
rapidly cancel their large resting quotes (phantom liquidity pulls). When the top-of-book queue
evaporates without corresponding executed volume, a severe liquidity vacuum forms:
    Drop_bid = (Q_bid^{t-1} - Q_bid^t) / Q_bid^{t-1}
    Drop_ask = (Q_ask^{t-1} - Q_ask^t) / Q_ask^{t-1}

If either queue depth drops by >= MIN_DEPTH_DROP_PCT (default: 75% or 0.75) within a sub-second
window (dt <= MAX_DEPLETION_WINDOW_SEC, default: 0.50s) from a baseline depth of at least
MIN_INITIAL_DEPTH (default: 5.0 lots), an acute liquidity withdrawal is taking place.
Scalpers submitting market or aggressive limit orders during this vacuum face massive slippage and
gaps through multiple book levels.

When a rapid queue depletion event occurs, the guard blocks entry orders immediately for
COOLDOWN_SECONDS (default: 45.0s) until the book replenishes.

Logic:
- Ingests top-of-book depths (bid_depth, ask_depth) with optional high-precision timestamp (ts).
- Validates strictly against booleans, NaNs, Infs, and negative values.
- Evaluates queue depletion drop percentage over high-frequency intervals dt <= 0.50s.
- Ignores trivial drops on thin dust queues (initial depth < 5.0 lots).
- If Drop_bid >= 0.75 or Drop_ask >= 0.75 within dt <= 0.50s:
    blocks entries for COOLDOWN_SECONDS (45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: invalid depth or timestamp inputs are safely rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_depth(bid_depth, ask_depth, ts=None)              -> None
  update(bid_depth, ask_depth, ts=None)                    -> None   (alias)
  get_latest_drop_pct()                                    -> float
  get_status()                                             -> dict
  reset()                                                  -> None
"""

import math
import threading
import time
from typing import Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MIN_DEPTH_DROP_PCT: float = 0.75      # 75% drop in queue depth constitutes a liquidity vacuum
MAX_DEPLETION_WINDOW_SEC: float = 0.50 # Window duration for high-frequency evaporation
MIN_INITIAL_DEPTH: float = 5.0        # Minimum baseline queue depth to qualify
COOLDOWN_SECONDS: float = 45.0        # Block duration on phantom liquidity pull


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_bid_depth: Optional[float] = None
_prev_ask_depth: Optional[float] = None
_prev_ts: Optional[float] = None
_latest_drop_pct: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_depth(bid_depth, ask_depth, ts=None) -> None:
    """Record Level-1 queue depths and detect rapid phantom liquidity depletion."""
    for val in (bid_depth, ask_depth):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return
        if math.isnan(val) or math.isinf(val) or val < 0.0:
            return

    b_depth = float(bid_depth)
    a_depth = float(ask_depth)

    # Resolve timestamp
    if ts is not None:
        if isinstance(ts, bool) or not isinstance(ts, (int, float)):
            return
        if math.isnan(ts) or math.isinf(ts) or ts < 0.0:
            return
        current_ts = float(ts)
    else:
        current_ts = time.monotonic()

    global _prev_bid_depth, _prev_ask_depth, _prev_ts, _latest_drop_pct, _blocked_until
    with _lock:
        if _prev_ts is not None and _prev_bid_depth is not None and _prev_ask_depth is not None:
            dt = current_ts - _prev_ts

            if 0.0 < dt <= MAX_DEPLETION_WINDOW_SEC:
                triggered = False

                # Check bid queue depletion
                if _prev_bid_depth >= MIN_INITIAL_DEPTH:
                    bid_drop = (_prev_bid_depth - b_depth) / _prev_bid_depth
                    if bid_drop >= MIN_DEPTH_DROP_PCT:
                        _latest_drop_pct = bid_drop
                        triggered = True

                # Check ask queue depletion
                if not triggered and _prev_ask_depth >= MIN_INITIAL_DEPTH:
                    ask_drop = (_prev_ask_depth - a_depth) / _prev_ask_depth
                    if ask_drop >= MIN_DEPTH_DROP_PCT:
                        _latest_drop_pct = ask_drop
                        triggered = True

                if triggered:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS

        _prev_bid_depth = b_depth
        _prev_ask_depth = a_depth
        _prev_ts = current_ts


def update(bid_depth, ask_depth, ts=None) -> None:
    """Alias for record_depth()."""
    record_depth(bid_depth, ask_depth, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if phantom liquidity pull or queue collapse has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_latest_drop_pct() -> float:
    """Return the most recently measured fractional queue depletion drop."""
    with _lock:
        return _latest_drop_pct


def get_status() -> Dict[str, Any]:
    """Return a diagnostic snapshot of the queue depletion guard state."""
    with _lock:
        now = time.monotonic()
        return {
            "prev_bid_depth": _prev_bid_depth,
            "prev_ask_depth": _prev_ask_depth,
            "latest_drop_pct": _latest_drop_pct,
            "min_depth_drop_pct_threshold": MIN_DEPTH_DROP_PCT,
            "max_depletion_window_sec": MAX_DEPLETION_WINDOW_SEC,
            "min_initial_depth": MIN_INITIAL_DEPTH,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset all queue tracking, depletion metrics, and active blocks."""
    global _prev_bid_depth, _prev_ask_depth, _prev_ts, _latest_drop_pct, _blocked_until
    with _lock:
        _prev_bid_depth = None
        _prev_ask_depth = None
        _prev_ts = None
        _latest_drop_pct = 0.0
        _blocked_until = 0.0
