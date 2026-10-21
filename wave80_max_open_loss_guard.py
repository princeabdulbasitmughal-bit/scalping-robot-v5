"""
wave80_max_open_loss_guard.py
------------------------------
Blocks new trade entries when any currently open position has an
unrealised floating loss exceeding a configurable threshold (default -25 pips).

Use case: prevents pyramiding into a losing trade when one leg is
already suffering severe drawdown.

Engineering standards:
- threading.RLock() for all shared state
- bool/NaN/Inf guards on all numeric inputs
- Fail-closed: unknown/invalid data defaults to safe (blocked) only
  when there is an active open position in a bad state — no positions
  means NOT blocked (clean slate)
- Ticket IDs: accept int or str (float/bool/None rejected)
- time.monotonic() for cooldown after breach
"""

import math
import threading
import time

_lock = threading.RLock()

# Max tolerated per-position unrealised loss in pips (negative threshold)
_max_open_loss_pips = -25.0
_cooldown_sec = 45.0

# {ticket_id: float}  current floating PnL in pips per open position
_open_positions: dict = {}
_blocked_until: float = 0.0


def _is_valid_ticket(ticket) -> bool:
    if isinstance(ticket, bool):
        return False
    return isinstance(ticket, (int, str))


def _is_valid_pips(v) -> bool:
    if isinstance(v, bool):
        return False
    if not isinstance(v, (int, float)):
        return False
    if math.isnan(v) or math.isinf(v):
        return False
    return True


def update_position(ticket, floating_pnl_pips: float) -> None:
    """
    Register or update the floating PnL (in pips) for an open position.
    Triggers a cooldown block if the loss exceeds the threshold.
    """
    global _blocked_until

    if not _is_valid_ticket(ticket):
        return
    if not _is_valid_pips(floating_pnl_pips):
        return

    key = str(ticket)
    with _lock:
        _open_positions[key] = float(floating_pnl_pips)
        # Check if any position breaches threshold
        if floating_pnl_pips <= _max_open_loss_pips:
            _blocked_until = time.monotonic() + _cooldown_sec


# Alias for wave module convention
update = update_position


def close_position(ticket) -> None:
    """Remove a closed/stopped-out position from tracking."""
    if not _is_valid_ticket(ticket):
        return
    with _lock:
        _open_positions.pop(str(ticket), None)


def is_entry_blocked() -> bool:
    """
    Return True if any open position is in deep floating loss (cooldown active).
    No open positions -> NOT blocked.
    """
    with _lock:
        return time.monotonic() < _blocked_until


# Alias
is_blocked = is_entry_blocked


def get_worst_open_loss() -> float:
    """Return the worst (most negative) floating PnL among open positions, or 0.0."""
    with _lock:
        if not _open_positions:
            return 0.0
        return min(_open_positions.values())


def reset() -> None:
    """Clear all position state and cooldown."""
    global _open_positions, _blocked_until
    with _lock:
        _open_positions = {}
        _blocked_until = 0.0
