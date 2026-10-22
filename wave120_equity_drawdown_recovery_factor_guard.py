"""
wave120_equity_drawdown_recovery_factor_guard.py
--------------------------------------------------
Guard: Drawdown Recovery Stagnation & Giveback Guard

Monitors account equity recovery after a drawdown valley. If an account rebounds
from a drawdown trough but subsequently gives back a major portion of that
recovery before achieving a new high-watermark, this guard triggers to halt
whipsawing in a secondary capitulation leg.

Logic:
- Tracks session equity high-watermark (_hwm) and trough equity during the drawdown (_trough).
- Peak recovery equity (_peak_recovery) is tracked once equity begins rising from the trough.
- If equity gives back >= MAX_RECOVERY_GIVEBACK (default: 0.60, 60% of rebound lost)
  after rebounding at least MIN_REBOUND_USD (default: $30.0), blocks entries for
  COOLDOWN_SECONDS (default: 120.0s).
- New HWM clears trough and recovery state.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()     -> bool
  is_blocked()           -> bool   (alias)
  update(equity)         -> None
  reset()                -> None
"""

import math
import threading
import time

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MIN_REBOUND_USD: float = 30.0           # minimum rebound needed to activate rule
MAX_RECOVERY_GIVEBACK: float = 0.60    # 60% giveback of rebound triggers block
COOLDOWN_SECONDS: float = 120.0        # block duration upon recovery breakdown


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_hwm: float = 0.0
_trough: float = 0.0
_peak_recovery: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update(equity) -> None:
    """Record current equity and monitor drawdown recovery trajectory."""
    if isinstance(equity, bool) or not isinstance(equity, (int, float)):
        return
    if math.isnan(equity) or math.isinf(equity) or equity <= 0.0:
        return

    eq = float(equity)
    now = time.monotonic()

    global _hwm, _trough, _peak_recovery, _blocked_until
    with _lock:
        if _hwm == 0.0:
            _hwm = eq
            _trough = eq
            _peak_recovery = eq
            return

        if eq >= _hwm:
            _hwm = eq
            _trough = eq
            _peak_recovery = eq
            return

        # Currently in drawdown below HWM
        if _trough == 0.0 or eq < _trough:
            _trough = eq
            _peak_recovery = eq
            return

        # Rebounding from trough
        if eq > _peak_recovery:
            _peak_recovery = eq

        rebound_gain = _peak_recovery - _trough
        if rebound_gain >= MIN_REBOUND_USD:
            giveback = (_peak_recovery - eq) / rebound_gain
            if giveback >= MAX_RECOVERY_GIVEBACK:
                _blocked_until = now + COOLDOWN_SECONDS


def is_entry_blocked() -> bool:
    """Return True if recovery giveback has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Reset HWM, trough, and active block."""
    global _hwm, _trough, _peak_recovery, _blocked_until
    with _lock:
        _hwm = 0.0
        _trough = 0.0
        _peak_recovery = 0.0
        _blocked_until = 0.0
