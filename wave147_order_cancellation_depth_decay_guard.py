"""
wave147_order_cancellation_depth_decay_guard.py
-----------------------------------------------
Guard: Order Book Ghost Liquidity & Flash Cancellation Decay Guard

Detects spoofing and ghost liquidity pulls on Level-2 order books.
Deceptive algorithmic participants flash large depth commitments to create
a false illusion of support/resistance, only to flash-cancel that depth milliseconds
prior to execution.

Logic:
- Tracks total near-book depth: V = bid_vol + ask_vol.
- Evaluates depth changes across consecutive sub-second snapshots (dt <= 0.50s):
    depth_drop = V_prev - V_curr
    canceled_vol = max(0.0, depth_drop - executed_vol)
    cancel_ratio = canceled_vol / V_prev
- If cancel_ratio >= MAX_CANCEL_RATIO (default: 0.70) and V_prev >= MIN_PREV_DEPTH (5.0 lots):
    blocks entries for COOLDOWN_SECONDS (default: 60.0s) to prevent filling against
    hollowed-out ghost order books.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Fail-closed: non-numeric, boolean, NaN, Inf, and negative values ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()                                         -> bool
  is_blocked()                                               -> bool   (alias)
  record_depth(bid_vol, ask_vol, executed_vol=0, ts=None)    -> None
  update(bid_vol, ask_vol, executed_vol=0, ts=None)          -> None   (alias)
  get_cancellation_decay_ratio()                             -> float
  reset()                                                    -> None
"""

import math
import threading
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_CANCEL_RATIO: float = 0.70         # 70% unexecuted depth pull triggers block
MIN_PREV_DEPTH: float = 5.0            # minimum initial depth required to evaluate ratio
MAX_DELTA_TIME: float = 0.50           # sub-second flash cancellation window
COOLDOWN_SECONDS: float = 60.0         # duration of protective block on ghost liquidity


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_depth: Optional[float] = None
_prev_time: Optional[float] = None
_last_cancel_ratio: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_depth(bid_vol, ask_vol, executed_vol=0.0, ts=None) -> None:
    """Record depth snapshot, subtract executed volume, and evaluate ghost cancellation."""
    for val in (bid_vol, ask_vol, executed_vol):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return
        if math.isnan(val) or math.isinf(val) or val < 0.0:
            return

    bv = float(bid_vol)
    av = float(ask_vol)
    ev = float(executed_vol)
    curr_depth = bv + av
    if curr_depth <= 0.0:
        return

    now = float(ts) if (ts is not None and isinstance(ts, (int, float)) and not isinstance(ts, bool)) else time.monotonic()

    global _prev_depth, _prev_time, _last_cancel_ratio, _blocked_until
    with _lock:
        if _prev_depth is not None and _prev_time is not None:
            dt = now - _prev_time
            if dt <= MAX_DELTA_TIME and _prev_depth >= MIN_PREV_DEPTH:
                depth_drop = _prev_depth - curr_depth
                canceled_vol = max(0.0, depth_drop - ev)
                cancel_ratio = canceled_vol / _prev_depth

                _last_cancel_ratio = cancel_ratio

                if cancel_ratio >= MAX_CANCEL_RATIO:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS

        _prev_depth = curr_depth
        _prev_time = now


def update(bid_vol, ask_vol, executed_vol=0.0, ts=None) -> None:
    """Alias for record_depth()."""
    record_depth(bid_vol, ask_vol, executed_vol=executed_vol, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if ghost liquidity flash cancellation has triggered protection."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_cancellation_decay_ratio() -> float:
    """Return the most recently computed cancellation decay ratio."""
    with _lock:
        return _last_cancel_ratio


def reset() -> None:
    """Reset depth references, cancellation metrics, and active block."""
    global _prev_depth, _prev_time, _last_cancel_ratio, _blocked_until
    with _lock:
        _prev_depth = None
        _prev_time = None
        _last_cancel_ratio = 0.0
        _blocked_until = 0.0
