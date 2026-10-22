"""
wave169_microstructure_quote_flicker_guard.py
---------------------------------------------
Guard: Best Bid/Offer High-Frequency Quote Flicker & Fleeting Liquidity Guard

Monitors top-of-book quote update velocity to detect quote flickering, phantom liquidity,
and HFT spoofing games at the inside spread:
    Quote Flicker Rate = (N - 1) / (t_latest - t_oldest)  [quote changes per second]

In modern electronic markets, predatory market-making algos rapidly flash bid/ask quotes
that are canceled or altered within milliseconds. Attempting to execute against flickering
quotes results in high order rejection rates, stale fills, and adverse queue positioning.
When the inside quote changes at a rate >= MAX_FLICKER_RATE (default: 25.0 updates/sec across
a rolling window of 20 quote changes), fleeting liquidity is detected,
triggering an entry block for COOLDOWN_SECONDS (default: 45.0s) until top-of-book stability resumes.

Logic:
- Records top-of-book quotes (bid_price, ask_price) and timestamps.
- Validates quote validity (ask > bid > 0, numeric, non-NaN, non-Inf, non-boolean).
- Detects discrete price changes at either the best bid or best ask level.
- Maintains rolling window (WINDOW_SIZE = 20 change timestamps).
- Evaluates update frequency rate in Hertz (updates per second).
- If rate >= MAX_FLICKER_RATE (25.0 changes/sec):
    blocks entries for COOLDOWN_SECONDS (45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: invalid, inverted, or crossed quotes are ignored.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_quote(bid_price, ask_price, ts=None)              -> None
  update(bid_price, ask_price, ts=None)                    -> None   (alias)
  get_flicker_rate()                                       -> float
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
MAX_FLICKER_RATE: float = 25.0     # 25 quote changes per second indicates fleeting quote flickering
WINDOW_SIZE: int = 20              # Lookback window of quote change timestamps
MIN_CHANGES: int = 10              # Minimum quote changes required before evaluation
COOLDOWN_SECONDS: float = 45.0     # Block duration in seconds on quote flicker detection


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_bid: Optional[float] = None
_prev_ask: Optional[float] = None
_change_timestamps: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_latest_rate: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_quote(bid_price, ask_price, ts=None) -> None:
    """Record top-of-book bid and ask prices, evaluating quote flicker rate."""
    for val in (bid_price, ask_price):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return
        if math.isnan(val) or math.isinf(val):
            return

    b = float(bid_price)
    a = float(ask_price)

    if b <= 0.0 or a <= 0.0 or a <= b:
        return

    now = float(ts) if (ts is not None and isinstance(ts, (int, float)) and not isinstance(ts, bool)) else time.monotonic()

    global _prev_bid, _prev_ask, _latest_rate, _blocked_until
    with _lock:
        if _prev_bid is None or _prev_ask is None:
            _prev_bid = b
            _prev_ask = a
            return

        # Check if either bid or ask price changed
        is_change = (abs(b - _prev_bid) > 1e-9) or (abs(a - _prev_ask) > 1e-9)
        _prev_bid = b
        _prev_ask = a

        if not is_change:
            return

        _change_timestamps.append(now)
        if len(_change_timestamps) < MIN_CHANGES:
            return

        elapsed = _change_timestamps[-1] - _change_timestamps[0]
        n_intervals = len(_change_timestamps) - 1

        if elapsed <= 1e-6:
            rate = 100.0  # Ultra-high burst frequency
        else:
            rate = float(n_intervals) / elapsed

        _latest_rate = rate

        if rate >= MAX_FLICKER_RATE:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(bid_price, ask_price, ts=None) -> None:
    """Alias for record_quote()."""
    record_quote(bid_price, ask_price, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if quote flickering has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_flicker_rate() -> float:
    """Return the most recently calculated quote flicker rate (updates/sec)."""
    with _lock:
        return _latest_rate


def reset() -> None:
    """Reset quote state, change history, latest rate, and active cooldown."""
    global _prev_bid, _prev_ask, _latest_rate, _blocked_until
    with _lock:
        _prev_bid = None
        _prev_ask = None
        _change_timestamps.clear()
        _latest_rate = 0.0
        _blocked_until = 0.0
