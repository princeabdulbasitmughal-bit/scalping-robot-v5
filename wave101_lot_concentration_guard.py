"""
wave101_lot_concentration_guard.py
------------------------------------
Guard: Lot Concentration Guard

Blocks new entries when the total open lot volume across all positions
exceeds a configurable maximum, preventing over-leveraged exposure from
an accumulation of small positions.

Logic:
- Maintains a dict of {ticket: lots} for all open positions.
- Computes total_lots = sum of all open position lot sizes.
- Blocks when total_lots >= MAX_TOTAL_LOTS (default: 5.0).
- No cooldown — block is real-time: lifts as soon as positions are closed
  and total lots fall below the threshold.
- Fail-closed: invalid tickets or non-positive lots silently rejected.
- Thread-safe: threading.RLock() on all shared state.

Aliases (required):
  is_entry_blocked()            -> bool
  is_blocked()                  -> bool       (alias)
  open_position(ticket, lots)   -> None       (register/update an open position)
  close_position(ticket)        -> None       (de-register a closed position)
  update(ticket, lots)          -> None       (open_position alias)
  reset()                       -> None
"""

import math
import threading

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_TOTAL_LOTS: float = 5.0   # maximum aggregate lot exposure allowed


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_positions: dict = {}   # {ticket: lots}


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


def _validate_lots(lots) -> bool:
    if isinstance(lots, bool):
        return False
    if not isinstance(lots, (int, float)):
        return False
    if math.isnan(lots) or math.isinf(lots):
        return False
    if lots <= 0.0:
        return False
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def open_position(ticket, lots) -> None:
    """Register or update an open position's lot size.

    Args:
        ticket: Unique position identifier (int or non-empty str).
        lots:   Positive finite lot size (float or int, not bool).
    """
    if not _validate_ticket(ticket):
        return
    if not _validate_lots(lots):
        return
    with _lock:
        _positions[ticket] = float(lots)


def close_position(ticket) -> None:
    """De-register a closed position.

    Args:
        ticket: Position identifier to remove.
    """
    if not _validate_ticket(ticket):
        return
    with _lock:
        _positions.pop(ticket, None)


def update(ticket, lots) -> None:
    """Alias for open_position()."""
    open_position(ticket, lots)


def is_entry_blocked() -> bool:
    """Return True when total open lots >= MAX_TOTAL_LOTS."""
    with _lock:
        total = sum(_positions.values())
        return total >= MAX_TOTAL_LOTS


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Clear all position state (use between tests or sessions)."""
    with _lock:
        _positions.clear()
