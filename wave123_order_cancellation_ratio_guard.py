"""
wave123_order_cancellation_ratio_guard.py
-------------------------------------------
Guard: Order Rejection & Cancellation Ratio Guard

Monitors broker connectivity and order routing health by tracking the ratio
of rejected or cancelled orders relative to successful fills. High cancellation
or reject ratios indicate broker API throttling, liquidity provider rejects,
or pricing desynchronization.

Logic:
- Records each order outcome: 1 if rejected/cancelled, 0 if filled.
- Maintains a rolling deque of last WINDOW_SIZE order attempts.
- When len(deque) >= MIN_SAMPLES (default: 5), calculates reject_ratio = rejects / total.
- If reject_ratio >= MAX_REJECT_RATIO (default: 0.30, i.e. 30%+ order failures),
  blocks entries for COOLDOWN_SECONDS (default: 120.0s).
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()                            -> bool
  is_blocked()                                  -> bool   (alias)
  record_order(is_rejected: bool)               -> None
  update(is_rejected: bool)                     -> None   (alias)
  reset()                                       -> None
"""

import threading
import time
from collections import deque

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 10              # rolling window of order execution attempts
MIN_SAMPLES: int = 5               # minimum orders required before evaluation
MAX_REJECT_RATIO: float = 0.30     # 30% rejection/cancellation threshold
COOLDOWN_SECONDS: float = 120.0    # duration of block upon execution health failure


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_order_outcomes: deque = deque(maxlen=WINDOW_SIZE)
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_order(is_rejected: bool) -> None:
    """Record an order outcome. True indicates rejected/cancelled, False indicates filled."""
    if not isinstance(is_rejected, bool):
        return

    val = 1 if is_rejected else 0
    now = time.monotonic()

    global _blocked_until
    with _lock:
        _order_outcomes.append(val)
        if len(_order_outcomes) >= MIN_SAMPLES:
            ratio = sum(_order_outcomes) / len(_order_outcomes)
            if ratio >= MAX_REJECT_RATIO:
                _blocked_until = now + COOLDOWN_SECONDS


def update(is_rejected: bool) -> None:
    """Alias for record_order()."""
    record_order(is_rejected)


def is_entry_blocked() -> bool:
    """Return True if order rejection/cancellation ratio triggers an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Clear order outcome history and reset active block."""
    global _blocked_until
    with _lock:
        _order_outcomes.clear()
        _blocked_until = 0.0
