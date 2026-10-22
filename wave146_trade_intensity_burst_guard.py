"""
wave146_trade_intensity_burst_guard.py
--------------------------------------
Guard: Microstructure Trade Arrival Intensity Burst Guard

Monitors transaction fill arrival frequency (trades executed per second) over
sub-second micro-windows. A sudden violent surge in trade frequency indicates
stop-loss liquidation cascades, news-breakout algorithmic cascades, or toxic sweeps.

Logic:
- Records timestamped executed trade transactions.
- Maintains rolling timestamp queue over BURST_WINDOW_SEC (default: 1.0s).
- Computes trade arrival intensity:
    rate = count(trades_in_window) / BURST_WINDOW_SEC
- If rate >= MAX_TRADES_PER_SEC (default: 25.0 trades/sec):
    blocks entries for COOLDOWN_SECONDS (default: 45.0s) to protect against
    queue delays and severe matching-engine slippage.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Fail-closed: invalid, non-numeric, boolean, NaN, Inf, and non-positive values ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()                      -> bool
  is_blocked()                            -> bool   (alias)
  record_trade(price, volume, ts=None)    -> None
  update(price, volume, ts=None)          -> None   (alias)
  get_current_trade_rate()                -> float
  reset()                                 -> None
"""

import collections
import math
import threading
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BURST_WINDOW_SEC: float = 1.0          # rolling window for trade intensity calculation
MAX_TRADES_PER_SEC: float = 25.0       # transaction frequency limit triggering block
COOLDOWN_SECONDS: float = 45.0         # duration of protective block on trade burst


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_timestamps = collections.deque()
_blocked_until: float = 0.0
_last_rate: float = 1.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_trade(price, volume, ts=None) -> None:
    """Record trade transaction and evaluate trade arrival intensity."""
    for val in (price, volume):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return
        if math.isnan(val) or math.isinf(val) or val <= 0.0:
            return

    now = float(ts) if (ts is not None and isinstance(ts, (int, float)) and not isinstance(ts, bool)) else time.monotonic()

    global _blocked_until, _last_rate
    with _lock:
        _timestamps.append(now)

        cutoff = now - BURST_WINDOW_SEC
        while _timestamps and _timestamps[0] < cutoff:
            _timestamps.popleft()

        rate = len(_timestamps) / BURST_WINDOW_SEC
        _last_rate = rate

        if rate >= MAX_TRADES_PER_SEC:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(price, volume, ts=None) -> None:
    """Alias for record_trade()."""
    record_trade(price, volume, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if trade arrival intensity has activated an entry block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_current_trade_rate() -> float:
    """Return the most recently computed trade arrival rate (trades/sec)."""
    with _lock:
        return _last_rate


def reset() -> None:
    """Reset trade timestamps, rate metrics, and active block."""
    global _blocked_until, _last_rate
    with _lock:
        _timestamps.clear()
        _blocked_until = 0.0
        _last_rate = 1.0
