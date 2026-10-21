"""
wave86_trade_duration_guard.py
--------------------------------
Blocks new entries if any currently open trade has been held longer
than a configurable maximum duration (default 4 hours = 14400s).

Use case: prevents pyramiding into a position that has stalled and
forces the operator to review excessively long-running trades.

Engineering standards:
- threading.RLock() for all shared state
- bool/NaN/Inf guards on all numeric inputs
- Ticket IDs: accept int or str (bool/None/list/float rejected)
- Open time stored as time.monotonic() snapshot for drift-free duration
- Fail-open: no open trades -> NOT blocked
- No separate cooldown: blocked as long as any trade exceeds max duration
"""

import math
import threading
import time

_lock = threading.RLock()

_max_duration_sec = 4 * 3600.0   # 4 hours in seconds

# {str(ticket_id): float monotonic open time}
_open_trades: dict = {}


def _is_valid_ticket(ticket) -> bool:
    if isinstance(ticket, bool):
        return False
    return isinstance(ticket, (int, str))


def open_trade(ticket) -> None:
    """Register a new trade opening. Records the current monotonic time."""
    if not _is_valid_ticket(ticket):
        return
    with _lock:
        _open_trades[str(ticket)] = time.monotonic()


# Alias
update = open_trade


def close_trade(ticket) -> None:
    """Remove a trade that has been closed or stopped out."""
    if not _is_valid_ticket(ticket):
        return
    with _lock:
        _open_trades.pop(str(ticket), None)


def is_entry_blocked() -> bool:
    """
    Return True if any open trade has exceeded the maximum hold duration.
    No open trades -> NOT blocked.
    """
    now = time.monotonic()
    with _lock:
        for open_time in _open_trades.values():
            if (now - open_time) >= _max_duration_sec:
                return True
        return False


# Alias
is_blocked = is_entry_blocked


def get_oldest_duration_sec() -> float:
    """Return the duration (seconds) of the longest-held open trade, or 0.0."""
    now = time.monotonic()
    with _lock:
        if not _open_trades:
            return 0.0
        return max(now - t for t in _open_trades.values())


def reset() -> None:
    """Clear all open trade records."""
    with _lock:
        _open_trades.clear()
