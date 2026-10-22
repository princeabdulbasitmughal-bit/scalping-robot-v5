"""
wave109_holding_cost_guard.py
-------------------------------
Guard: Holding Cost (Swap & Financing) Guard

Prevents excessive accumulation of negative financing fees (rollover / swap charges)
across open positions. If aggregate unrealized swap costs exceed a risk threshold,
new entries are blocked.

Logic:
- Maintains a dictionary of {ticket: swap_cost_usd} for all currently open positions.
- Computes aggregate swap: total_swap = sum(swap_cost_usd).
- Negative values indicate financing charges debited from the account.
- If total_swap <= MAX_NEGATIVE_SWAP_USD (default: -25.0 USD), blocks entries for
  COOLDOWN_SECONDS (default: 60.0s).
- Thread-safe: threading.RLock() on all shared state.
- Numeric validation guards against NaN, Inf, and booleans.

Aliases (required):
  is_entry_blocked()             -> bool
  is_blocked()                   -> bool   (alias)
  update_swap(ticket, swap_usd)  -> None
  close_ticket(ticket)           -> None
  update(ticket, swap_usd)       -> None   (alias for update_swap)
  reset()                        -> None
"""

import math
import threading
import time

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_NEGATIVE_SWAP_USD: float = -25.0   # maximum permissible negative swap/financing ($)
COOLDOWN_SECONDS: float = 60.0        # duration of block once threshold breached


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_swaps: dict = {}
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_ticket(ticket) -> bool:
    if isinstance(ticket, bool):
        return False
    if isinstance(ticket, int):
        return True
    if isinstance(ticket, str) and ticket.strip():
        return True
    return False


def _validate_swap(swap) -> bool:
    if isinstance(swap, bool):
        return False
    if not isinstance(swap, (int, float)):
        return False
    if math.isnan(swap) or math.isinf(swap):
        return False
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update_swap(ticket, swap_usd) -> None:
    """Update or record the accrued swap cost for an open position."""
    if not _validate_ticket(ticket) or not _validate_swap(swap_usd):
        return

    global _blocked_until
    with _lock:
        _swaps[ticket] = float(swap_usd)
        total_swap = sum(_swaps.values())
        if total_swap <= MAX_NEGATIVE_SWAP_USD:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def close_ticket(ticket) -> None:
    """Remove a closed position from the swap tracking pool."""
    if not _validate_ticket(ticket):
        return

    with _lock:
        _swaps.pop(ticket, None)


def update(ticket, swap_usd) -> None:
    """Alias for update_swap()."""
    update_swap(ticket, swap_usd)


def is_entry_blocked() -> bool:
    """Return True if total swap cost has breached the allowable negative limit."""
    with _lock:
        if time.monotonic() < _blocked_until:
            return True
        total_swap = sum(_swaps.values())
        return total_swap <= MAX_NEGATIVE_SWAP_USD


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Clear all tracked swap costs and reset block status."""
    global _blocked_until
    with _lock:
        _swaps.clear()
        _blocked_until = 0.0
