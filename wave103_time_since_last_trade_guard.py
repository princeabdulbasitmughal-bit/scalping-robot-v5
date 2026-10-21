"""
wave103_time_since_last_trade_guard.py
----------------------------------------
Guard: Time-Since-Last-Trade Guard (Minimum Trade Interval)

Enforces a minimum interval between successive trade entries to prevent
over-trading / order-spamming on the same signal.

Logic:
- Tracks the monotonic timestamp of the last registered trade.
- Blocks new entries when (now - last_trade_time) < MIN_INTERVAL_SECONDS
  (default: 30s).
- No cooldown separate from the interval — the block naturally expires when
  enough time has elapsed since the last trade.
- Fail-closed before first trade: NOT blocked (no prior trade = no restriction).
- Thread-safe: threading.RLock() on all shared state.

Aliases (required):
  is_entry_blocked()  -> bool
  is_blocked()        -> bool   (alias)
  record_trade()      -> None   (call when a trade is submitted)
  update()            -> None   (alias for record_trade)
  reset()             -> None
"""

import threading
import time

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MIN_INTERVAL_SECONDS: float = 30.0   # minimum time between trades


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_last_trade_time: float = -1.0   # -1.0 = no trade recorded yet


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_trade() -> None:
    """Register that a trade was just submitted. Resets the interval timer."""
    global _last_trade_time
    with _lock:
        _last_trade_time = time.monotonic()


def update() -> None:
    """Alias for record_trade()."""
    record_trade()


def is_entry_blocked() -> bool:
    """Return True when minimum interval since last trade has not elapsed."""
    with _lock:
        if _last_trade_time < 0.0:
            return False   # no trade recorded yet — not blocked
        elapsed = time.monotonic() - _last_trade_time
        return elapsed < MIN_INTERVAL_SECONDS


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Clear trade timestamp (use between tests or sessions)."""
    global _last_trade_time
    with _lock:
        _last_trade_time = -1.0
