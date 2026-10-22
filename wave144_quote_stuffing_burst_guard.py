"""
wave144_quote_stuffing_burst_guard.py
-------------------------------------
Guard: Order Book Quote Stuffing & Feed Saturation Burst Guard

Monitors top-of-book quote update frequency over sub-second micro-windows.
Quote stuffing occurs when predatory high-frequency algorithms generate massive
bursts of quote updates (bid/ask price and volume revisions) without trade executions,
causing artificial message queue latency, order book flicker, and feed saturation.

Logic:
- Records timestamped quote arrivals (bid and ask).
- Maintains a rolling queue of quote timestamps over BURST_WINDOW_SEC (default: 1.0s).
- Computes instantaneous quote arrival rate:
    rate = count(quotes_in_window) / BURST_WINDOW_SEC
- If rate >= MAX_QUOTES_PER_SEC (default: 40.0 quotes/sec):
    blocks entries for COOLDOWN_SECONDS (default: 45.0s) to protect against
    stale fill execution during feed congestion.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Fail-closed: invalid, non-numeric, boolean, NaN, Inf, and non-positive prices ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()                           -> bool
  is_blocked()                                 -> bool   (alias)
  record_quote(bid, ask, ts=None)              -> None
  update(bid, ask, ts=None)                    -> None   (alias)
  get_current_quote_rate()                     -> float
  reset()                                      -> None
"""

import collections
import math
import threading
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BURST_WINDOW_SEC: float = 1.0          # micro-window for burst frequency calculation
MAX_QUOTES_PER_SEC: float = 40.0       # quote frequency limit triggering block
COOLDOWN_SECONDS: float = 45.0         # duration of protective block on feed saturation


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_timestamps = collections.deque()
_blocked_until: float = 0.0
_last_rate: float = 1.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_quote(bid, ask, ts=None) -> None:
    """Record quote arrival and evaluate quote stuffing burst frequency."""
    for p in (bid, ask):
        if isinstance(p, bool) or not isinstance(p, (int, float)):
            return
        if math.isnan(p) or math.isinf(p) or p <= 0.0:
            return

    b = float(bid)
    a = float(ask)
    if a <= b:
        return

    now = float(ts) if (ts is not None and isinstance(ts, (int, float)) and not isinstance(ts, bool)) else time.monotonic()

    global _blocked_until, _last_rate
    with _lock:
        _timestamps.append(now)

        cutoff = now - BURST_WINDOW_SEC
        while _timestamps and _timestamps[0] < cutoff:
            _timestamps.popleft()

        rate = len(_timestamps) / BURST_WINDOW_SEC
        _last_rate = rate

        if rate >= MAX_QUOTES_PER_SEC:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(bid, ask, ts=None) -> None:
    """Alias for record_quote()."""
    record_quote(bid, ask, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if quote stuffing burst has triggered an entry block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_current_quote_rate() -> float:
    """Return the most recently computed quote arrival rate (quotes/sec)."""
    with _lock:
        return _last_rate


def reset() -> None:
    """Reset quote timestamps, rate metrics, and active block."""
    global _blocked_until, _last_rate
    with _lock:
        _timestamps.clear()
        _blocked_until = 0.0
        _last_rate = 1.0
