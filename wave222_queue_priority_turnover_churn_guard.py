"""
wave222_queue_priority_turnover_churn_guard.py
------------------------------------------------
Guard: LOB Queue Priority Turnover & Order Book Churn Guard

Monitors rapid queue position degradation, excessive limit order book turnover, and queue
evaporation (Moallemi & Saglam 2013; Huang & Polak 2011):
    Turnover Ratio:        R_{turnover} = (V_{added} + V_{cancelled}) / max(0.1, Q_{standing}) in rolling 3.0s
    Queue Drain Velocity:  v_{drain} = V_{cancelled} / max(0.1, dt) (lots/sec)

In stable, orderly limit order book trading:
    - Queue position is predictable; standing orders rest quietly at the touch.
    - Queue turnover ratio R_{turnover} < 1.5x per 3 seconds.

During predatory front-running, queue-jumping algorithms, or quote manipulation:
    - Bots continuously cancel and re-insert orders ahead of the queue, or pull standing depth
      instantly when aggressive order flow arrives:
        1) Excessive Queue Turnover:
           R_{turnover} >= MAX_TURNOVER_RATIO (default: 4.0x turnover in <= 3.0s) AND
           Q_{standing} >= MIN_STANDING_DEPTH (default: 10.0 lots).
        2) Toxic Queue Evaporation / Drain:
           v_{drain} >= MAX_DRAIN_VELOCITY (default: 8.0 lots/sec without matching trades).

Scalpers attempting to post passive orders into hyper-churned queues face severe adverse
selection: they will only be filled when the price level is about to be completely overrun.

When excessive queue turnover or toxic drain velocity is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests queue updates via record_queue_update(standing_depth, added_vol=0.0, cancelled_vol=0.0, ts=None).
- Maintains rolling event history within WINDOW_SECONDS = 3.0s.
- Computes turnover ratio R_{turnover} and drain velocity v_{drain}.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative values are rejected.

Aliases (required):
  is_entry_blocked()                                                                   -> bool
  is_blocked()                                                                         -> bool   (alias)
  record_queue_update(standing_depth, added_vol=0.0, cancelled_vol=0.0, ts=None)       -> None
  update(standing_depth, added_vol=0.0, cancelled_vol=0.0, ts=None)                    -> None   (alias)
  get_queue_metrics()                                                                  -> dict
  get_status()                                                                         -> dict
  reset()                                                                              -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SECONDS: float = 3.0               # 3.0 seconds rolling evaluation window
MAX_TURNOVER_RATIO: float = 4.0           # 4.0x queue turnover within 3.0s
MIN_STANDING_DEPTH: float = 10.0          # 10.0 lots minimum standing depth
MAX_DRAIN_VELOCITY: float = 8.0           # 8.0 lots/sec rapid queue drain without trades
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
# History of (ts, added_vol, cancelled_vol)
_events = collections.deque()
_latest_standing_depth: float = 0.0
_latest_turnover_ratio: float = 0.0
_latest_drain_velocity: float = 0.0
_blocked_until: float = 0.0


def _is_valid_non_negative(val: Any) -> bool:
    """Validate value is a non-negative finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val >= 0.0


def _prune_events(now: float) -> None:
    """Remove queue update events older than WINDOW_SECONDS."""
    cutoff = now - WINDOW_SECONDS
    while _events and _events[0][0] < cutoff:
        _events.popleft()


def record_queue_update(
    standing_depth: float,
    added_vol: float = 0.0,
    cancelled_vol: float = 0.0,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest queue update state and evaluate turnover ratio and queue drain velocity.
    """
    global _latest_standing_depth, _latest_turnover_ratio, _latest_drain_velocity, _blocked_until

    if not _is_valid_non_negative(standing_depth):
        return
    if not _is_valid_non_negative(added_vol):
        return
    if not _is_valid_non_negative(cancelled_vol):
        return

    q_stand = float(standing_depth)
    v_add = float(added_vol)
    v_cancel = float(cancelled_vol)

    with _lock:
        now = time.monotonic() if ts is None else float(ts)
        _latest_standing_depth = q_stand

        _events.append((now, v_add, v_cancel))
        _prune_events(now)

        tot_added = sum(e[1] for e in _events)
        tot_cancelled = sum(e[2] for e in _events)
        tot_churn = tot_added + tot_cancelled

        turnover_ratio = tot_churn / max(0.1, q_stand)
        _latest_turnover_ratio = turnover_ratio

        # Calculate time span of events in window
        if len(_events) >= 2:
            dt = max(0.1, _events[-1][0] - _events[0][0])
            drain_velocity = tot_cancelled / dt
        else:
            drain_velocity = tot_cancelled / WINDOW_SECONDS
        _latest_drain_velocity = drain_velocity

        # Condition 1: Excessive Queue Turnover Churn
        if turnover_ratio >= MAX_TURNOVER_RATIO and q_stand >= MIN_STANDING_DEPTH:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 2: Toxic Queue Evaporation / Rapid Drain
        if drain_velocity >= MAX_DRAIN_VELOCITY and tot_cancelled >= 10.0:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(
    standing_depth: float,
    added_vol: float = 0.0,
    cancelled_vol: float = 0.0,
    ts: Optional[float] = None,
) -> None:
    """Alias for record_queue_update()."""
    record_queue_update(standing_depth, added_vol, cancelled_vol, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to queue turnover / churn."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_queue_metrics() -> Dict[str, float]:
    """Return latest calculated standing depth, turnover ratio, and drain velocity."""
    with _lock:
        return {
            "standing_depth": _latest_standing_depth,
            "turnover_ratio": _latest_turnover_ratio,
            "drain_velocity": _latest_drain_velocity,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the queue turnover churn guard."""
    with _lock:
        now = time.monotonic()
        return {
            "standing_depth": _latest_standing_depth,
            "turnover_ratio": _latest_turnover_ratio,
            "drain_velocity": _latest_drain_velocity,
            "event_count": len(_events),
            "window_seconds": WINDOW_SECONDS,
            "max_turnover_ratio": MAX_TURNOVER_RATIO,
            "min_standing_depth": MIN_STANDING_DEPTH,
            "max_drain_velocity": MAX_DRAIN_VELOCITY,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset queue history, churn events, metrics, and active cooldown blocks."""
    global _latest_standing_depth, _latest_turnover_ratio, _latest_drain_velocity, _blocked_until
    with _lock:
        _events.clear()
        _latest_standing_depth = 0.0
        _latest_turnover_ratio = 0.0
        _latest_drain_velocity = 0.0
        _blocked_until = 0.0
