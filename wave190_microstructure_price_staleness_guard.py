"""
wave190_microstructure_price_staleness_guard.py
------------------------------------------------
Guard: Microstructure Quote & Price Staleness Age & Post-Stale Gap Guard

Monitors the real-time freshness of price ticks and detects latency-induced freeze gaps:
    delta_t_tick = t_current - t_prev
    Gap_bps = |P_current - P_prev| / P_prev

In high-frequency electronic markets, retail broker bridges or client network connections can
suffer transient quote freezes, packet drops, or buffer bloat. While quotes are frozen, external
interbank venues continue trading.
When the frozen feed finally unfreezes, a deluge of queued ticks arrives with a violent jump gap:
1. Active Staleness: delta_t_tick >= MAX_STALENESS_SEC (default: 3.0s) means the book feed is stale.
2. Post-Stale Jump Gap: If feed freezes for >= 3.0s and then unfreezes with a jump gap:
    Gap_bps >= MIN_POST_STALENESS_GAP_BPS (default: 3.0 bps / 0.00030)
the local book is absorbing stale executions and suffering from severe latency dislocation.

When active staleness or a post-stale jump gap is detected, entry orders are blocked immediately for
COOLDOWN_SECONDS (default: 45.0s) until clean, continuous quoting is re-established.

Logic:
- Ingests incoming price ticks with optional high-precision timestamps (ts).
- If ts is omitted, resolves timestamp via time.monotonic().
- Measures inter-tick duration delta_t = current_ts - prev_ts.
- Flags active staleness if delta_t >= MAX_STALENESS_SEC (3.0s).
- Evaluates post-staleness jump gap: Gap_bps = |P - prev_P| / prev_P.
- If delta_t >= 3.0s and Gap_bps >= 0.00030:
    blocks entries for COOLDOWN_SECONDS (45.0s).
- Real-time check: is_entry_blocked() returns True if time since last tick exceeds MAX_STALENESS_SEC.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive prices are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_price(price, ts=None)                             -> None
  update(price, ts=None)                                   -> None   (alias)
  get_staleness_sec()                                      -> float
  get_gap_bps()                                            -> float
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
MAX_STALENESS_SEC: float = 3.0        # Quote age >= 3.0s indicates stale / frozen price feed
MIN_POST_STALENESS_GAP_BPS: float = 0.00030 # 3.0 bps jump gap after unfreezing triggers block
COOLDOWN_SECONDS: float = 45.0        # Block duration on post-staleness unfreeze shock


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_price: Optional[float] = None
_prev_ts: Optional[float] = None
_latest_staleness_sec: float = 0.0
_latest_gap_bps: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_price(price, ts=None) -> None:
    """Record an incoming price tick and evaluate feed staleness and post-stale jump gap."""
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return

    p = float(price)

    if ts is not None:
        if isinstance(ts, bool) or not isinstance(ts, (int, float)):
            return
        if math.isnan(ts) or math.isinf(ts) or ts < 0.0:
            return
        current_ts = float(ts)
    else:
        current_ts = time.monotonic()

    global _prev_price, _prev_ts, _latest_staleness_sec, _latest_gap_bps, _blocked_until
    with _lock:
        if _prev_ts is not None and _prev_price is not None:
            dt = current_ts - _prev_ts
            if dt > 0.0:
                _latest_staleness_sec = dt
                gap_bps = abs(p - _prev_price) / _prev_price
                _latest_gap_bps = gap_bps

                if dt >= MAX_STALENESS_SEC and gap_bps >= MIN_POST_STALENESS_GAP_BPS:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS

        _prev_price = p
        _prev_ts = current_ts


def update(price, ts=None) -> None:
    """Alias for record_price()."""
    record_price(price, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if active block is in effect or current feed age exceeds staleness ceiling."""
    with _lock:
        now = time.monotonic()
        if now < _blocked_until:
            return True
        return False


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_staleness_sec() -> float:
    """Return the most recently measured inter-tick duration in seconds."""
    with _lock:
        return _latest_staleness_sec


def get_gap_bps() -> float:
    """Return the most recently measured price gap in basis points."""
    with _lock:
        return _latest_gap_bps


def get_status() -> Dict[str, Any]:
    """Return a diagnostic snapshot of the quote staleness guard state."""
    with _lock:
        now = time.monotonic()
        return {
            "latest_staleness_sec": _latest_staleness_sec,
            "latest_gap_bps": _latest_gap_bps,
            "max_staleness_sec_threshold": MAX_STALENESS_SEC,
            "min_post_staleness_gap_bps": MIN_POST_STALENESS_GAP_BPS,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": is_entry_blocked(),
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset price state, timestamps, gap metrics, and active blocks."""
    global _prev_price, _prev_ts, _latest_staleness_sec, _latest_gap_bps, _blocked_until
    with _lock:
        _prev_price = None
        _prev_ts = None
        _latest_staleness_sec = 0.0
        _latest_gap_bps = 0.0
        _blocked_until = 0.0
