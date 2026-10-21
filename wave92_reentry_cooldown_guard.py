"""
wave92_reentry_cooldown_guard.py
---------------------------------
Prevents re-entering the same direction (BUY or SELL) on the same
symbol within a cooldown window after a stop-loss exit.

Use case: avoids "revenge trading" — immediately re-entering a losing
direction after being stopped out.

API:
  record_stop_loss(symbol, direction)  -> call on SL exit
  is_entry_blocked(symbol, direction)  -> call before new entry
  reset()                              -> clear all state

Engineering standards:
- threading.RLock() for all shared state
- symbol: non-empty str; direction: "BUY" or "SELL" (case-insensitive)
- Invalid inputs silently ignored / not blocked
- time.monotonic() for cooldown timer
- No warmup; fail-open (unknown combos not blocked)
"""

import threading
import time

_lock = threading.RLock()

_cooldown_sec = 30.0

# {(symbol_upper, direction_upper): float monotonic unblock time}
_cooldowns: dict = {}


def _is_valid_symbol(s) -> bool:
    return isinstance(s, str) and len(s.strip()) > 0


def _is_valid_direction(d) -> bool:
    return isinstance(d, str) and d.strip().upper() in ("BUY", "SELL")


def record_stop_loss(symbol: str, direction: str) -> None:
    """
    Record a stop-loss exit for the given symbol and direction.
    Starts a cooldown preventing re-entry in the same direction.
    """
    if not _is_valid_symbol(symbol) or not _is_valid_direction(direction):
        return
    key = (symbol.strip().upper(), direction.strip().upper())
    with _lock:
        _cooldowns[key] = time.monotonic() + _cooldown_sec


# Alias
update = record_stop_loss


def is_entry_blocked(symbol: str, direction: str) -> bool:
    """
    Return True if a same-direction re-entry is within the cooldown
    window for this symbol.
    Unknown symbol/direction combinations -> NOT blocked (fail-open).
    Invalid inputs -> NOT blocked (fail-open; caller should validate).
    """
    if not _is_valid_symbol(symbol) or not _is_valid_direction(direction):
        return False
    key = (symbol.strip().upper(), direction.strip().upper())
    with _lock:
        unblock_at = _cooldowns.get(key)
        if unblock_at is None:
            return False
        return time.monotonic() < unblock_at


# Alias (no-arg version for module convention — always False without args)
is_blocked = is_entry_blocked


def get_remaining_cooldown(symbol: str, direction: str) -> float:
    """Return remaining cooldown seconds for a symbol/direction pair, or 0.0."""
    if not _is_valid_symbol(symbol) or not _is_valid_direction(direction):
        return 0.0
    key = (symbol.strip().upper(), direction.strip().upper())
    with _lock:
        unblock_at = _cooldowns.get(key)
        if unblock_at is None:
            return 0.0
        return max(0.0, unblock_at - time.monotonic())


def reset() -> None:
    """Clear all cooldown state."""
    with _lock:
        _cooldowns.clear()
