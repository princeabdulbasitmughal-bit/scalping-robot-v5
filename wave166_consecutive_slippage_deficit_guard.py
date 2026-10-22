"""
wave166_consecutive_slippage_deficit_guard.py
---------------------------------------------
Guard: Multi-Trade Cumulative Slippage Deficit & Toxic Routing Guard

Monitors execution slippage across fills to detect broker bridge latency, B-book dealer markups,
or toxic counterparty routing.
While random execution slippage is normal, consecutive adverse slippage runs (streak >= 4)
or severe cumulative slippage deficit (sum(slippage) >= 0.0030 / 30 bps across 5 trades)
indicates that order execution has degraded into a negative-expectancy regime.
When triggered, trade entries are blocked for COOLDOWN_SECONDS (default: 120.0s / 2m) to allow
broker routing queues to normalize.

Logic:
- Records individual fill slippage (positive value represents adverse loss).
- Evaluates consecutive adverse fill streak.
- Maintains rolling window (WINDOW_SIZE = 5 trades) of execution slippages.
- If streak >= MAX_ADVERSE_STREAK (4 fills) OR rolling cumulative slippage >= MAX_CUMULATIVE_SLIPPAGE (0.0030):
    blocks entries for COOLDOWN_SECONDS (120.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: invalid or non-numeric slippage values are ignored.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_slippage(slippage, is_adverse=True, ts=None)      -> None
  update(slippage, is_adverse=True, ts=None)               -> None   (alias)
  get_cumulative_slippage()                                -> float
  get_adverse_streak()                                     -> int
  reset()                                                  -> None
"""

import collections
import math
import threading
import time
from typing import Deque, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_ADVERSE_STREAK: int = 4        # 4 consecutive fills with adverse slippage trigger routing guard
MAX_CUMULATIVE_SLIPPAGE: float = 0.0030 # 30 bps cumulative slippage deficit over rolling window
WINDOW_SIZE: int = 5               # Rolling window of recent executions
COOLDOWN_SECONDS: float = 120.0    # 2-minute cooling-off period on toxic execution routing


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_streak: int = 0
_history: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_latest_cumulative: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_slippage(slippage, is_adverse=True, ts=None) -> None:
    """Record execution fill slippage, updating streak and cumulative deficit."""
    if isinstance(slippage, bool) or not isinstance(slippage, (int, float)):
        return
    if math.isnan(slippage) or math.isinf(slippage):
        return

    s = float(slippage)
    adverse = bool(is_adverse) if isinstance(is_adverse, bool) else True

    global _streak, _latest_cumulative, _blocked_until
    with _lock:
        if adverse and s > 0.0:
            _streak += 1
            _history.append(s)
        else:
            _streak = 0
            _history.append(-abs(s) if not adverse else 0.0)

        cum_slip = sum(_history)
        _latest_cumulative = cum_slip

        if _streak >= MAX_ADVERSE_STREAK or cum_slip >= MAX_CUMULATIVE_SLIPPAGE:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(slippage, is_adverse=True, ts=None) -> None:
    """Alias for record_slippage()."""
    record_slippage(slippage, is_adverse=is_adverse, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if slippage deficit has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_cumulative_slippage() -> float:
    """Return rolling cumulative slippage deficit."""
    with _lock:
        return _latest_cumulative


def get_adverse_streak() -> int:
    """Return consecutive adverse slippage fill count."""
    with _lock:
        return _streak


def reset() -> None:
    """Reset streak, slippage history, cumulative deficit, and active cooldown."""
    global _streak, _latest_cumulative, _blocked_until
    with _lock:
        _streak = 0
        _history.clear()
        _latest_cumulative = 0.0
        _blocked_until = 0.0
