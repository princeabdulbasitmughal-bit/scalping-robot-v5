"""
wave132_tick_run_length_guard.py
---------------------------------
Guard: Microstructure Directional Run Length & Streak Persistence Guard

Monitors unbroken monotonic price runs (consecutive positive or consecutive
negative tick-to-tick movements). Extended unbroken runs represent severe
order book thinning, aggressive market order sweeps, or toxic informed flow.

Logic:
- Evaluates consecutive price transitions:
    diff = price_curr - price_prev
    diff > 0: uptick -> run += 1 if run > 0 else 1
    diff < 0: downtick -> run -= 1 if run < 0 else -1
    diff == 0: flat tick -> preserves current streak or breaks?
                 breaks streak to 0 to require strict directional continuity.
- If abs(run) >= MAX_RUN_LENGTH (default: 8 consecutive monotonic ticks):
    blocks entries for COOLDOWN_SECONDS (default: 30.0s) to prevent entering
    against runaway momentum sweeps.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Fail-closed: invalid, non-numeric, boolean, NaN, Inf, and non-positive prices ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()             -> bool
  is_blocked()                   -> bool   (alias)
  record_tick(price, ts=None)    -> None
  update(price, ts=None)         -> None   (alias)
  get_current_run()              -> int
  reset()                        -> None
"""

import math
import threading
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_RUN_LENGTH: int = 8                # consecutive monotonic ticks triggering block
COOLDOWN_SECONDS: float = 30.0         # duration of protective block


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_price: Optional[float] = None
_current_run: int = 0                  # positive for upticks, negative for downticks
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_tick(price, ts=None) -> None:
    """Record tick price and evaluate monotonic run streak."""
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return

    curr_p = float(price)

    global _prev_price, _current_run, _blocked_until
    with _lock:
        if _prev_price is None:
            _prev_price = curr_p
            _current_run = 0
            return

        diff = curr_p - _prev_price
        if diff > 1e-9:
            if _current_run > 0:
                _current_run += 1
            else:
                _current_run = 1
        elif diff < -1e-9:
            if _current_run < 0:
                _current_run -= 1
            else:
                _current_run = -1
        else:
            # Flat tick breaks directional continuity
            _current_run = 0

        _prev_price = curr_p

        if abs(_current_run) >= MAX_RUN_LENGTH:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(price, ts=None) -> None:
    """Alias for record_tick()."""
    record_tick(price, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if an extended directional tick run is blocking entries."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_current_run() -> int:
    """Return current run streak (positive for upticks, negative for downticks)."""
    with _lock:
        return _current_run


def reset() -> None:
    """Reset run length tracking, price history, and active block."""
    global _prev_price, _current_run, _blocked_until
    with _lock:
        _prev_price = None
        _current_run = 0
        _blocked_until = 0.0
