"""
wave137_skewness_fat_tail_guard.py
-----------------------------------
Guard: Microstructure Return Skewness & Tail Asymmetry Guard

Monitors standardized third moment (skewness) of micro-tick returns.
A sudden extreme positive or negative skewness (|skewness| >= 2.50) indicates
fat-tail asymmetric shocks, flash crashes, or liquidity sweep squeezes where
normal Gaussian inventory risk metrics break down.

Logic:
- Records rolling window of WINDOW_SIZE (default: 30) fractional returns.
- When buffer contains at least MIN_OBSERVATIONS (default: 15):
    mean = sum(R) / N
    variance = sum((R_i - mean)^2) / (N - 1)
    std = sqrt(variance)
    m3 = sum((R_i - mean)^3) / N
    skewness = m3 / (std^3)  (when std > 1e-6)
- If abs(skewness) >= MAX_SKEWNESS (default: 2.50):
    blocks entries for COOLDOWN_SECONDS (default: 60.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Fail-closed: invalid, non-numeric, boolean, NaN, Inf, and non-positive prices ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()             -> bool
  is_blocked()                   -> bool   (alias)
  record_tick(price, ts=None)    -> None
  update(price, ts=None)         -> None   (alias)
  get_current_skewness()         -> float
  reset()                        -> None
"""

import collections
import math
import threading
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 30                  # rolling returns buffer size
MIN_OBSERVATIONS: int = 15             # minimum returns to compute skewness
MAX_SKEWNESS: float = 2.50             # absolute skewness limit triggering block
MIN_VOLATILITY: float = 1e-6           # floor to prevent zero-variance division
COOLDOWN_SECONDS: float = 60.0         # duration of protective block


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_price: Optional[float] = None
_returns = collections.deque(maxlen=WINDOW_SIZE)
_blocked_until: float = 0.0
_last_skewness: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_tick(price, ts=None) -> None:
    """Record tick price, compute return, and evaluate distribution skewness."""
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return

    curr_p = float(price)

    global _prev_price, _blocked_until, _last_skewness
    with _lock:
        if _prev_price is None:
            _prev_price = curr_p
            return

        r = (curr_p - _prev_price) / _prev_price
        _returns.append(r)
        _prev_price = curr_p

        if len(_returns) >= MIN_OBSERVATIONS:
            n = len(_returns)
            mean_r = sum(_returns) / n
            var = sum((x - mean_r) ** 2 for x in _returns) / (n - 1)
            std = math.sqrt(var)

            if std > MIN_VOLATILITY:
                m3 = sum((x - mean_r) ** 3 for x in _returns) / n
                skew = m3 / (std ** 3)
            else:
                skew = 0.0

            _last_skewness = skew

            if abs(skew) >= MAX_SKEWNESS:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(price, ts=None) -> None:
    """Alias for record_tick()."""
    record_tick(price, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if asymmetric return skewness has triggered protection."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_current_skewness() -> float:
    """Return the most recently computed return skewness."""
    with _lock:
        return _last_skewness


def reset() -> None:
    """Reset price history, return buffer, and active block."""
    global _prev_price, _blocked_until, _last_skewness
    with _lock:
        _prev_price = None
        _returns.clear()
        _blocked_until = 0.0
        _last_skewness = 0.0
