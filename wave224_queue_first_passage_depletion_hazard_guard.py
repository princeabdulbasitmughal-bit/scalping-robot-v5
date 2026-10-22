"""
wave224_queue_first_passage_depletion_hazard_guard.py
-------------------------------------------------------
Guard: LOB Queue First-Passage Depletion Hazard Guard

Monitors limit order book queue extinction boundaries and aggressive market order absorption
(Avellaneda & Stoikov 2008; Cont & de Larrard 2013):
    Absorption Ratio:      Phi_{absorb} = V_{aggr} / max(0.1, Q_{standing}) in rolling 3.0s
    Depletion Velocity:    v_{deplete} = max(0.0, Q_{start} - Q_{curr}) / max(0.05, dt) (lots/sec)

In balanced, healthy order book states:
    - Queue depletion is slow and accompanied by continuous replenishment:
      Phi_{absorb} < 0.40, v_{deplete} < 5.0 lots/sec.

During aggressive predatory sweeps, iceberg execution, or institutional market orders:
    - Standing depth at the touch is consumed faster than limit order replenishment can arrive:
        1) Aggressive Absorption Shock:
           Phi_{absorb} >= MAX_ABSORPTION_RATIO (default: 0.85, meaning 85% of standing depth is consumed)
           AND Q_{standing} >= MIN_STANDING_DEPTH (default: 5.0 lots).
        2) Runaway Depletion Velocity:
           v_{deplete} >= MAX_DEPLETION_VELOCITY (default: 12.0 lots/sec queue burn rate)
           with cumulative depth drop >= 8.0 lots.

Posting passive orders into a queue experiencing runaway first-passage depletion results in
instantaneous queue exhaustion, adverse execution selection, and immediate price level loss.

When excessive queue depletion hazard is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests queue events via record_queue_state(standing_depth, aggr_fill_vol=0.0, ts=None).
- Maintains rolling event history within WINDOW_SECONDS = 3.0s.
- Evaluates absorption ratio Phi_{absorb} and depletion velocity v_{deplete}.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative values are rejected.

Aliases (required):
  is_entry_blocked()                                                   -> bool
  is_blocked()                                                         -> bool   (alias)
  record_queue_state(standing_depth, aggr_fill_vol=0.0, ts=None)        -> None
  update(standing_depth, aggr_fill_vol=0.0, ts=None)                   -> None   (alias)
  get_depletion_metrics()                                              -> dict
  get_status()                                                         -> dict
  reset()                                                              -> None
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
MAX_ABSORPTION_RATIO: float = 0.85        # 85% of standing queue absorbed by aggressive flow
MIN_STANDING_DEPTH: float = 5.0           # 5.0 lots minimum standing depth
MAX_DEPLETION_VELOCITY: float = 12.0      # 12.0 lots/sec queue depletion velocity
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
# History of (ts, standing_depth, aggr_fill_vol)
_events = collections.deque()
_latest_standing_depth: float = 0.0
_latest_absorption_ratio: float = 0.0
_latest_depletion_velocity: float = 0.0
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
    """Remove queue events older than WINDOW_SECONDS."""
    cutoff = now - WINDOW_SECONDS
    while _events and _events[0][0] < cutoff:
        _events.popleft()


def record_queue_state(
    standing_depth: float,
    aggr_fill_vol: float = 0.0,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest queue state and evaluate aggressive absorption and depletion velocity.
    """
    global _latest_standing_depth, _latest_absorption_ratio, _latest_depletion_velocity, _blocked_until

    if not _is_valid_non_negative(standing_depth):
        return
    if not _is_valid_non_negative(aggr_fill_vol):
        return

    q = float(standing_depth)
    v_aggr = float(aggr_fill_vol)

    with _lock:
        now = time.monotonic() if ts is None else float(ts)
        _latest_standing_depth = q

        _events.append((now, q, v_aggr))
        _prune_events(now)

        tot_aggr_vol = sum(e[2] for e in _events)
        initial_q = _events[0][1] if _events else q
        current_q = q

        absorption_ratio = tot_aggr_vol / max(0.1, initial_q)
        _latest_absorption_ratio = absorption_ratio

        # Calculate depletion velocity
        dt = max(0.05, now - _events[0][0])
        depth_drop = max(0.0, initial_q - current_q)
        depletion_velocity = depth_drop / dt
        _latest_depletion_velocity = depletion_velocity

        # Condition 1: High aggressive absorption of standing queue
        if absorption_ratio >= MAX_ABSORPTION_RATIO and initial_q >= MIN_STANDING_DEPTH:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 2: Runaway queue depletion velocity
        if depletion_velocity >= MAX_DEPLETION_VELOCITY and depth_drop >= 8.0:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(
    standing_depth: float,
    aggr_fill_vol: float = 0.0,
    ts: Optional[float] = None,
) -> None:
    """Alias for record_queue_state()."""
    record_queue_state(standing_depth, aggr_fill_vol, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to queue depletion hazard."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_depletion_metrics() -> Dict[str, float]:
    """Return latest calculated standing depth, absorption ratio, and depletion velocity."""
    with _lock:
        return {
            "standing_depth": _latest_standing_depth,
            "absorption_ratio": _latest_absorption_ratio,
            "depletion_velocity": _latest_depletion_velocity,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the queue depletion hazard guard."""
    with _lock:
        now = time.monotonic()
        return {
            "standing_depth": _latest_standing_depth,
            "absorption_ratio": _latest_absorption_ratio,
            "depletion_velocity": _latest_depletion_velocity,
            "event_count": len(_events),
            "window_seconds": WINDOW_SECONDS,
            "max_absorption_ratio": MAX_ABSORPTION_RATIO,
            "min_standing_depth": MIN_STANDING_DEPTH,
            "max_depletion_velocity": MAX_DEPLETION_VELOCITY,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset queue event history, metrics, and active cooldown blocks."""
    global _latest_standing_depth, _latest_absorption_ratio, _latest_depletion_velocity, _blocked_until
    with _lock:
        _events.clear()
        _latest_standing_depth = 0.0
        _latest_absorption_ratio = 0.0
        _latest_depletion_velocity = 0.0
        _blocked_until = 0.0
