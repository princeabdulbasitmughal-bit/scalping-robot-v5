"""
wave200_quote_fade_velocity_guard.py
-------------------------------------
Guard: Order Book Quote Fading Velocity Guard

Monitors the velocity with which market makers withdraw liquidity and revise top-of-book quotes
away from aggressive order flow (Biais, Hillion, Spatt 1995; Hasbrouck 2007):
    v_{fade, ask} = [(Ask_t - Ask_{t - dt}) / Ask_{t - dt}] / dt * 10,000   (bps/second)
    v_{fade, bid} = [(Bid_{t - dt} - Bid_t) / Bid_{t - dt}] / dt * 10,000   (bps/second)
where dt <= 0.50 seconds.

In orderly, competitive market-making conditions, quotes remain stationary or adjust smoothly:
    v_{fade} < 10.0 bps/second.

During toxic order flow events, informed front-running, or market maker flight, liquidity providers
cancel resting depth and fade their quotes at extreme speed:
    1) Severe ask quote fading:
       v_{fade, ask} >= MAX_FADE_VELOCITY (default: 20.0 bps/sec) with delta >= MIN_FADE_MOVE_BPS (1.5 bps).
    2) Severe bid quote fading:
       v_{fade, bid} >= MAX_FADE_VELOCITY (default: 20.0 bps/sec) with delta >= MIN_FADE_MOVE_BPS (1.5 bps).

Scalpers attempting to enter or exit positions while quotes are rapidly fading experience catastrophic
adverse selection, severe queue jumping, and execution slippage past the vanished quotes.

When excessive quote fade velocity is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests top-of-book quotes (bid > 0.0, ask > bid, ts=None).
- Calculates elapsed time dt from previous quote.
- If 0.0 < dt <= 0.50s, calculates instantaneous quote fade velocities for bid and ask.
- Evaluates if either velocity breaches MAX_FADE_VELOCITY (20.0 bps/sec).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive bids/asks, or inverted quotes are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_quote(bid, ask, ts=None)                          -> None
  update(bid, ask, ts=None)                                -> None   (alias)
  get_fade_metrics()                                       -> dict
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
MAX_FADE_VELOCITY: float = 20.0        # 20.0 bps/second quote fade speed
MIN_FADE_MOVE_BPS: float = 1.5         # 1.5 bps minimum quote displacement
MAX_EVAL_DT: float = 0.50              # maximum time interval (seconds) for velocity calculation
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_bid: Optional[float] = None
_prev_ask: Optional[float] = None
_prev_ts: Optional[float] = None
_latest_bid_velocity: float = 0.0
_latest_ask_velocity: float = 0.0
_blocked_until: float = 0.0


def _is_valid_price(val: Any) -> bool:
    """Validate price is a positive finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val > 0.0


def record_quote(bid: float, ask: float, ts: Optional[float] = None) -> None:
    """
    Ingest a new quote update and calculate quote fade velocities.
    """
    global _prev_bid, _prev_ask, _prev_ts
    global _latest_bid_velocity, _latest_ask_velocity, _blocked_until

    if not _is_valid_price(bid) or not _is_valid_price(ask):
        return
    if float(ask) <= float(bid):
        return

    b = float(bid)
    a = float(ask)

    with _lock:
        now = time.monotonic() if ts is None else float(ts)

        if _prev_bid is None or _prev_ask is None or _prev_ts is None:
            _prev_bid = b
            _prev_ask = a
            _prev_ts = now
            return

        dt = now - _prev_ts
        if 0.0 < dt <= MAX_EVAL_DT:
            # Ask fading upward: (a - prev_a) / prev_a
            ask_move_bps = ((a - _prev_ask) / _prev_ask) * 10_000.0
            ask_vel = (ask_move_bps / dt) if ask_move_bps > 0.0 else 0.0
            _latest_ask_velocity = ask_vel

            # Bid fading downward: (prev_b - b) / prev_b
            bid_move_bps = ((_prev_bid - b) / _prev_bid) * 10_000.0
            bid_vel = (bid_move_bps / dt) if bid_move_bps > 0.0 else 0.0
            _latest_bid_velocity = bid_vel

            # Check Condition 1: Ask quote fade velocity breach
            if ask_vel >= MAX_FADE_VELOCITY and ask_move_bps >= MIN_FADE_MOVE_BPS:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                _prev_bid = b
                _prev_ask = a
                _prev_ts = now
                return

            # Check Condition 2: Bid quote fade velocity breach
            if bid_vel >= MAX_FADE_VELOCITY and bid_move_bps >= MIN_FADE_MOVE_BPS:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                _prev_bid = b
                _prev_ask = a
                _prev_ts = now
                return

        _prev_bid = b
        _prev_ask = a
        _prev_ts = now


def update(bid: float, ask: float, ts: Optional[float] = None) -> None:
    """Alias for record_quote()."""
    record_quote(bid, ask, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to quote fade velocity."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_fade_metrics() -> Dict[str, float]:
    """Return latest calculated bid and ask quote fade velocities."""
    with _lock:
        return {
            "bid_fade_velocity_bps_sec": _latest_bid_velocity,
            "ask_fade_velocity_bps_sec": _latest_ask_velocity,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the quote fade velocity guard."""
    with _lock:
        now = time.monotonic()
        return {
            "bid_fade_velocity_bps_sec": _latest_bid_velocity,
            "ask_fade_velocity_bps_sec": _latest_ask_velocity,
            "max_velocity_threshold": MAX_FADE_VELOCITY,
            "min_fade_move_bps": MIN_FADE_MOVE_BPS,
            "max_eval_dt": MAX_EVAL_DT,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset quote history, fade metrics, and active cooldown blocks."""
    global _prev_bid, _prev_ask, _prev_ts
    global _latest_bid_velocity, _latest_ask_velocity, _blocked_until
    with _lock:
        _prev_bid = None
        _prev_ask = None
        _prev_ts = None
        _latest_bid_velocity = 0.0
        _latest_ask_velocity = 0.0
        _blocked_until = 0.0
