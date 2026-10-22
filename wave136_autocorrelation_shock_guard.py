"""
wave136_autocorrelation_shock_guard.py
---------------------------------------
Guard: Lag-1 Tick Return Autocorrelation Shock Guard

Monitors serial correlation between consecutive micro-tick returns:
    rho_1 = Corr(R_t, R_{t-1})
In normal market-making conditions, bid-ask bounce produces mild negative
serial correlation (rho_1 in [-0.35, 0.05]).
Strong positive autocorrelation (rho_1 >= +0.40) signals institutional order
splitting, momentum chasing, and runaway trend persistence.
Hyper-negative autocorrelation (rho_1 <= -0.70) signals ping-pong whipsaw traps.

Logic:
- Stores rolling window of WINDOW_SIZE (default: 25) tick returns R_t = (P_t - P_{t-1}) / P_{t-1}.
- When buffer contains at least MIN_OBSERVATIONS (default: 15) return pairs (R_t, R_{t-1}):
    Computes Pearson correlation coefficient between lagged pairs.
- If rho_1 >= MAX_POSITIVE_AUTOCORR (default: +0.40) OR
  rho_1 <= MIN_NEGATIVE_AUTOCORR (default: -0.70):
    blocks entries for COOLDOWN_SECONDS (default: 45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Fail-closed: invalid, non-numeric, boolean, NaN, Inf, and non-positive prices ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()             -> bool
  is_blocked()                   -> bool   (alias)
  record_tick(price, ts=None)    -> None
  update(price, ts=None)         -> None   (alias)
  get_current_autocorrelation()  -> float
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
WINDOW_SIZE: int = 25                  # rolling returns buffer size
MIN_OBSERVATIONS: int = 15             # minimum return pairs to evaluate autocorrelation
MAX_POSITIVE_AUTOCORR: float = 0.40    # runaway momentum continuation threshold
MIN_NEGATIVE_AUTOCORR: float = -0.70   # extreme ping-pong whipsaw threshold
COOLDOWN_SECONDS: float = 45.0         # duration of protective block


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_price: Optional[float] = None
_returns = collections.deque(maxlen=WINDOW_SIZE)
_blocked_until: float = 0.0
_last_autocorr: float = -0.10          # default to normal mild negative bounce


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_tick(price, ts=None) -> None:
    """Record tick price, compute fractional return, and evaluate lag-1 autocorrelation."""
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return

    curr_p = float(price)

    global _prev_price, _blocked_until, _last_autocorr
    with _lock:
        if _prev_price is None:
            _prev_price = curr_p
            return

        r = (curr_p - _prev_price) / _prev_price
        _returns.append(r)
        _prev_price = curr_p

        if len(_returns) >= MIN_OBSERVATIONS + 1:
            # Construct lag pairs: x = R_{t-1}, y = R_t
            x = [_returns[i] for i in range(len(_returns) - 1)]
            y = [_returns[i + 1] for i in range(len(_returns) - 1)]
            n = len(x)

            mean_x = sum(x) / n
            mean_y = sum(y) / n

            cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
            var_x = sum((x[i] - mean_x) ** 2 for i in range(n))
            var_y = sum((y[i] - mean_y) ** 2 for i in range(n))

            denom = math.sqrt(var_x * var_y)
            if denom > 1e-12:
                rho = cov / denom
            else:
                rho = 0.0

            _last_autocorr = rho

            if rho >= MAX_POSITIVE_AUTOCORR or rho <= MIN_NEGATIVE_AUTOCORR:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(price, ts=None) -> None:
    """Alias for record_tick()."""
    record_tick(price, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if autocorrelation shock has triggered an entry block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_current_autocorrelation() -> float:
    """Return the most recently computed lag-1 autocorrelation coefficient."""
    with _lock:
        return _last_autocorr


def reset() -> None:
    """Reset price history, return buffers, and active block."""
    global _prev_price, _blocked_until, _last_autocorr
    with _lock:
        _prev_price = None
        _returns.clear()
        _blocked_until = 0.0
        _last_autocorr = -0.10
