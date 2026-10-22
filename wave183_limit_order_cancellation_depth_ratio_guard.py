"""
wave183_limit_order_cancellation_depth_ratio_guard.py
------------------------------------------------------
Guard: Limit Order Cancellation-to-Depth Ratio (CDR) Guard

Monitors the intensity of limit order cancellations relative to prevailing visible order book
depth over a rolling high-frequency time window:
    CDR = sum(V_cancelled) / D_avg

In orderly double auction trading, limit order placement and cancellations represent balanced
liquidity maintenance (CDR typically <= 0.80).
However, during predatory spoofing routines, flash crashes, or immediate pre-news freezes, large
liquidity providers rapidly cancel multiple price layers across the book (liquidity withdrawal
vacuum). When the cumulative volume of cancelled orders dwarfs visible depth:
    CDR >= MAX_CDR (default: 2.50, or 250% of visible depth cancelled within 10.0s)
the order book becomes dangerously thin and vulnerable to catastrophic gap fills and slippage.

When excessive cancellation-to-depth is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s) until new limit orders restabilize the book depth.

Logic:
- Ingests cancellation events (cancelled_volume, current_depth, ts=None).
- Maintains a sliding time window over WINDOW_SECONDS (10.0s).
- Prunes events older than (current_time - WINDOW_SECONDS).
- Requires at least MIN_CANCELLATIONS = 5 events and baseline depth >= MIN_DEPTH (5.0 lots).
- Computes CDR = sum(V_cancelled) / D_avg.
- If CDR >= MAX_CDR (2.50):
    blocks entries for COOLDOWN_SECONDS (45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive values are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_cancellation(cancelled_vol, depth, ts=None)       -> None
  update(cancelled_vol, depth, ts=None)                    -> None   (alias)
  get_cdr()                                                -> float
  get_status(ts=None)                                      -> dict
  reset()                                                  -> None
"""

import collections
import math
import threading
import time
from typing import Deque, Dict, Optional, Tuple, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_CDR: float = 2.50                 # CDR >= 2.50 (250% depth cancelled) indicates toxic book evaporation
MIN_CANCELLATIONS: int = 5            # Minimum cancellation events in window to qualify
MIN_DEPTH: float = 5.0                # Minimum average depth to evaluate
WINDOW_SECONDS: float = 10.0          # Rolling evaluation time window
COOLDOWN_SECONDS: float = 45.0        # Block duration on excessive cancellation surge


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
# Tuple: (timestamp, cancelled_volume, depth)
_cancellations: Deque[Tuple[float, float, float]] = collections.deque()
_latest_cdr: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _purge_old_events(now: float) -> None:
    """Purge cancellation events outside the rolling time window. Must be called under _lock."""
    cutoff = now - WINDOW_SECONDS
    while _cancellations and _cancellations[0][0] < cutoff:
        _cancellations.popleft()


def record_cancellation(cancelled_volume, current_depth, ts=None) -> None:
    """Record a limit order cancellation event and evaluate Cancellation-to-Depth Ratio."""
    for val in (cancelled_volume, current_depth):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return
        if math.isnan(val) or math.isinf(val) or val <= 0.0:
            return

    c_vol = float(cancelled_volume)
    depth = float(current_depth)

    if ts is not None:
        if isinstance(ts, bool) or not isinstance(ts, (int, float)):
            return
        if math.isnan(ts) or math.isinf(ts) or ts < 0.0:
            return
        current_ts = float(ts)
    else:
        current_ts = time.monotonic()

    global _latest_cdr, _blocked_until
    with _lock:
        _cancellations.append((current_ts, c_vol, depth))
        _purge_old_events(current_ts)

        if len(_cancellations) < MIN_CANCELLATIONS:
            return

        total_cancelled = sum(ev[1] for ev in _cancellations)
        avg_depth = sum(ev[2] for ev in _cancellations) / float(len(_cancellations))

        if avg_depth >= MIN_DEPTH:
            cdr = total_cancelled / avg_depth
            _latest_cdr = cdr

            if cdr >= MAX_CDR:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(cancelled_volume, current_depth, ts=None) -> None:
    """Alias for record_cancellation()."""
    record_cancellation(cancelled_volume, current_depth, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if excessive cancellation ratio has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_cdr() -> float:
    """Return the most recently computed Cancellation-to-Depth Ratio."""
    with _lock:
        return _latest_cdr


def get_status(ts=None) -> Dict[str, Any]:
    """Return a diagnostic snapshot of the cancellation-to-depth guard state."""
    with _lock:
        now = time.monotonic()
        if ts is not None and not isinstance(ts, bool) and isinstance(ts, (int, float)):
            _purge_old_events(float(ts))
        return {
            "cdr": _latest_cdr,
            "cancellation_count": len(_cancellations),
            "min_cancellations_threshold": MIN_CANCELLATIONS,
            "min_depth_threshold": MIN_DEPTH,
            "max_cdr_threshold": MAX_CDR,
            "window_seconds": WINDOW_SECONDS,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset all cancellation event history, CDR metrics, and active blocks."""
    global _latest_cdr, _blocked_until
    with _lock:
        _cancellations.clear()
        _latest_cdr = 0.0
        _blocked_until = 0.0
