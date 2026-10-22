"""
wave155_hurst_exponent_mean_reversion_guard.py
----------------------------------------------
Guard: Rescaled Range (R/S) Hurst Exponent Regime Transition Guard

Estimates the Hurst Exponent (H) over rolling high-frequency price returns:
    H in (0.0, 1.0)
    H < 0.50: Anti-persistent / mean-reverting (healthy regime for scalping/market-making)
    H ~ 0.50: Geometric Brownian motion (random walk)
    H > 0.50: Persistent / trending momentum

Scalping strategies predicated on mean reversion and spread capture incur severe tail losses
when the market enters a runaway persistent trend (H >= MAX_TREND_HURST, default: 0.75),
as fade orders are steamrolled. Conversely, extreme whiplash noise (H <= MIN_CHOP_HURST, default: 0.20)
causes execution churn and slippage.

Logic:
- Accumulates rolling price ticks (WINDOW_SIZE = 32 ticks).
- Calculates log returns X_t = ln(P_t / P_{t-1}).
- Computes mean-adjusted cumulative deviations Z_t.
- Computes Rescaled Range (R/S) = (max(Z) - min(Z)) / std(X).
- Calculates H = ln(R/S) / ln(N / 2).
- When return variance is degenerate (variance <= 1e-12):
    if mean return is non-zero, classifies as deterministic runaway trend (H = 0.95).
    if mean return is zero, classifies as neutral flat market (H = 0.50).
- Clamps H to [0.05, 0.95].
- If H >= MAX_TREND_HURST (0.75) OR H <= MIN_CHOP_HURST (0.20):
    blocks entries for COOLDOWN_SECONDS (default: 60.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive prices are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_price(price, ts=None)                             -> None
  update(price, ts=None)                                   -> None   (alias)
  get_hurst_exponent()                                     -> float
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
WINDOW_SIZE: int = 32              # Number of price observations in rolling window
MAX_TREND_HURST: float = 0.75      # Persistent trend threshold (steamrolls mean-reversion)
MIN_CHOP_HURST: float = 0.20       # Violent whiplash / extreme anti-persistence threshold
COOLDOWN_SECONDS: float = 60.0     # Block duration in seconds on adverse regime


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prices: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_latest_hurst: float = 0.50
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_price(price, ts=None) -> None:
    """Record an incoming price tick and calculate the Rescaled Range Hurst Exponent."""
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return

    p = float(price)

    global _latest_hurst, _blocked_until
    with _lock:
        _prices.append(p)
        if len(_prices) < WINDOW_SIZE:
            return

        # Calculate log returns
        returns = [math.log(_prices[i] / _prices[i - 1]) for i in range(1, len(_prices))]
        n = len(returns)
        if n < 8:
            return

        mean_r = sum(returns) / n
        variance = sum((r - mean_r) ** 2 for r in returns) / n
        if variance <= 1e-12:
            if abs(mean_r) > 1e-6:
                _latest_hurst = 0.95
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            else:
                _latest_hurst = 0.50
            return

        std_dev = math.sqrt(variance)

        # Cumulative deviations
        cum_dev = 0.0
        z_vals = []
        for r in returns:
            cum_dev += (r - mean_r)
            z_vals.append(cum_dev)

        r_range = max(z_vals) - min(z_vals)
        if r_range <= 1e-12:
            if abs(mean_r) > 1e-6:
                _latest_hurst = 0.95
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            else:
                _latest_hurst = 0.50
            return

        rs = r_range / std_dev
        log_n2 = math.log(float(n) / 2.0)
        if log_n2 <= 1e-6:
            h = 0.50
        else:
            h = math.log(rs) / log_n2

        # Bounding clamp
        h = max(0.05, min(0.95, h))
        _latest_hurst = h

        if h >= MAX_TREND_HURST or h <= MIN_CHOP_HURST:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(price, ts=None) -> None:
    """Alias for record_price()."""
    record_price(price, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if Hurst exponent regime transition has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_hurst_exponent() -> float:
    """Return the latest calculated Hurst exponent."""
    with _lock:
        return _latest_hurst


def reset() -> None:
    """Reset price history, calculated Hurst exponent, and active cooldown."""
    global _latest_hurst, _blocked_until
    with _lock:
        _prices.clear()
        _latest_hurst = 0.50
        _blocked_until = 0.0
