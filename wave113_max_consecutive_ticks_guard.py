"""
wave113_max_consecutive_ticks_guard.py
----------------------------------------
Guard: Consecutive Directional Tick Run Guard

Protects against entering during directional momentum spikes, cascading stops,
or liquidity voids by detecting consecutive price ticks all moving in the same
direction (monotonic runs).

Logic:
- Compares each incoming price tick with the preceding tick.
- Tracks the consecutive run length of up-ticks (+1) or down-ticks (-1).
- If abs(run_length) >= MAX_CONSECUTIVE_RUN (default: 8 ticks), triggers a
  cooldown block for COOLDOWN_SECONDS (default: 30.0s).
- Flat ticks (equal price) do not increment the run.
- Opposing ticks reverse the run counter direction.
- Thread-safe: threading.RLock() on all state.
- Numeric validation guards against NaN, Inf, and booleans.

Aliases (required):
  is_entry_blocked()      -> bool
  is_blocked()            -> bool   (alias)
  update(price)           -> None
  reset()                 -> None
"""

import math
import threading
import time

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_CONSECUTIVE_RUN: int = 8      # max consecutive ticks in same direction
COOLDOWN_SECONDS: float = 30.0    # block duration upon directional run breach


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_last_price: float = -1.0
_current_direction: int = 0       # +1 for up, -1 for down, 0 for neutral
_run_count: int = 0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update(price) -> None:
    """Record incoming price tick and evaluate directional run."""
    if isinstance(price, bool):
        return
    if not isinstance(price, (int, float)):
        return
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return

    p = float(price)

    global _last_price, _current_direction, _run_count, _blocked_until
    with _lock:
        if _last_price <= 0.0:
            _last_price = p
            return

        if p > _last_price:
            new_dir = 1
        elif p < _last_price:
            new_dir = -1
        else:
            new_dir = 0

        _last_price = p

        if new_dir != 0:
            if new_dir == _current_direction:
                _run_count += 1
            else:
                _current_direction = new_dir
                _run_count = 1

            if _run_count >= MAX_CONSECUTIVE_RUN:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def is_entry_blocked() -> bool:
    """Return True if a directional momentum tick run has triggered a block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Reset tick tracking state and clear cooldown."""
    global _last_price, _current_direction, _run_count, _blocked_until
    with _lock:
        _last_price = -1.0
        _current_direction = 0
        _run_count = 0
        _blocked_until = 0.0
