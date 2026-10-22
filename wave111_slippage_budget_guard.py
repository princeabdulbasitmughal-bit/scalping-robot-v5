"""
wave111_slippage_budget_guard.py
----------------------------------
Guard: Cumulative Slippage Budget Guard

Monitors aggregate adverse execution slippage across filled orders. When total
adverse slippage exceeds a safety budget, entries are blocked to protect against
toxic order execution, predatory routing, or spread blowing during high-volatility events.

Logic:
- Accumulates adverse execution slippage (in pips) where requested_price vs fill_price
  resulted in an unfavorable price move for the trader.
- If cumulative adverse slippage >= MAX_ADVERSE_SLIPPAGE_PIPS (default: 15.0 pips),
  blocks entries for COOLDOWN_SECONDS (default: 300.0s = 5 minutes).
- Favorable slippage (price improvement) does not inflate adverse slippage (clamped at 0.0).
- Thread-safe: threading.RLock() on all state.
- Cooldown tracked via time.monotonic().

Aliases (required):
  is_entry_blocked()                     -> bool
  is_blocked()                           -> bool   (alias)
  record_slippage(slippage_pips)         -> None
  update(slippage_pips)                  -> None   (alias)
  reset()                                -> None
"""

import math
import threading
import time

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_ADVERSE_SLIPPAGE_PIPS: float = 15.0   # total tolerable adverse slippage (pips)
COOLDOWN_SECONDS: float = 300.0          # block duration upon budget exhaustion


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_cumulative_adverse_pips: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_slippage(slippage_pips) -> None:
    """Record execution slippage in pips. Positive values represent adverse slippage.

    Args:
        slippage_pips: Float/int pips (positive=worse fill, negative=price improvement).
    """
    if isinstance(slippage_pips, bool):
        return
    if not isinstance(slippage_pips, (int, float)):
        return
    if math.isnan(slippage_pips) or math.isinf(slippage_pips):
        return

    adverse = max(0.0, float(slippage_pips))

    global _cumulative_adverse_pips, _blocked_until
    with _lock:
        _cumulative_adverse_pips += adverse
        if _cumulative_adverse_pips >= MAX_ADVERSE_SLIPPAGE_PIPS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(slippage_pips) -> None:
    """Alias for record_slippage()."""
    record_slippage(slippage_pips)


def is_entry_blocked() -> bool:
    """Return True if slippage budget has been exhausted and cooldown is active."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Reset accumulated slippage and clear active cooldown."""
    global _cumulative_adverse_pips, _blocked_until
    with _lock:
        _cumulative_adverse_pips = 0.0
        _blocked_until = 0.0
