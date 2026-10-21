"""
wave87_profit_factor_guard.py
------------------------------
Tracks rolling profit factor (gross_profit / gross_loss) over the
last N completed trades (default N=20). Blocks new entries when the
profit factor drops below a threshold (default 0.8), indicating the
strategy is in a degraded / losing regime.

PF = gross_profit / gross_loss
- PF > 1.0  ->  more gross profit than gross loss (healthy)
- PF < 0.8  ->  strategy is losing significantly (block)
- No losses recorded yet  ->  PF = infinity  ->  NOT blocked
- No wins recorded yet    ->  PF = 0.0       ->  blocked if < threshold

Engineering standards:
- threading.RLock() for all shared state
- bool/NaN/Inf guards on all PnL inputs
- Fail-closed during warmup (fewer than min_trades completed)
- time.monotonic() for cooldown timer
- Rolling deque of (pnl: float) values
"""

import math
import threading
import time
from collections import deque

_lock = threading.RLock()

_window_size = 20           # number of trades in rolling window
_min_trades = 10            # minimum trades before blocking can activate
_pf_threshold = 0.8         # block when profit factor < this
_cooldown_sec = 120.0

_trade_pnls: deque = deque(maxlen=_window_size)
_blocked_until: float = 0.0


def _is_valid_pnl(v) -> bool:
    if isinstance(v, bool):
        return False
    if not isinstance(v, (int, float)):
        return False
    if math.isnan(v) or math.isinf(v):
        return False
    return True


def record_trade_pnl(pnl: float) -> None:
    """Record the realised PnL of a completed trade and update PF."""
    global _blocked_until

    if not _is_valid_pnl(pnl):
        return

    with _lock:
        _trade_pnls.append(float(pnl))

        # Need minimum trades before blocking
        if len(_trade_pnls) < _min_trades:
            return

        gross_profit = sum(p for p in _trade_pnls if p > 0.0)
        gross_loss   = sum(abs(p) for p in _trade_pnls if p < 0.0)

        if gross_loss == 0.0:
            return   # PF = infinity, not blocked

        pf = gross_profit / gross_loss
        if pf < _pf_threshold:
            _blocked_until = time.monotonic() + _cooldown_sec


# Alias
update = record_trade_pnl


def is_entry_blocked() -> bool:
    """
    Return True if profit factor is below threshold (cooldown active)
    or still in warmup (fewer than min_trades recorded).
    Warmup -> fail-closed.
    """
    with _lock:
        if len(_trade_pnls) < _min_trades:
            return True   # fail-closed during warmup
        return time.monotonic() < _blocked_until


# Alias
is_blocked = is_entry_blocked


def get_profit_factor() -> float:
    """
    Return the current rolling profit factor.
    Returns -1.0 during warmup; float('inf') if no losses recorded.
    """
    with _lock:
        if len(_trade_pnls) < _min_trades:
            return -1.0
        gross_profit = sum(p for p in _trade_pnls if p > 0.0)
        gross_loss   = sum(abs(p) for p in _trade_pnls if p < 0.0)
        if gross_loss == 0.0:
            return float("inf")
        return gross_profit / gross_loss


def reset() -> None:
    """Clear all trade history and cooldown."""
    global _blocked_until
    with _lock:
        _trade_pnls.clear()
        _blocked_until = 0.0
