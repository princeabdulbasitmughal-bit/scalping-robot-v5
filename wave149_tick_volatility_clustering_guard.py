"""
wave149_tick_volatility_clustering_guard.py
-------------------------------------------
Guard: Autoregressive Conditional Heteroskedasticity (ARCH) Volatility Clustering Guard

Monitors serial correlation between consecutive squared returns:
    rho = Corr(R_t^2, R_{t-1}^2)
In quiet random-walk regimes, volatility shocks are independent (rho ~= 0.0).
When volatility clustering emerges (rho >= 0.50), high-volatility moves cluster
in continuous bursts (ARCH effect), where trading risks entering into repeated,
self-reinforcing turbulence.

Logic:
- Stores rolling window of WINDOW_SIZE (default: 25) squared fractional returns R_t^2.
- When buffer contains at least MIN_OBSERVATIONS (default: 15) return pairs:
    Computes Pearson correlation coefficient between lagged squared returns.
- If rho >= MAX_VOL_CLUSTERING (default: 0.50) and average return variance >= MIN_MEAN_VARIANCE (1e-8):
    blocks entries for COOLDOWN_SECONDS (default: 60.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Fail-closed: invalid, non-numeric, boolean, NaN, Inf, and non-positive prices ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()                   -> bool
  is_blocked()                         -> bool   (alias)
  record_tick(price, ts=None)          -> None
  update(price, ts=None)               -> None   (alias)
  get_volatility_clustering_corr()     -> float
  reset()                              -> None
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
MIN_OBSERVATIONS: int = 15             # minimum return pairs to evaluate clustering
MAX_VOL_CLUSTERING: float = 0.50       # ARCH clustering correlation threshold
MIN_MEAN_VARIANCE: float = 1e-8        # threshold to avoid triggering on zero-noise ticks
COOLDOWN_SECONDS: float = 60.0         # duration of protective block


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_price: Optional[float] = None
_sq_returns = collections.deque(maxlen=WINDOW_SIZE)
_blocked_until: float = 0.0
_last_clustering_corr: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_tick(price, ts=None) -> None:
    """Record tick price, compute squared return, and evaluate ARCH clustering correlation."""
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return

    curr_p = float(price)

    global _prev_price, _blocked_until, _last_clustering_corr
    with _lock:
        if _prev_price is None:
            _prev_price = curr_p
            return

        r = (curr_p - _prev_price) / _prev_price
        _sq_returns.append(r * r)
        _prev_price = curr_p

        if len(_sq_returns) >= MIN_OBSERVATIONS + 1:
            x = [_sq_returns[i] for i in range(len(_sq_returns) - 1)]
            y = [_sq_returns[i + 1] for i in range(len(_sq_returns) - 1)]
            n = len(x)

            mean_x = sum(x) / n
            mean_y = sum(y) / n

            cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
            var_x = sum((x[i] - mean_x) ** 2 for i in range(n))
            var_y = sum((y[i] - mean_y) ** 2 for i in range(n))

            denom = math.sqrt(var_x * var_y)
            if denom > 1e-12:
                corr = cov / denom
            else:
                corr = 0.0

            _last_clustering_corr = corr

            if corr >= MAX_VOL_CLUSTERING and mean_x >= MIN_MEAN_VARIANCE:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(price, ts=None) -> None:
    """Alias for record_tick()."""
    record_tick(price, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if volatility clustering has triggered protection."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_volatility_clustering_corr() -> float:
    """Return the most recently computed squared return correlation."""
    with _lock:
        return _last_clustering_corr


def reset() -> None:
    """Reset price history, squared return buffer, and active block."""
    global _prev_price, _blocked_until, _last_clustering_corr
    with _lock:
        _prev_price = None
        _sq_returns.clear()
        _blocked_until = 0.0
        _last_clustering_corr = 0.0
