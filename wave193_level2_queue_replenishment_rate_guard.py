"""
wave193_level2_queue_replenishment_rate_guard.py
-------------------------------------------------
Guard: Level-2 Order Queue Replenishment Rate & Absorption Deficit Guard

Monitors the speed and completeness with which consumed order book queue depth is replenished by
resting market makers following an execution drop:
    Replenish_Ratio = (Q_current - Q_drop) / max(1e-6, Q_pre - Q_drop)

In resilient, liquid double auction books, when aggressive market orders sweep through standing depth,
liquidity providers restock limit orders almost instantaneously (Replenish_Ratio >= 0.70 within 200ms).
However, during toxic order flow sweeps or market maker quote withdrawals, consumed liquidity is NOT
replenished:
    Replenish_Ratio < MIN_REPLENISH_RATIO (default: 0.30, or < 30% restored after 0.50s)

This replenishment deficit indicates that market makers have vacated the book and are refusing to
provide liquidity. The order book is left exposed to violent cascading slippage and price runaway.

When a liquidity replenishment deficit is detected following a queue depletion shock, entry orders
are blocked for COOLDOWN_SECONDS (default: 45.0s) until resting limit depth recovers.

Logic:
- Ingests top-of-book depths (bid_depth, ask_depth, ts=None).
- Detects significant queue drops (drop >= 50% from baseline depth >= MIN_PRE_DEPTH = 10.0 lots).
- Initiates an evaluation window (EVAL_WINDOW_SEC = 0.50s).
- Tracks whether consumed queue depth is restored to at least MIN_REPLENISH_RATIO (0.30).
- If the evaluation window expires and Replenish_Ratio < 0.30:
    blocks entries for COOLDOWN_SECONDS (45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative depths are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_depth(bid_depth, ask_depth, ts=None)              -> None
  update(bid_depth, ask_depth, ts=None)                    -> None   (alias)
  get_replenish_ratio()                                    -> float
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
EVAL_WINDOW_SEC: float = 0.50         # 500 ms window to evaluate queue replenishment
MIN_DEPLETION_DROP_PCT: float = 0.50  # 50% drop qualifies as major queue absorption
MIN_PRE_DEPTH: float = 10.0           # Minimum pre-drop baseline depth to qualify
MIN_REPLENISH_RATIO: float = 0.30     # Less than 30% replenished constitutes absorption deficit
COOLDOWN_SECONDS: float = 45.0        # Block duration on replenishment deficit


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_b_depth: Optional[float] = None
_prev_a_depth: Optional[float] = None
_prev_ts: Optional[float] = None
_active_depletion: Optional[Dict[str, Any]] = None
_latest_replenish_ratio: float = 1.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_depth(bid_depth, ask_depth, ts=None) -> None:
    """Record Level-1 queue depths and evaluate post-drop liquidity replenishment."""
    for val in (bid_depth, ask_depth):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return
        if math.isnan(val) or math.isinf(val) or val < 0.0:
            return

    qb = float(bid_depth)
    qa = float(ask_depth)

    if ts is not None:
        if isinstance(ts, bool) or not isinstance(ts, (int, float)):
            return
        if math.isnan(ts) or math.isinf(ts) or ts < 0.0:
            return
        current_ts = float(ts)
    else:
        current_ts = time.monotonic()

    global _prev_b_depth, _prev_a_depth, _prev_ts, _active_depletion, _latest_replenish_ratio, _blocked_until
    with _lock:
        # Check active monitored depletion
        if _active_depletion is not None:
            side = _active_depletion["side"]
            curr_q = qb if side == "bid" else qa
            pre_q = _active_depletion["pre_q"]
            drop_q = _active_depletion["drop_q"]
            deadline = _active_depletion["deadline"]

            needed = pre_q - drop_q
            restored = curr_q - drop_q
            ratio = max(0.0, restored / needed) if needed > 0.0 else 1.0
            _latest_replenish_ratio = ratio

            if current_ts >= deadline:
                # Window expired: evaluate replenishment
                if ratio < MIN_REPLENISH_RATIO:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                _active_depletion = None
            elif ratio >= 0.80:
                # Fully replenished early
                _active_depletion = None

        # Detect new depletion shocks if no active depletion is being timed
        if _active_depletion is None and _prev_b_depth is not None and _prev_a_depth is not None and _prev_ts is not None:
            dt = current_ts - _prev_ts
            if 0.0 < dt <= 0.50:
                # Bid drop check
                if _prev_b_depth >= MIN_PRE_DEPTH and qb <= (1.0 - MIN_DEPLETION_DROP_PCT) * _prev_b_depth:
                    _active_depletion = {
                        "side": "bid",
                        "pre_q": _prev_b_depth,
                        "drop_q": qb,
                        "t_drop": current_ts,
                        "deadline": current_ts + EVAL_WINDOW_SEC,
                    }
                    _latest_replenish_ratio = 0.0
                # Ask drop check
                elif _prev_a_depth >= MIN_PRE_DEPTH and qa <= (1.0 - MIN_DEPLETION_DROP_PCT) * _prev_a_depth:
                    _active_depletion = {
                        "side": "ask",
                        "pre_q": _prev_a_depth,
                        "drop_q": qa,
                        "t_drop": current_ts,
                        "deadline": current_ts + EVAL_WINDOW_SEC,
                    }
                    _latest_replenish_ratio = 0.0

        _prev_b_depth = qb
        _prev_a_depth = qa
        _prev_ts = current_ts


def update(bid_depth, ask_depth, ts=None) -> None:
    """Alias for record_depth()."""
    record_depth(bid_depth, ask_depth, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if liquidity replenishment deficit has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_replenish_ratio() -> float:
    """Return the most recently measured queue replenishment ratio."""
    with _lock:
        return _latest_replenish_ratio


def get_status() -> Dict[str, Any]:
    """Return a diagnostic snapshot of the queue replenishment guard state."""
    with _lock:
        now = time.monotonic()
        return {
            "latest_replenish_ratio": _latest_replenish_ratio,
            "has_active_depletion": _active_depletion is not None,
            "min_replenish_ratio_threshold": MIN_REPLENISH_RATIO,
            "eval_window_sec": EVAL_WINDOW_SEC,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset queue depth history, active depletion tracking, and active blocks."""
    global _prev_b_depth, _prev_a_depth, _prev_ts, _active_depletion, _latest_replenish_ratio, _blocked_until
    with _lock:
        _prev_b_depth = None
        _prev_a_depth = None
        _prev_ts = None
        _active_depletion = None
        _latest_replenish_ratio = 1.0
        _blocked_until = 0.0
