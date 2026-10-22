"""
wave202_limit_order_book_depth_replenishment_latency_guard.py
--------------------------------------------------------------
Guard: Limit Order Book Queue Depth Replenishment Latency Guard

Monitors the precise clock latency required for standing queue depth to be reconstituted
following an aggressive liquidity consumption shock (Hautsch & Huang 2012):
    Depletion:  Q_shock <= (1 - DEPLETION_DROP_PCT) * Q_pre
    Recovery:   Q_t >= REPLENISH_TARGET_PCT * Q_pre

In deep, resilient double-auction books supported by active market making, resting depth is
restocked almost instantaneously following a sweep:
    tau_{replenish} < 0.50 seconds.

During market maker quoting withdrawals or toxic order flow events, standing depth remains depleted:
    1) Excessive replenishment latency:
       tau_{replenish} >= MAX_REPLENISH_LATENCY (default: 1.5s)
    2) Failure to replenish before window expiry:
       EVAL_WINDOW_SEC (2.0s) elapses while queue depth remains unreplenished (< 80% restored).

Entering limit or marketable scalping positions while depth replenishment is paralyzed exposes the
system to extreme cascading slippage and predatory sweep fills.

When replenishment latency exceeds safety limits, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests top-of-book depths (bid_depth, ask_depth, ts=None).
- Detects queue drops >= 50% from baseline depth >= MIN_PRE_DEPTH (10.0 lots).
- Starts a replenishment clock (t_shock).
- Evaluates whether depth is restored to >= 80% of pre-shock depth within MAX_REPLENISH_LATENCY (1.5s).
- Blocks entries for COOLDOWN_SECONDS (45.0s) if replenishment is delayed or window expires.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative depth inputs are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_depth(bid_depth, ask_depth, ts=None)              -> None
  update(bid_depth, ask_depth, ts=None)                    -> None   (alias)
  get_replenish_latency()                                  -> float
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
MIN_PRE_DEPTH: float = 10.0            # 10.0 lots minimum baseline depth
DEPLETION_DROP_PCT: float = 0.50       # 50% drop initiates depletion tracking
REPLENISH_TARGET_PCT: float = 0.80     # 80% of pre-shock depth required for recovery
MAX_REPLENISH_LATENCY: float = 1.5     # maximum acceptable replenishment latency (seconds)
EVAL_WINDOW_SEC: float = 2.0           # 2.0s maximum evaluation window
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_bid_depth: Optional[float] = None
_prev_ask_depth: Optional[float] = None
_prev_ts: Optional[float] = None
_active_depletion: Optional[Dict[str, Any]] = None
_latest_replenish_latency: float = 0.0
_blocked_until: float = 0.0


def _is_valid_depth(val: Any) -> bool:
    """Validate depth is a non-negative finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val >= 0.0


def record_depth(bid_depth: float, ask_depth: float, ts: Optional[float] = None) -> None:
    """
    Ingest a new depth update and monitor queue replenishment latency.
    """
    global _prev_bid_depth, _prev_ask_depth, _prev_ts, _active_depletion
    global _latest_replenish_latency, _blocked_until

    if not _is_valid_depth(bid_depth) or not _is_valid_depth(ask_depth):
        return

    bd = float(bid_depth)
    ad = float(ask_depth)

    with _lock:
        now = time.monotonic() if ts is None else float(ts)

        if _prev_bid_depth is None or _prev_ask_depth is None or _prev_ts is None:
            _prev_bid_depth = bd
            _prev_ask_depth = ad
            _prev_ts = now
            return

        # Check existing active depletion
        if _active_depletion is not None:
            side = _active_depletion["side"]
            pre_depth = _active_depletion["pre_depth"]
            t_shock = _active_depletion["t_shock"]
            deadline = _active_depletion["deadline"]

            curr_depth = bd if side == "bid" else ad
            elapsed = now - t_shock

            # Check if replenished
            if curr_depth >= REPLENISH_TARGET_PCT * pre_depth:
                _latest_replenish_latency = elapsed
                if elapsed >= MAX_REPLENISH_LATENCY:
                    # Took too long to replenish
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                _active_depletion = None
            elif now >= deadline:
                # Window expired without recovery
                _latest_replenish_latency = elapsed
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                _active_depletion = None

        # Check for new depletion shock
        dt = now - _prev_ts
        if _active_depletion is None and 0.0 < dt <= 0.50:
            # Bid depletion
            if _prev_bid_depth >= MIN_PRE_DEPTH and bd <= (1.0 - DEPLETION_DROP_PCT) * _prev_bid_depth:
                _active_depletion = {
                    "side": "bid",
                    "pre_depth": _prev_bid_depth,
                    "t_shock": now,
                    "deadline": now + EVAL_WINDOW_SEC,
                }
                _latest_replenish_latency = 0.0
            # Ask depletion
            elif _prev_ask_depth >= MIN_PRE_DEPTH and ad <= (1.0 - DEPLETION_DROP_PCT) * _prev_ask_depth:
                _active_depletion = {
                    "side": "ask",
                    "pre_depth": _prev_ask_depth,
                    "t_shock": now,
                    "deadline": now + EVAL_WINDOW_SEC,
                }
                _latest_replenish_latency = 0.0

        _prev_bid_depth = bd
        _prev_ask_depth = ad
        _prev_ts = now


def update(bid_depth: float, ask_depth: float, ts: Optional[float] = None) -> None:
    """Alias for record_depth()."""
    record_depth(bid_depth, ask_depth, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to replenishment latency."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_replenish_latency() -> float:
    """Return latest measured queue depth replenishment latency in seconds."""
    with _lock:
        return _latest_replenish_latency


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the replenishment latency guard."""
    with _lock:
        now = time.monotonic()
        return {
            "replenish_latency_sec": _latest_replenish_latency,
            "has_active_depletion": _active_depletion is not None,
            "max_latency_threshold": MAX_REPLENISH_LATENCY,
            "replenish_target_pct": REPLENISH_TARGET_PCT,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset depth history, active depletion state, and cooldown blocks."""
    global _prev_bid_depth, _prev_ask_depth, _prev_ts, _active_depletion
    global _latest_replenish_latency, _blocked_until
    with _lock:
        _prev_bid_depth = None
        _prev_ask_depth = None
        _prev_ts = None
        _active_depletion = None
        _latest_replenish_latency = 0.0
        _blocked_until = 0.0
