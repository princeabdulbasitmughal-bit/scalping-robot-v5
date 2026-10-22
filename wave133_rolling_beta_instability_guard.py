"""
wave133_rolling_beta_instability_guard.py
-----------------------------------------
Guard: Rolling Beta Instability & Factor Sensitivity Shift Guard

Monitors the rolling empirical beta between the scalping asset (Asset A) and
its market factor / benchmark index (Asset B). Severe deviations from equilibrium
beta indicate factor decoupling, structural breaks, or idiosyncratic shock risk.

Logic:
- Records simultaneous price observations for Asset A and Benchmark B.
- Calculates fractional returns:
    R_A = (price_a - prev_a) / prev_a
    R_B = (price_b - prev_b) / prev_b
- Stores returns in rolling buffers of WINDOW_SIZE (default: 20 observations).
- When buffer contains at least MIN_OBSERVATIONS (default: 15):
    cov = sum((R_A - mean_A) * (R_B - mean_B)) / (N - 1)
    var_B = sum((R_B - mean_B)^2) / (N - 1)
    beta = cov / var_B  (when var_B > 1e-12)
- If abs(beta - EQUILIBRIUM_BETA) >= MAX_BETA_DRIFT (default: 1.50 from 1.0):
    blocks entries for COOLDOWN_SECONDS (default: 90.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Fail-closed: non-numeric, boolean, NaN, Inf, and non-positive prices ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()                           -> bool
  is_blocked()                                 -> bool   (alias)
  record_prices(price_a, price_b, ts=None)     -> None
  update(price_a, price_b, ts=None)            -> None   (alias)
  get_current_beta()                           -> float
  reset()                                      -> None
"""

import collections
import math
import threading
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 20                  # rolling observations for covariance calculation
MIN_OBSERVATIONS: int = 15             # minimum observations for reliable beta estimate
EQUILIBRIUM_BETA: float = 1.0          # expected equilibrium factor beta
MAX_BETA_DRIFT: float = 1.50           # maximum permissible deviation from equilibrium
COOLDOWN_SECONDS: float = 90.0         # duration of protective block on factor shock


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_a: Optional[float] = None
_prev_b: Optional[float] = None
_returns_a = collections.deque(maxlen=WINDOW_SIZE)
_returns_b = collections.deque(maxlen=WINDOW_SIZE)
_blocked_until: float = 0.0
_last_beta: float = EQUILIBRIUM_BETA


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_prices(price_a, price_b, ts=None) -> None:
    """Record pair prices and evaluate rolling empirical beta drift."""
    for p in (price_a, price_b):
        if isinstance(p, bool) or not isinstance(p, (int, float)):
            return
        if math.isnan(p) or math.isinf(p) or p <= 0.0:
            return

    pa = float(price_a)
    pb = float(price_b)

    global _prev_a, _prev_b, _blocked_until, _last_beta
    with _lock:
        if _prev_a is None or _prev_b is None:
            _prev_a = pa
            _prev_b = pb
            return

        r_a = (pa - _prev_a) / _prev_a
        r_b = (pb - _prev_b) / _prev_b

        _returns_a.append(r_a)
        _returns_b.append(r_b)

        _prev_a = pa
        _prev_b = pb

        if len(_returns_a) >= MIN_OBSERVATIONS:
            n = len(_returns_a)
            mean_a = sum(_returns_a) / n
            mean_b = sum(_returns_b) / n

            cov = sum((_returns_a[i] - mean_a) * (_returns_b[i] - mean_b) for i in range(n)) / (n - 1)
            var_b = sum((_returns_b[i] - mean_b) ** 2 for i in range(n)) / (n - 1)

            if var_b > 1e-12:
                beta = cov / var_b
                _last_beta = beta
                if abs(beta - EQUILIBRIUM_BETA) >= MAX_BETA_DRIFT:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(price_a, price_b, ts=None) -> None:
    """Alias for record_prices()."""
    record_prices(price_a, price_b, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if rolling beta drift is blocking entries."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_current_beta() -> float:
    """Return the most recently computed empirical beta."""
    with _lock:
        return _last_beta


def reset() -> None:
    """Reset all return buffers, price references, and active block."""
    global _prev_a, _prev_b, _blocked_until, _last_beta
    with _lock:
        _prev_a = None
        _prev_b = None
        _returns_a.clear()
        _returns_b.clear()
        _blocked_until = 0.0
        _last_beta = EQUILIBRIUM_BETA
