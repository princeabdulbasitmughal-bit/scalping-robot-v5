"""
wave127_adverse_excursion_velocity_guard.py
--------------------------------------------
Guard: Maximum Adverse Excursion (MAE) Velocity Guard

Monitors the velocity of unrealized floating loss expansion. A sudden steep
deterioration in floating open losses indicates an active runaway market move,
cascading stops against our inventory, or severe slippage on active trades.

Logic:
- Records timestamped snapshots of aggregate floating unrealized PnL.
- When floating PnL is negative (in drawdown) and deteriorating:
  loss_deterioration = -(pnl_curr - pnl_prev)
  velocity = loss_deterioration / dt  (USD / second)
- If velocity >= MAX_MAE_VELOCITY_USD_PER_SEC (default: 5.00 USD/s),
  blocks entries for COOLDOWN_SECONDS (default: 90.0s).
- Fail-closed: invalid or non-numeric inputs ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()                    -> bool
  is_blocked()                          -> bool   (alias)
  record_floating_pnl(pnl, ts=None)     -> None
  update(pnl, ts=None)                  -> None   (alias)
  reset()                               -> None
"""

import math
import threading
import time

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_MAE_VELOCITY_USD_PER_SEC: float = 5.00  # $5/sec loss deterioration limit
COOLDOWN_SECONDS: float = 90.0             # duration of block on MAE velocity spike


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_pnl: float = 0.0
_prev_time: float = -1.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_floating_pnl(pnl, ts=None) -> None:
    """Record current floating unrealized PnL and evaluate loss velocity."""
    if isinstance(pnl, bool) or not isinstance(pnl, (int, float)):
        return
    if math.isnan(pnl) or math.isinf(pnl):
        return

    curr_pnl = float(pnl)
    now = float(ts) if (ts is not None and isinstance(ts, (int, float)) and not isinstance(ts, bool)) else time.monotonic()

    global _prev_pnl, _prev_time, _blocked_until
    with _lock:
        if _prev_time < 0.0:
            _prev_pnl = curr_pnl
            _prev_time = now
            return

        dt = now - _prev_time
        if dt > 0.001:
            # Deterioration is positive if curr_pnl is more negative than prev_pnl
            deterioration = _prev_pnl - curr_pnl
            if deterioration > 0.0:
                velocity = deterioration / dt
                if velocity >= MAX_MAE_VELOCITY_USD_PER_SEC:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS

        _prev_pnl = curr_pnl
        _prev_time = now


def update(pnl, ts=None) -> None:
    """Alias for record_floating_pnl()."""
    record_floating_pnl(pnl, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if adverse excursion velocity is blocking entries."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Reset floating PnL tracking and clear active block."""
    global _prev_pnl, _prev_time, _blocked_until
    with _lock:
        _prev_pnl = 0.0
        _prev_time = -1.0
        _blocked_until = 0.0
