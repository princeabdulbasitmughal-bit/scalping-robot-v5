"""
wave114_profit_giveback_guard.py
----------------------------------
Guard: Peak Floating Profit Giveback Guard

Protects open gains by monitoring unrealized floating profit. When floating
profit reaches a meaningful positive peak and subsequently gives back a major
portion of that profit, new entries are blocked to prevent compounding exposure
during sharp reversals.

Logic:
- Tracks the peak floating profit observed (_peak_floating_pnl).
- If _peak_floating_pnl >= MIN_PROFIT_TRIGGER_USD (default: 50.0 USD):
  computes giveback ratio: (peak - current) / peak.
- If giveback ratio >= MAX_GIVEBACK_RATIO (default: 0.50, i.e. 50% giveback),
  blocks entries for COOLDOWN_SECONDS (default: 60.0s).
- When floating profit falls to <= 0 or positions are closed, resets peak.
- Thread-safe: threading.RLock() on all shared state.
- Cooldown tracked via time.monotonic().

Aliases (required):
  is_entry_blocked()             -> bool
  is_blocked()                   -> bool   (alias)
  update(floating_pnl)           -> None
  reset()                        -> None
"""

import math
import threading
import time

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MIN_PROFIT_TRIGGER_USD: float = 50.0   # min peak profit before giveback rule activates
MAX_GIVEBACK_RATIO: float = 0.50       # 50% giveback triggers block
COOLDOWN_SECONDS: float = 60.0         # block duration upon giveback breach


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_peak_floating_pnl: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update(floating_pnl) -> None:
    """Record current floating unrealized PnL and evaluate giveback."""
    if isinstance(floating_pnl, bool):
        return
    if not isinstance(floating_pnl, (int, float)):
        return
    if math.isnan(floating_pnl) or math.isinf(floating_pnl):
        return

    pnl = float(floating_pnl)
    now = time.monotonic()

    global _peak_floating_pnl, _blocked_until
    with _lock:
        if pnl <= 0.0:
            _peak_floating_pnl = 0.0
            return

        if pnl > _peak_floating_pnl:
            _peak_floating_pnl = pnl
        elif _peak_floating_pnl >= MIN_PROFIT_TRIGGER_USD:
            giveback = (_peak_floating_pnl - pnl) / _peak_floating_pnl
            if giveback >= MAX_GIVEBACK_RATIO:
                _blocked_until = now + COOLDOWN_SECONDS


def is_entry_blocked() -> bool:
    """Return True if peak profit giveback has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Reset peak floating PnL tracking and active cooldown."""
    global _peak_floating_pnl, _blocked_until
    with _lock:
        _peak_floating_pnl = 0.0
        _blocked_until = 0.0
