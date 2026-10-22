"""
wave110_quote_staleness_guard.py
----------------------------------
Guard: Quote Staleness Guard

Protects against executing orders during broker feed freezes or WebSocket
disconnections by checking the age of the most recent market quote (bid/ask tick).

Logic:
- Stores monotonic timestamp of last received quote tick via record_quote() or update().
- If elapsed time since last quote > MAX_STALENESS_SECONDS (default: 5.0s),
  entry is blocked.
- Fail-closed before first quote: blocked until at least one valid quote is recorded.
- Real-time gate: lifts immediately as soon as a fresh quote tick arrives.
- Thread-safe: threading.RLock() on all shared state.

Aliases (required):
  is_entry_blocked()              -> bool
  is_blocked()                    -> bool   (alias)
  record_quote(bid=None, ask=None)-> None
  update(bid=None, ask=None)      -> None   (alias)
  reset()                         -> None
"""

import math
import threading
import time

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_STALENESS_SECONDS: float = 5.0   # max tolerable delay between quote ticks


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_last_quote_time: float = -1.0       # -1.0 indicates no quote recorded yet


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_quote(bid=None, ask=None) -> None:
    """Record quote receipt. Optionally validates numeric positive bid/ask."""
    if bid is not None:
        if isinstance(bid, bool) or not isinstance(bid, (int, float)):
            return
        if math.isnan(bid) or math.isinf(bid) or bid <= 0.0:
            return

    if ask is not None:
        if isinstance(ask, bool) or not isinstance(ask, (int, float)):
            return
        if math.isnan(ask) or math.isinf(ask) or ask <= 0.0:
            return

    global _last_quote_time
    with _lock:
        _last_quote_time = time.monotonic()


def update(bid=None, ask=None) -> None:
    """Alias for record_quote()."""
    record_quote(bid=bid, ask=ask)


def is_entry_blocked() -> bool:
    """Return True if no quote has been received or last quote is older than MAX_STALENESS_SECONDS."""
    with _lock:
        if _last_quote_time < 0.0:
            return True   # Fail-closed: uninitialized feed is considered stale
        elapsed = time.monotonic() - _last_quote_time
        return elapsed > MAX_STALENESS_SECONDS


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Reset last quote timestamp (restores uninitialized stale state)."""
    global _last_quote_time
    with _lock:
        _last_quote_time = -1.0
