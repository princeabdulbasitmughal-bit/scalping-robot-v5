"""
wave99_max_trade_count_guard.py
---------------------------------
Guard: Maximum Concurrent Trade Count Guard

Blocks new entry orders when the number of currently open trades meets or
exceeds a configurable maximum, preventing over-exposure from excessive
simultaneous positions.

Logic:
- Tracks a set of open trade ticket IDs.
- Blocks when len(open_tickets) >= MAX_TRADES (default: 5).
- No cooldown timer — block lifts immediately when trade count drops below
  the threshold (real-time gate, not time-based).
- Fail-closed: non-string/non-int ticket IDs silently rejected.
- Thread-safe: threading.RLock() on all shared state.

Aliases (required):
  is_entry_blocked()        -> bool
  is_blocked()              -> bool   (alias)
  open_trade(ticket)        -> None   (register an opened trade)
  close_trade(ticket)       -> None   (de-register a closed trade)
  update(ticket, is_open)   -> None   (unified update: is_open=True→open, False→close)
  reset()                   -> None
"""

import math
import threading

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_TRADES: int = 5   # maximum concurrent open positions allowed


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_open_tickets: set = set()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_ticket(ticket) -> bool:
    """Accept only non-bool int or non-empty string ticket IDs."""
    if isinstance(ticket, bool):
        return False
    if isinstance(ticket, int):
        return True
    if isinstance(ticket, str) and ticket.strip():
        return True
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def open_trade(ticket) -> None:
    """Register a newly opened trade.

    Args:
        ticket: Unique trade identifier (int or non-empty str).
    """
    if not _validate_ticket(ticket):
        return
    with _lock:
        _open_tickets.add(ticket)


def close_trade(ticket) -> None:
    """De-register a closed trade.

    Args:
        ticket: Trade identifier to remove (int or non-empty str).
    """
    if not _validate_ticket(ticket):
        return
    with _lock:
        _open_tickets.discard(ticket)


def update(ticket, is_open) -> None:
    """Unified update: open or close a trade by ticket.

    Args:
        ticket: Trade identifier.
        is_open: True to register as open; False to de-register.
    """
    if isinstance(is_open, bool):
        pass  # bool is valid here (it IS a boolean flag)
    elif not isinstance(is_open, int):
        return  # reject non-bool, non-int is_open
    if is_open:
        open_trade(ticket)
    else:
        close_trade(ticket)


def is_entry_blocked() -> bool:
    """Return True when the number of open trades meets or exceeds MAX_TRADES."""
    with _lock:
        return len(_open_tickets) >= MAX_TRADES


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Clear all open trade state (use between tests or sessions)."""
    with _lock:
        _open_tickets.clear()
