"""
wave196_quote_intensity_acceleration_guard.py
----------------------------------------------
Guard: Quote Arrival Intensity Acceleration & Burst Churn Guard

Monitors high-frequency top-of-book quote update intensity and discrete acceleration:
    Intensity:     lambda_t = N_{[t - W, t]} / W       (quotes/second)
    Acceleration:  a_t = (lambda_t - lambda_{t - W}) / W (quotes/second^2)
where W = 1.0 second observation window.

In healthy order-driven trading environments, quote arrival rates reflect steady price discovery
and modest algorithmic updates:
    - Quote intensity: lambda_t < 60.0 quotes/sec
    - Acceleration:    a_t < 40.0 quotes/sec^2

During predatory microstructure events—such as quote stuffing, rapid cancellation churn,
flashing spoof quotes, or sudden feed congestion—quote generation surges violently:
    1) Hyper-intensity breach:
       lambda_t >= MAX_QUOTE_INTENSITY (default: 120.0 quotes/sec)
    2) Violent acceleration shock:
       a_t >= MAX_INTENSITY_ACCELERATION (default: 80.0 quotes/sec^2)
       with elevated baseline intensity (lambda_t >= MIN_ACTIVE_INTENSITY = 40.0 quotes/sec).

In these hyper-active churn conditions, retail scalping infrastructure experiences socket queue
bloat, quotation latency, and severe fill degradation (slipping past vanished quotes).

When excessive quote intensity or acceleration is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s) until normal book cadence is restored.

Logic:
- Ingests quote updates (bid > 0.0, ask > bid, ts=None).
- Records arrival timestamps in a rolling window.
- Computes arrival count in current window [now - W, now] and prior window [now - 2W, now - W].
- Evaluates intensity lambda_t and acceleration a_t.
- Blocks entries for COOLDOWN_SECONDS (45.0s) if thresholds are breached.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive bids/asks, or inverted quotes are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_quote(bid, ask, ts=None)                          -> None
  update(bid, ask, ts=None)                                -> None   (alias)
  get_intensity()                                          -> float
  get_acceleration()                                       -> float
  get_status()                                             -> dict
  reset()                                                  -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SECONDS: float = 1.0
MAX_QUOTE_INTENSITY: float = 120.0          # quotes/sec
MAX_INTENSITY_ACCELERATION: float = 80.0    # quotes/sec^2
MIN_ACTIVE_INTENSITY: float = 40.0          # min intensity required for acceleration trip
COOLDOWN_SECONDS: float = 45.0
MAX_TIMESTAMP_HISTORY: int = 500

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_timestamps = collections.deque(maxlen=MAX_TIMESTAMP_HISTORY)
_latest_intensity: float = 0.0
_latest_acceleration: float = 0.0
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
    Ingest a new top-of-book quote update and calculate arrival rate metrics.
    """
    global _latest_intensity, _latest_acceleration, _blocked_until

    if not _is_valid_price(bid) or not _is_valid_price(ask):
        return
    if float(ask) <= float(bid):
        # Inverted or crossed quote invalid
        return

    with _lock:
        now = time.monotonic() if ts is None else float(ts)
        _timestamps.append(now)

        # Count events in current window [now - W, now]
        current_cutoff = now - WINDOW_SECONDS
        prior_cutoff = now - (2.0 * WINDOW_SECONDS)

        # Evict timestamps older than 2 * WINDOW_SECONDS from the front of deque
        while _timestamps and _timestamps[0] < prior_cutoff:
            _timestamps.popleft()

        curr_count = 0
        prior_count = 0
        for t in _timestamps:
            if t >= current_cutoff:
                curr_count += 1
            elif t >= prior_cutoff:
                prior_count += 1

        curr_intensity = curr_count / WINDOW_SECONDS
        prior_intensity = prior_count / WINDOW_SECONDS
        acceleration = (curr_intensity - prior_intensity) / WINDOW_SECONDS

        _latest_intensity = curr_intensity
        _latest_acceleration = acceleration

        # Condition 1: Hyper-intensity breach
        if curr_intensity >= MAX_QUOTE_INTENSITY:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 2: Violent acceleration surge
        if acceleration >= MAX_INTENSITY_ACCELERATION and curr_intensity >= MIN_ACTIVE_INTENSITY:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(bid: float, ask: float, ts: Optional[float] = None) -> None:
    """Alias for record_quote()."""
    record_quote(bid, ask, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to quote churn."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_intensity() -> float:
    """Return the latest calculated quote arrival intensity (quotes/sec)."""
    with _lock:
        return _latest_intensity


def get_acceleration() -> float:
    """Return the latest calculated quote intensity acceleration (quotes/sec^2)."""
    with _lock:
        return _latest_acceleration


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the quote intensity guard."""
    with _lock:
        now = time.monotonic()
        return {
            "intensity": _latest_intensity,
            "acceleration": _latest_acceleration,
            "history_count": len(_timestamps),
            "window_seconds": WINDOW_SECONDS,
            "max_intensity_threshold": MAX_QUOTE_INTENSITY,
            "max_acceleration_threshold": MAX_INTENSITY_ACCELERATION,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset quote history, intensity metrics, and active blocks."""
    global _latest_intensity, _latest_acceleration, _blocked_until
    with _lock:
        _timestamps.clear()
        _latest_intensity = 0.0
        _latest_acceleration = 0.0
        _blocked_until = 0.0
