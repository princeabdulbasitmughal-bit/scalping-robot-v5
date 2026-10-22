"""
wave157_relative_volatility_index_guard.py
------------------------------------------
Guard: Dorsey's Relative Volatility Index (RVI) Exhaustion Guard

Calculates the Relative Volatility Index (RVI; Dorsey, 1993) over high-frequency tick prices:
Instead of measuring directional price changes like RSI, RVI measures the direction of
*volatility* by measuring rolling standard deviation on upward ticks versus downward ticks:
    If P_t > P_{t-1}: U_t = StDev(P, 10), D_t = 0
    If P_t < P_{t-1}: U_t = 0, D_t = StDev(P, 10)
    If P_t == P_{t-1}: U_t = 0, D_t = 0
    RVI = 100.0 * (Sum(U, 14) / (Sum(U, 14) + Sum(D, 14)))

Under balanced conditions, RVI oscillates between 35 and 65.
When RVI >= MAX_RVI (default: 85.0), the market is in an extreme parabolic upward volatility surge.
When RVI <= MIN_RVI (default: 15.0), the market is experiencing a one-sided downward volatility waterfall.
Entering mean-reverting scalp trades during these extreme one-sided volatility blowouts results
in immediate adverse fills.
If RVI >= 85.0 or RVI <= 15.0, entries are blocked for COOLDOWN_SECONDS (default: 60.0s).

Logic:
- Records price ticks into a rolling window.
- Computes tick-to-tick direction and short-term price standard deviation (VOL_WINDOW = 10).
- Separates directional volatility components (U, D) over SMOOTH_WINDOW = 14.
- Evaluates RVI in [0.0, 100.0].
- If RVI >= MAX_RVI (85.0) OR RVI <= MIN_RVI (15.0):
    blocks entries for COOLDOWN_SECONDS (60.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive prices are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_price(price, ts=None)                             -> None
  update(price, ts=None)                                   -> None   (alias)
  get_rvi()                                                -> float
  reset()                                                  -> None
"""

import collections
import math
import threading
import time
from typing import Deque, Optional, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
VOL_WINDOW: int = 10               # Lookback window for tick standard deviation
SMOOTH_WINDOW: int = 14            # Lookback window for RVI directional volatility sums
MAX_RVI: float = 85.0              # Extreme upward volatility exhaustion threshold
MIN_RVI: float = 15.0              # Extreme downward volatility capitulation threshold
COOLDOWN_SECONDS: float = 60.0     # Block duration in seconds on extreme volatility regime


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prices: Deque[float] = collections.deque(maxlen=VOL_WINDOW + 2)
_u_history: Deque[float] = collections.deque(maxlen=SMOOTH_WINDOW)
_d_history: Deque[float] = collections.deque(maxlen=SMOOTH_WINDOW)
_latest_rvi: float = 50.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_price(price, ts=None) -> None:
    """Record an incoming price tick and calculate the Relative Volatility Index."""
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return

    p = float(price)

    global _latest_rvi, _blocked_until
    with _lock:
        if len(_prices) > 0:
            prev_price = _prices[-1]
            diff = p - prev_price
        else:
            diff = 0.0

        _prices.append(p)

        if len(_prices) < VOL_WINDOW:
            return

        # Calculate standard deviation over the last VOL_WINDOW prices
        window = list(_prices)[-VOL_WINDOW:]
        n = len(window)
        mean_p = sum(window) / n
        variance = sum((x - mean_p) ** 2 for x in window) / n
        std_p = math.sqrt(variance)

        if diff > 1e-9:
            u = std_p
            d = 0.0
        elif diff < -1e-9:
            u = 0.0
            d = std_p
        else:
            u = 0.0
            d = 0.0

        _u_history.append(u)
        _d_history.append(d)

        if len(_u_history) < SMOOTH_WINDOW:
            return

        sum_u = sum(_u_history)
        sum_d = sum(_d_history)
        total = sum_u + sum_d

        if total <= 1e-9:
            rvi = 50.0
        else:
            rvi = 100.0 * (sum_u / total)

        _latest_rvi = rvi

        if rvi >= MAX_RVI or rvi <= MIN_RVI:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(price, ts=None) -> None:
    """Alias for record_price()."""
    record_price(price, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if extreme RVI volatility exhaustion has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_rvi() -> float:
    """Return the most recently calculated Relative Volatility Index."""
    with _lock:
        return _latest_rvi


def reset() -> None:
    """Reset price history, volatility components, latest RVI, and active cooldown."""
    global _latest_rvi, _blocked_until
    with _lock:
        _prices.clear()
        _u_history.clear()
        _d_history.clear()
        _latest_rvi = 50.0
        _blocked_until = 0.0
