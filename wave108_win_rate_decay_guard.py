"""
wave108_win_rate_decay_guard.py
---------------------------------
Guard: Rolling Win Rate Decay Guard

Monitors the short-term win rate of completed trades over a rolling window.
When the rolling win rate drops below a minimum threshold, blocks new entries
for a cooldown period to prevent consecutive strategy losses and tilt.

Logic:
- Maintains a rolling deque of last WINDOW_SIZE trade outcomes (1 for win, 0 for loss).
- When len(deque) >= MIN_TRADES_WARMUP (default: 10), computes win rate = wins / total.
- If win_rate < MIN_WIN_RATE (default: 0.35, i.e. 35%), blocks entries for
  COOLDOWN_SECONDS (default: 180.0s).
- Fail-closed on corrupted inputs (ignored, state preserved).
- Thread-safe: threading.RLock() on all state.
- Cooldown tracked via time.monotonic().

Aliases (required):
  is_entry_blocked()        -> bool
  is_blocked()              -> bool   (alias)
  record_trade(pnl)         -> None   (pnl > 0 is win, <= 0 is loss)
  record_outcome(is_win)    -> None   (explicit boolean outcome)
  update(pnl_or_is_win)     -> None   (unified update)
  reset()                   -> None
"""

import math
import threading
import time
from collections import deque

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 20              # rolling window of completed trades
MIN_TRADES_WARMUP: int = 10        # minimum trades before guard can trigger
MIN_WIN_RATE: float = 0.35         # minimum acceptable win rate (35%)
COOLDOWN_SECONDS: float = 180.0    # block duration upon win rate decay


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_outcomes: deque = deque(maxlen=WINDOW_SIZE)
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_outcome(is_win: bool) -> None:
    """Record a trade outcome directly as a boolean (True=win, False=loss)."""
    if not isinstance(is_win, bool):
        return

    global _blocked_until
    with _lock:
        _outcomes.append(1 if is_win else 0)
        if len(_outcomes) >= MIN_TRADES_WARMUP:
            win_rate = sum(_outcomes) / len(_outcomes)
            if win_rate < MIN_WIN_RATE:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def record_trade(pnl) -> None:
    """Record a trade outcome by its PnL (pnl > 0: win, pnl <= 0: loss)."""
    if isinstance(pnl, bool):
        return
    if not isinstance(pnl, (int, float)):
        return
    if math.isnan(pnl) or math.isinf(pnl):
        return

    record_outcome(float(pnl) > 0.0)


def update(pnl_or_is_win) -> None:
    """Unified update: accepts either a numeric PnL or a boolean outcome."""
    if isinstance(pnl_or_is_win, bool):
        record_outcome(pnl_or_is_win)
    elif isinstance(pnl_or_is_win, (int, float)):
        record_trade(pnl_or_is_win)


def is_entry_blocked() -> bool:
    """Return True if the rolling win rate has dropped below MIN_WIN_RATE."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Reset history and clear active cooldown."""
    global _blocked_until
    with _lock:
        _outcomes.clear()
        _blocked_until = 0.0
