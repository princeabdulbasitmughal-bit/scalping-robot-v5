"""
wave156_amihud_illiquidity_ratio_guard.py
-----------------------------------------
Guard: Amihud Absolute Return-to-Volume Illiquidity Ratio Guard

Calculates the classic Amihud Illiquidity metric (Amihud, 2002) over high-frequency trade ticks:
    ILLIQ_t = |Return_t| / Volume_t

Amihud ILLIQ directly captures price impact per unit of trading volume without requiring
signed order flow decomposition. Under deep institutional liquidity, large volume transacts
with negligible price impact (ILLIQ near 0.0).
When order book depth evaporates, even tiny trades produce outsized price moves.
If instantaneous or rolling average ILLIQ >= MAX_AMIHUD_ILLIQ (default: 0.0030 / 30 bps per lot),
the market has entered an illiquidity vacuum where entries face prohibitive execution slippage,
triggering an entry block for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Records price return and trade volume.
- Validates inputs (volume > 0, numeric, non-NaN, non-Inf, non-boolean).
- Computes ILLIQ_t = |return| / volume.
- Maintains rolling window (WINDOW_SIZE = 15) of ILLIQ observations.
- If current ILLIQ >= MAX_AMIHUD_ILLIQ (0.0030) OR rolling average >= MAX_AMIHUD_ILLIQ:
    blocks entries for COOLDOWN_SECONDS (45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: invalid or corrupted trade inputs are ignored.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_trade(price_return, volume, ts=None)              -> None
  update(price_return, volume, ts=None)                    -> None   (alias)
  get_amihud_illiq()                                       -> float
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
MAX_AMIHUD_ILLIQ: float = 0.0030   # 30 bps price displacement per lot triggers illiquidity guard
WINDOW_SIZE: int = 15              # Rolling window of recent trade observations
COOLDOWN_SECONDS: float = 45.0     # Block duration in seconds on illiquidity spike


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_history: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_latest_illiq: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_trade(price_return, volume, ts=None) -> None:
    """Record a trade's price return and executed volume, evaluating Amihud illiquidity."""
    for val in (price_return, volume):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return
        if math.isnan(val) or math.isinf(val):
            return

    ret = float(price_return)
    vol = float(volume)

    if vol <= 0.0:
        return

    illiq = abs(ret) / vol

    global _latest_illiq, _blocked_until
    with _lock:
        _latest_illiq = illiq
        _history.append(illiq)

        avg_illiq = sum(_history) / len(_history)
        if illiq >= MAX_AMIHUD_ILLIQ or avg_illiq >= MAX_AMIHUD_ILLIQ:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(price_return, volume, ts=None) -> None:
    """Alias for record_trade()."""
    record_trade(price_return, volume, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if Amihud illiquidity has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_amihud_illiq() -> float:
    """Return the most recently calculated Amihud illiquidity ratio."""
    with _lock:
        return _latest_illiq


def reset() -> None:
    """Reset illiquidity history, latest ratio, and active cooldown."""
    global _latest_illiq, _blocked_until
    with _lock:
        _history.clear()
        _latest_illiq = 0.0
        _blocked_until = 0.0
