"""
wave152_order_size_herding_guard.py
-----------------------------------
Guard: Institutional Order Size Herding & Iceberg Slicing Guard

Detects algorithmic order slicing (TWAP/VWAP/POV institutional execution engines)
characterised by consecutive identical or fixed-lot trades occurring in rapid succession.
When institutional execution algorithms sweep or slice parent blocks into repetitive
child orders (e.g. 6+ consecutive trades of identical lot sizes within 10 seconds),
retail scalpers entering counter-trend face asymmetric adverse inventory exhaustion.

Logic:
- Records trade size and execution timestamp.
- Validates inputs (size > 0, numeric, non-NaN, non-Inf, non-boolean).
- Compares incoming trade size with current run size.
- Resets run if the inter-arrival time exceeds WINDOW_SECONDS (default: 10.0s).
- If trade size matches previous trade size within epsilon (1e-6):
    increments streak count.
- If streak count >= MAX_HERD_STREAK (default: 6 trades):
    triggers an entry block for COOLDOWN_SECONDS (default: 45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: invalid or corrupted trade parameters are ignored.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_trade_size(size, ts=None)                         -> None
  update(size, ts=None)                                    -> None   (alias)
  get_herding_run_length()                                 -> int
  reset()                                                  -> None
"""

import math
import threading
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_HERD_STREAK: int = 6           # Consecutive identical order sizes trigger institutional iceberg guard
WINDOW_SECONDS: float = 10.0       # Max elapsed time between child orders to sustain streak
COOLDOWN_SECONDS: float = 45.0     # Cooling-off duration on institutional execution detection


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_streak_size: Optional[float] = None
_streak_count: int = 0
_last_ts: Optional[float] = None
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_trade_size(size, ts=None) -> None:
    """Record an incoming trade size and check for algorithmic iceberg herding streaks."""
    if isinstance(size, bool) or not isinstance(size, (int, float)):
        return
    if math.isnan(size) or math.isinf(size) or size <= 0.0:
        return

    s = float(size)
    now = float(ts) if (ts is not None and isinstance(ts, (int, float)) and not isinstance(ts, bool)) else time.monotonic()

    global _streak_size, _streak_count, _last_ts, _blocked_until
    with _lock:
        if _last_ts is not None and (now - _last_ts) > WINDOW_SECONDS:
            # Time gap exceeded window: reset streak
            _streak_size = s
            _streak_count = 1
            _last_ts = now
            return

        _last_ts = now

        if _streak_size is not None and abs(s - _streak_size) < 1e-6:
            _streak_count += 1
        else:
            _streak_size = s
            _streak_count = 1

        if _streak_count >= MAX_HERD_STREAK:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(size, ts=None) -> None:
    """Alias for record_trade_size()."""
    record_trade_size(size, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if institutional order size herding has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_herding_run_length() -> int:
    """Return the current consecutive streak length of identical order sizes."""
    with _lock:
        return _streak_count


def reset() -> None:
    """Reset streak state, timestamp, and active cooldown."""
    global _streak_size, _streak_count, _last_ts, _blocked_until
    with _lock:
        _streak_size = None
        _streak_count = 0
        _last_ts = None
        _blocked_until = 0.0
