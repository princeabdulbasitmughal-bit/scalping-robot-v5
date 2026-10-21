"""
wave107_account_balance_guard.py
----------------------------------
Guard: Minimum Account Balance Guard

Blocks new entries when the account balance falls below a configurable
minimum threshold, acting as a hard floor to prevent trading on a nearly
depleted account.

Logic:
- On every update(balance), if balance < MIN_BALANCE_USD (default: $500),
  entry is blocked for COOLDOWN_SECONDS (default: 60s).
- Zero or negative balance: immediately triggers block (never unblocked until
  balance recovers above threshold).
- Fail-closed: bool/NaN/Inf inputs silently ignored; no update means no block.
- Thread-safe: threading.RLock() on all shared state.
- Monotonic clock for cooldown.

Aliases (required):
  is_entry_blocked()   -> bool
  is_blocked()         -> bool   (alias)
  update(balance)      -> None
  reset()              -> None
"""

import math
import threading
import time

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MIN_BALANCE_USD: float = 500.0    # minimum acceptable account balance
COOLDOWN_SECONDS: float = 60.0   # block duration after breach


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update(balance) -> None:
    """Record current account balance and block if below minimum.

    Args:
        balance: Current account balance in USD (finite, not bool).
                 Zero/negative values trigger block.
    """
    if isinstance(balance, bool):
        return
    if not isinstance(balance, (int, float)):
        return
    if math.isnan(balance) or math.isinf(balance):
        return

    global _blocked_until
    bal = float(balance)
    with _lock:
        if bal < MIN_BALANCE_USD:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def is_entry_blocked() -> bool:
    """Return True when account balance is below the minimum threshold."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Clear block state (use between tests or sessions)."""
    global _blocked_until
    with _lock:
        _blocked_until = 0.0
