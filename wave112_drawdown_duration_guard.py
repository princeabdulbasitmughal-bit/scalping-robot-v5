"""
wave112_drawdown_duration_guard.py
------------------------------------
Guard: Prolonged Drawdown Duration Guard

Monitors how long the account has remained continuously below its equity
high-watermark (underwater duration). If an account fails to make a new high
for an extended duration, it indicates an adverse regime or strategy stagnation,
triggering a temporary cooldown block to allow market conditions to reset.

Logic:
- Tracks session equity high-watermark (_hwm).
- When equity >= _hwm, updates _hwm and clears the underwater timer.
- When equity < _hwm, starts or maintains underwater duration counter.
- If continuous underwater duration >= MAX_UNDERWATER_SECONDS (default: 3600.0s = 1 hr),
  blocks entries for COOLDOWN_SECONDS (default: 300.0s = 5 min).
- Thread-safe: threading.RLock() on all shared state.
- Cooldown tracked via time.monotonic().

Aliases (required):
  is_entry_blocked()      -> bool
  is_blocked()            -> bool   (alias)
  update(equity)          -> None
  reset()                 -> None
"""

import math
import threading
import time

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_UNDERWATER_SECONDS: float = 3600.0   # 1 hour max continuous underwater duration
COOLDOWN_SECONDS: float = 300.0         # 5 min block when underwater limit reached


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_hwm: float = 0.0
_underwater_since: float = -1.0         # -1.0 indicates at HWM or uninitialized
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update(equity) -> None:
    """Record current account equity and update high-watermark or underwater timer."""
    if isinstance(equity, bool):
        return
    if not isinstance(equity, (int, float)):
        return
    if math.isnan(equity) or math.isinf(equity) or equity <= 0.0:
        return

    eq = float(equity)
    now = time.monotonic()

    global _hwm, _underwater_since, _blocked_until
    with _lock:
        if _hwm == 0.0:
            _hwm = eq
            _underwater_since = -1.0
            return

        if eq >= _hwm:
            _hwm = eq
            _underwater_since = -1.0
        else:
            if _underwater_since == -1.0:
                _underwater_since = now
            elif (now - _underwater_since) >= MAX_UNDERWATER_SECONDS:
                _blocked_until = now + COOLDOWN_SECONDS


def is_entry_blocked() -> bool:
    """Return True if account has been underwater too long and cooldown is active."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Reset HWM, underwater timer, and active block."""
    global _hwm, _underwater_since, _blocked_until
    with _lock:
        _hwm = 0.0
        _underwater_since = -1.0
        _blocked_until = 0.0
