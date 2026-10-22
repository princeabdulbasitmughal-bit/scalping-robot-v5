"""
wave239_cancellation_intensity_acceleration_guard.py
------------------------------------------------------
Guard: Order Cancellation Intensity & Second-Derivative Acceleration Guard

Monitors limit order cancellation rate and second-derivative cancellation acceleration
(Hasbrouck & Saar 2013; Hautsch & Huang 2012; Cartea et al. 2015):
    Current Cancellation Rate:   C_{curr} = cancellations in [t - 1.0s, t] (cancels / sec)
    Previous Cancellation Rate:  C_{prev} = cancellations in [t - 2.0s, t - 1.0s) (cancels / sec)
    Cancellation Acceleration:   a_{cancel} = C_{curr} - C_{prev} (cancels / sec^2)
    Acute Blitz Burst:           B_{acute} = cancellations in [t - 0.5s, t]

In normal orderly two-sided market making:
    - Order cancellation rates change smoothly and symmetrically:
      C_{curr} ~ 2 - 8 cancels/sec, with |a_{cancel}| < 5.0 cancels/sec^2.

During quote stuffing, predatory queue vanishing, algorithmic phantom liquidity pull,
or institutional risk-off de-leveraging cascades:
    - Algorithms cancel passive limit depth at explosive non-linear speeds:
        1) Acceleration Surge:
           a_{cancel} >= MAX_ACCELERATION (default: 15.0 cancels/sec^2) AND
           C_{curr} >= MIN_CURRENT_CANCELS (default: 20.0 cancels/sec).
        2) Acute Blitz Burst:
           B_{acute} >= MAX_ACUTE_BURST (default: 25 cancellations in <= 0.5s) OR
           C_{curr} >= MAX_INSTANTANEOUS_CANCELS (default: 35.0 cancels/sec).

Submitting limit orders or attempting to fade into an escalating cancellation blitz results in
immediate quote evaporation, adverse fill selection, and severe execution slippage.

When cancellation acceleration surge or acute burst is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests cancellation events via record_cancellation(count=1, ts=None) or
  direct rate feeds via record_cancellation_rate(cancels_per_sec, prev_cancels_per_sec=None, ts=None).
- Maintains sliding event history window of 5.0 seconds.
- Evaluates a_{cancel}, C_{curr}, and acute blitz burst B_{acute}.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative counts/rates are rejected.

Aliases (required):
  is_entry_blocked()                                                                   -> bool
  is_blocked()                                                                         -> bool   (alias)
  record_cancellation(count=1, ts=None)                                                -> None
  record_cancellation_rate(cancels_per_sec, prev_cancels_per_sec=None, ts=None)        -> None
  update(count=1, ts=None)                                                             -> None   (alias)
  get_cancellation_metrics()                                                           -> dict
  get_status()                                                                         -> dict
  reset()                                                                              -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any, List, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_ACCELERATION: float = 15.0             # 15.0 cancels/sec^2 acceleration surge
MIN_CURRENT_CANCELS: float = 20.0          # 20.0 cancels/sec threshold for acceleration
MAX_ACUTE_BURST: float = 25.0              # 25 cancellations in <= 0.5s blitz window
MAX_INSTANTANEOUS_CANCELS: float = 35.0    # 35.0 cancels/sec instant ceiling
COOLDOWN_SECONDS: float = 45.0
HISTORY_WINDOW_SECONDS: float = 5.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_cancel_events: collections.deque = collections.deque()  # elements: (timestamp, count)
_latest_c_curr: float = 0.0
_latest_c_prev: float = 0.0
_latest_acceleration: float = 0.0
_latest_acute_burst: float = 0.0
_blocked_until: float = 0.0


def _is_valid_non_negative(val: Any) -> bool:
    """Validate value is a non-negative finite numeric float or int."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val >= 0.0


