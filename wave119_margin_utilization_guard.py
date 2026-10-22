"""
wave119_margin_utilization_guard.py
-------------------------------------
Guard: Dynamic Margin Utilization Guard

Enforces a conservative upper ceiling on account leverage by monitoring
the percentage of total equity committed to used margin.

Logic:
- Computes margin utilization = (used_margin / equity) * 100.0 (%).
- If equity <= 0.0 or utilization >= MAX_MARGIN_UTILIZATION_PCT (default: 40.0%),
  blocks entries for COOLDOWN_SECONDS (default: 45.0s).
- Real-time gate: even after cooldown expires, if current utilization remains
  above threshold, entry remains blocked.
- Zero used margin (no open positions) = 0.0% utilization -> not blocked.
- Fail-closed: invalid or non-numeric inputs silently ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()                 -> bool
  is_blocked()                       -> bool   (alias)
  record_margin(used_margin, equity) -> None
  update(used_margin, equity)        -> None   (alias)
  reset()                            -> None
"""

import math
import threading
import time

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_MARGIN_UTILIZATION_PCT: float = 40.0   # 40% maximum allowable used margin
COOLDOWN_SECONDS: float = 45.0             # duration of block on utilization breach


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_used_margin: float = 0.0
_equity: float = 10000.0                   # default healthy initial equity
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate(val) -> bool:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_margin(used_margin, equity) -> None:
    """Record current used margin and equity in account currency."""
    if not _validate(used_margin) or not _validate(equity):
        return
    if used_margin < 0.0:
        return

    um = float(used_margin)
    eq = float(equity)

    global _used_margin, _equity, _blocked_until
    with _lock:
        _used_margin = um
        _equity = eq

        if _equity <= 0.0:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        utilization_pct = (_used_margin / _equity) * 100.0
        if utilization_pct >= MAX_MARGIN_UTILIZATION_PCT:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(used_margin, equity) -> None:
    """Alias for record_margin()."""
    record_margin(used_margin, equity)


def is_entry_blocked() -> bool:
    """Return True if margin utilization exceeds threshold or active cooldown."""
    with _lock:
        if time.monotonic() < _blocked_until:
            return True
        if _equity <= 0.0:
            return True
        utilization_pct = (_used_margin / _equity) * 100.0
        return utilization_pct >= MAX_MARGIN_UTILIZATION_PCT


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Reset margin utilization tracking and clear block."""
    global _used_margin, _equity, _blocked_until
    with _lock:
        _used_margin = 0.0
        _equity = 10000.0
        _blocked_until = 0.0
