"""
wave94_open_pnl_threshold_guard.py
------------------------------------
Monitors aggregate floating PnL across all currently open positions.
Blocks new entries when the total unrealised loss exceeds a threshold
(default -$100), preventing further exposure during an active drawdown.

API:
  update_position(ticket, floating_pnl_usd)  -> update per-ticket PnL
  close_position(ticket)                      -> remove closed position
  is_entry_blocked()                          -> check before entry
  get_total_open_pnl()                        -> aggregate floating PnL
  reset()

Engineering standards:
- threading.RLock() for all shared state
- Ticket: int or str; bool/None/list/float rejected
- floating_pnl_usd: finite float; bool/NaN/Inf rejected
- Fail-open: no open positions -> NOT blocked
- time.monotonic() for cooldown after threshold breach
"""

import math
import threading
import time

_lock = threading.RLock()

_loss_threshold_usd = -100.0    # block when total open PnL <= this
_cooldown_sec = 60.0

# {str(ticket): float pnl}
_open_pnls: dict = {}
_blocked_until: float = 0.0


def _is_valid_ticket(t) -> bool:
    if isinstance(t, bool):
        return False
    return isinstance(t, (int, str))


def _is_valid_pnl(v) -> bool:
    if isinstance(v, bool):
        return False
    if not isinstance(v, (int, float)):
        return False
    if math.isnan(v) or math.isinf(v):
        return False
    return True


def update_position(ticket, floating_pnl_usd: float) -> None:
    """Update or register the floating PnL for an open position."""
    global _blocked_until

    if not _is_valid_ticket(ticket) or not _is_valid_pnl(floating_pnl_usd):
        return

    with _lock:
        _open_pnls[str(ticket)] = float(floating_pnl_usd)
        total = sum(_open_pnls.values())
        if total <= _loss_threshold_usd:
            _blocked_until = time.monotonic() + _cooldown_sec


# Alias
update = update_position


def close_position(ticket) -> None:
    """Remove a closed/stopped-out position from tracking."""
    if not _is_valid_ticket(ticket):
        return
    with _lock:
        _open_pnls.pop(str(ticket), None)


def is_entry_blocked() -> bool:
    """
    Return True if aggregate floating loss hits threshold (cooldown active).
    No open positions -> NOT blocked.
    """
    with _lock:
        return time.monotonic() < _blocked_until


# Alias
is_blocked = is_entry_blocked


def get_total_open_pnl() -> float:
    """Return the sum of all floating PnLs. Returns 0.0 with no open positions."""
    with _lock:
        return sum(_open_pnls.values()) if _open_pnls else 0.0


def reset() -> None:
    """Clear all position state and cooldown."""
    global _blocked_until
    with _lock:
        _open_pnls.clear()
        _blocked_until = 0.0