def record_cancellation(
    count: float = 1,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest a cancellation event count at given timestamp (or current time).
    Evaluates rolling rates, acceleration, and acute burst.
    """
    global _latest_c_curr, _latest_c_prev, _latest_acceleration
    global _latest_acute_burst, _blocked_until

    if not _is_valid_non_negative(count):
        return

    c = float(count)
    if c == 0.0:
        return

    now = float(ts) if ts is not None else time.time()

    with _lock:
        _cancel_events.append((now, c))

        # Prune events older than HISTORY_WINDOW_SECONDS relative to latest event
        cutoff = now - HISTORY_WINDOW_SECONDS
        while _cancel_events and _cancel_events[0][0] < cutoff:
            _cancel_events.popleft()

        # Compute counts in time slices:
        # [now - 1.0, now] -> C_curr
        # [now - 2.0, now - 1.0) -> C_prev
        # [now - 0.5, now] -> Acute burst
        c_curr = 0.0
        c_prev = 0.0
        acute_burst = 0.0

        for t_evt, cnt in _cancel_events:
            age = now - t_evt
            if age <= 0.5:
                acute_burst += cnt
            if age <= 1.0:
                c_curr += cnt
            elif age <= 2.0:
                c_prev += cnt

        acceleration = c_curr - c_prev

        _latest_c_curr = c_curr
        _latest_c_prev = c_prev
        _latest_acceleration = acceleration
        _latest_acute_burst = acute_burst

        # Condition 1: Acute blitz burst or extreme instant rate
        if acute_burst >= MAX_ACUTE_BURST or c_curr >= MAX_INSTANTANEOUS_CANCELS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 2: Acceleration surge with elevated current cancellation rate
        if acceleration >= MAX_ACCELERATION and c_curr >= MIN_CURRENT_CANCELS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_cancellation_rate(
    cancels_per_sec: float,
    prev_cancels_per_sec: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Directly ingest measured current and previous cancellation rates.
    """
    global _latest_c_curr, _latest_c_prev, _latest_acceleration, _blocked_until

    if not _is_valid_non_negative(cancels_per_sec):
        return

    c_curr = float(cancels_per_sec)

    with _lock:
        if prev_cancels_per_sec is not None:
            if not _is_valid_non_negative(prev_cancels_per_sec):
                return
            c_prev = float(prev_cancels_per_sec)
        else:
            c_prev = _latest_c_curr

        acceleration = c_curr - c_prev

        _latest_c_curr = c_curr
        _latest_c_prev = c_prev
        _latest_acceleration = acceleration

        # Instantaneous ceiling
        if c_curr >= MAX_INSTANTANEOUS_CANCELS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Acceleration surge
        if acceleration >= MAX_ACCELERATION and c_curr >= MIN_CURRENT_CANCELS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(
    count: float = 1,
    ts: Optional[float] = None,
) -> None:
    """Alias for record_cancellation()."""
    record_cancellation(count, ts)


def is_entry_blocked() -> bool:
    """Check if new entries are blocked by cancellation acceleration."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_cancellation_metrics() -> Dict[str, float]:
    """Retrieve current cancellation metrics."""
    with _lock:
        return {
            "c_curr": _latest_c_curr,
            "c_prev": _latest_c_prev,
            "cancellation_acceleration": _latest_acceleration,
            "acute_burst": _latest_acute_burst,
        }


def get_status() -> Dict[str, Any]:
    """Retrieve complete guard status."""
    with _lock:
        now = time.monotonic()
        blocked = now < _blocked_until
        remaining = max(0.0, _blocked_until - now) if blocked else 0.0
        return {
            "guard_name": "wave239_cancellation_intensity_acceleration_guard",
            "is_blocked": blocked,
            "blocked_seconds_remaining": remaining,
            "event_count": len(_cancel_events),
            "c_curr": _latest_c_curr,
            "c_prev": _latest_c_prev,
            "cancellation_acceleration": _latest_acceleration,
            "acute_burst": _latest_acute_burst,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "max_acceleration": MAX_ACCELERATION,
            "min_current_cancels": MIN_CURRENT_CANCELS,
            "max_acute_burst": MAX_ACUTE_BURST,
            "max_instantaneous_cancels": MAX_INSTANTANEOUS_CANCELS,
        }


def reset() -> None:
    """Reset all guard state and clear cooldowns."""
    global _latest_c_curr, _latest_c_prev, _latest_acceleration
    global _latest_acute_burst, _blocked_until

    with _lock:
        _cancel_events.clear()
        _latest_c_curr = 0.0
        _latest_c_prev = 0.0
        _latest_acceleration = 0.0
        _latest_acute_burst = 0.0
        _blocked_until = 0.0
