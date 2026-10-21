"""
wave95_symbol_exposure_guard.py
---------------------------------
Tracks the number of open positions per symbol. Blocks new entries
on a symbol when the open position count reaches the maximum allowed
(default 2). Prevents over-concentration on a single instrument.

API:
  open_position(symbol, ticket)   -> register new open position
  close_position(symbol, ticket)  -> remove closed position
  is_entry_blocked(symbol)        -> check before entry on that symbol
  get_exposure(symbol)            -> current open count for symbol
  reset()

Engineering standards:
- threading.RLock() for all shared state
- symbol: non-empty str; ticket: int or str (bool rejected)
- Fail-open: unknown symbol -> NOT blocked
- No cooldown needed — purely count-based
- No warmup required
"""

import threading

_lock = threading.RLock()

_max_positions_per_symbol = 2

# {symbol_upper: set of str(ticket)}
_symbol_positions: dict = {}


def _is_valid_symbol(s) -> bool:
    return isinstance(s, str) and len(s.strip()) > 0


def _is_valid_ticket(t) -> bool:
    if isinstance(t, bool):
        return False
    return isinstance(t, (int, str))


def open_position(symbol: str, ticket) -> None:
    """Register a new open position for the given symbol."""
    if not _is_valid_symbol(symbol) or not _is_valid_ticket(ticket):
        return
    key = symbol.strip().upper()
    with _lock:
        if key not in _symbol_positions:
            _symbol_positions[key] = set()
        _symbol_positions[key].add(str(ticket))


# Alias for wave module convention
update = open_position


def close_position(symbol: str, ticket) -> None:
    """Remove a closed position for the given symbol."""
    if not _is_valid_symbol(symbol) or not _is_valid_ticket(ticket):
        return
    key = symbol.strip().upper()
    with _lock:
        if key in _symbol_positions:
            _symbol_positions[key].discard(str(ticket))
            if not _symbol_positions[key]:
                del _symbol_positions[key]


def is_entry_blocked(symbol: str) -> bool:
    """
    Return True if open position count for this symbol >= max.
    Unknown symbol or invalid input -> NOT blocked (fail-open).
    """
    if not _is_valid_symbol(symbol):
        return False
    key = symbol.strip().upper()
    with _lock:
        count = len(_symbol_positions.get(key, set()))
        return count >= _max_positions_per_symbol


# Alias (requires symbol arg; no-arg version defaults to False)
is_blocked = is_entry_blocked


def get_exposure(symbol: str) -> int:
    """Return the number of open positions for the given symbol."""
    if not _is_valid_symbol(symbol):
        return 0
    key = symbol.strip().upper()
    with _lock:
        return len(_symbol_positions.get(key, set()))


def reset() -> None:
    """Clear all position tracking."""
    with _lock:
        _symbol_positions.clear()
