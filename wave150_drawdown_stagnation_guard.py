"""
wave150_drawdown_stagnation_guard.py
------------------------------------
Guard: Account Drawdown Underwater Stagnation & Churn Decay Guard

Monitors continuous duration spent underwater (Equity < High-Water Mark) combined
with active trade churning.
When an account remains trapped underwater for an extended time (MAX_STAGNATION_SECONDS)
while generating multiple trades without setting new equity peaks, it indicates that
the strategy's market edge has dissipated in the current regime, risking death by
commissions and slow inventory erosion.

Logic:
- Records timestamped account equity and trade count.
- When equity >= HWM:
    updates HWM, resets underwater timer to None, resets drawdown trade counter to 0.
- When equity < HWM:
    starts underwater timer if not already active.
    accumulates trades executed during the drawdown.
- If (now - underwater_start) >= MAX_STAGNATION_SECONDS (default: 1800.0s / 30m)
  AND drawdown_trades >= MAX_STAGNATION_TRADES (default: 15 trades):
    blocks entries for COOLDOWN_SECONDS (default: 300.0s / 5m) to halt churning.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Fail-closed: non-numeric, boolean, NaN, and Inf inputs are ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()                                   -> bool
  is_blocked()                                         -> bool   (alias)
  record_equity(equity, trades_count=0, ts=None)       -> None
  update(equity, trades_count=0, ts=None)              -> None   (alias)
  get_underwater_duration()                            -> float
  reset()                                              -> None
"""

import math
import threading
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_STAGNATION_SECONDS: float = 1800.0 # 30 minutes underwater triggers stagnation check
MAX_STAGNATION_TRADES: int = 15        # minimum trades during drawdown to confirm churn
COOLDOWN_SECONDS: float = 300.0        # 5-minute cooling-off period on stagnation break


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_hwm: Optional[float] = None
_underwater_start: Optional[float] = None
_drawdown_trades: int = 0
_current_duration: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_equity(equity, trades_count=0, ts=None) -> None:
    """Record equity and trade increment, evaluate underwater stagnation."""
    if isinstance(equity, bool) or not isinstance(equity, (int, float)):
        return
    if math.isnan(equity) or math.isinf(equity):
        return

    eq = float(equity)
    trades_inc = int(trades_count) if (isinstance(trades_count, int) and not isinstance(trades_count, bool) and trades_count >= 0) else 0
    now = float(ts) if (ts is not None and isinstance(ts, (int, float)) and not isinstance(ts, bool)) else time.monotonic()

    global _hwm, _underwater_start, _drawdown_trades, _current_duration, _blocked_until
    with _lock:
        if _hwm is None:
            _hwm = eq
            _underwater_start = None
            _drawdown_trades = 0
            _current_duration = 0.0
            return

        if eq >= _hwm:
            _hwm = eq
            _underwater_start = None
            _drawdown_trades = 0
            _current_duration = 0.0
        else:
            if _underwater_start is None:
                _underwater_start = now

            _drawdown_trades += trades_inc
            duration = now - _underwater_start
            _current_duration = duration

            if duration >= MAX_STAGNATION_SECONDS and _drawdown_trades >= MAX_STAGNATION_TRADES:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(equity, trades_count=0, ts=None) -> None:
    """Alias for record_equity()."""
    record_equity(equity, trades_count=trades_count, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if drawdown stagnation churn has activated an entry block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_underwater_duration() -> float:
    """Return active underwater duration in seconds (0.0 if at or above HWM)."""
    with _lock:
        return _current_duration


def reset() -> None:
    """Reset HWM, underwater tracking, trade counters, and active block."""
    global _hwm, _underwater_start, _drawdown_trades, _current_duration, _blocked_until
    with _lock:
        _hwm = None
        _underwater_start = None
        _drawdown_trades = 0
        _current_duration = 0.0
        _blocked_until = 0.0
