"""
wave125_order_size_drift_guard.py
----------------------------------
Guard: Dynamic Order Size Drift & Fat-Finger Guard

Protects against unexpected position sizing spikes, rogue martingale scaling,
or fat-finger lot size errors by comparing each candidate order's lot size
against the rolling average order size.

Logic:
- Maintains a rolling deque of last WINDOW_SIZE executed order sizes.
- When an order size is checked or updated:
  - If len(deque) >= MIN_SAMPLES (default: 5):
    - avg_size = sum(deque) / len(deque)
    - If lots >= MAX_DRIFT_MULTIPLIER * avg_size (default: 3.0x multiplier),
      blocks entries for COOLDOWN_SECONDS (default: 60.0s).
- Valid executed orders are added to the baseline history via record_order().
- Fail-closed: invalid, non-numeric, or negative lot sizes rejected.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()             -> bool
  is_blocked()                   -> bool   (alias)
  record_order(lots)             -> None
  check_order(lots)              -> bool   (True if order passes, False if blocked)
  update(lots)                   -> None   (alias for record_order)
  reset()                        -> None
"""

import math
import threading
import time
from collections import deque

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 20              # rolling window of order sizes
MIN_SAMPLES: int = 5               # minimum history samples before drift evaluation
MAX_DRIFT_MULTIPLIER: float = 3.0  # 3.0x average size limit
COOLDOWN_SECONDS: float = 60.0     # duration of block on drift breach


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_order_sizes: deque = deque(maxlen=WINDOW_SIZE)
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate(lots) -> bool:
    if isinstance(lots, bool) or not isinstance(lots, (int, float)):
        return False
    if math.isnan(lots) or math.isinf(lots) or lots <= 0.0:
        return False
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_order(lots) -> None:
    """Record an executed order lot size into baseline history and check for drift."""
    if not _validate(lots):
        return

    l = float(lots)
    now = time.monotonic()

    global _blocked_until
    with _lock:
        if len(_order_sizes) >= MIN_SAMPLES:
            avg_size = sum(_order_sizes) / len(_order_sizes)
            if l >= MAX_DRIFT_MULTIPLIER * avg_size:
                _blocked_until = now + COOLDOWN_SECONDS
        _order_sizes.append(l)


def check_order(lots) -> bool:
    """Check if a candidate order size violates drift rules without adding it to history.
    Returns True if safe, False if blocked.
    """
    if not _validate(lots):
        return False

    l = float(lots)
    with _lock:
        if is_entry_blocked():
            return False
        if len(_order_sizes) >= MIN_SAMPLES:
            avg_size = sum(_order_sizes) / len(_order_sizes)
            if l >= MAX_DRIFT_MULTIPLIER * avg_size:
                return False
        return True


def update(lots) -> None:
    """Alias for record_order()."""
    record_order(lots)


def is_entry_blocked() -> bool:
    """Return True if an order size drift violation has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Clear order size history and reset active block."""
    global _blocked_until
    with _lock:
        _order_sizes.clear()
        _blocked_until = 0.0
