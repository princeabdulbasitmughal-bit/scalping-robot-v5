"""
wave88_sharpe_ratio_guard.py
------------------------------
Blocks new entries when the rolling Sharpe ratio of recent trade PnLs
drops below a configurable threshold (default -0.5).

Sharpe = mean(pnl) / std(pnl)

A negative Sharpe with high volatility indicates a risk-adjusted losing
streak. Requires at least min_trades (default 10) before activating.

Engineering standards:
- threading.RLock() for all shared state
- bool/NaN/Inf guards on all PnL inputs
- Fail-closed during warmup (fewer than min_trades)
- If std == 0 (all identical PnLs): Sharpe = +inf if mean > 0, else -inf
- time.monotonic() for cooldown timer
- Rolling deque of PnL floats
"""

import math
import threading
import time
from collections import deque

_lock = threading.RLock()

_window_size = 20
_min_trades  = 10
_sharpe_threshold = -0.5
_cooldown_sec = 90.0

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


def _compute_sharpe(pnls: list) -> float:
    n = len(pnls)
    if n < 2:
        return 0.0
    mean = sum(pnls) / n
    variance = sum((p - mean) ** 2 for p in pnls) / (n - 1)
    std = math.sqrt(variance)
    if std == 0.0:
        return math.inf if mean > 0 else -math.inf
    return mean / std


def record_trade_pnl(pnl: float) -> None:
    """Record a completed trade PnL and update Sharpe state."""
    global _blocked_until

    if not _is_valid_pnl(pnl):
        return

    with _lock:
        _trade_pnls.append(float(pnl))

        if len(_trade_pnls) < _min_trades:
            return

        sharpe = _compute_sharpe(list(_trade_pnls))
        if sharpe < _sharpe_threshold:
            _blocked_until = time.monotonic() + _cooldown_sec


# Alias
update = record_trade_pnl


def is_entry_blocked() -> bool:
    """
    Return True if Sharpe is below threshold (cooldown active),
    or still in warmup phase (fail-closed).
    """
    with _lock:
        if len(_trade_pnls) < _min_trades:
            return True
        return time.monotonic() < _blocked_until


# Alias
is_blocked = is_entry_blocked


def get_sharpe() -> float:
    """Return the current rolling Sharpe ratio, or -999.0 during warmup."""
    with _lock:
        if len(_trade_pnls) < _min_trades:
            return -999.0
        return _compute_sharpe(list(_trade_pnls))


def reset() -> None:
    """Clear all trade history and cooldown."""
    global _blocked_until
    with _lock:
        _trade_pnls.clear()
        _blocked_until = 0.0
