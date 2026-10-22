"""
wave138_kurtosis_fat_tail_guard.py
----------------------------------
Guard: Microstructure Return Kurtosis & Leptokurtic Fat-Tail Shock Guard

Monitors standardized fourth central moment (kurtosis) of micro-tick returns:
    kappa = m_4 / (variance^2)
In normal Gaussian conditions, kurtosis ~= 3.0 (excess kurtosis ~= 0.0).
A surge to extreme leptokurtic levels (kurtosis >= 6.0) indicates heavy-tail
outliers, frequent jump discontinuities, and catastrophic gap risk that violates
scalping stop-loss assumptions.

Logic:
- Records rolling window of WINDOW_SIZE (default: 30) fractional tick returns.
- When buffer contains at least MIN_OBSERVATIONS (default: 15):
    mean = sum(R) / N
    variance = sum((R_i - mean)^2) / (N - 1)
    std = sqrt(variance)
    m4 = sum((R_i - mean)^4) / N
    kurtosis = m4 / (variance^2)  (when variance > 1e-12)
- If kurtosis >= MAX_KURTOSIS (default: 6.0):
    blocks entries for COOLDOWN_SECONDS (default: 60.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Fail-closed: invalid, non-numeric, boolean, NaN, Inf, and non-positive prices ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()             -> bool
  is_blocked()                   -> bool   (alias)
  record_tick(price, ts=None)    -> None
  update(price, ts=None)         -> None   (alias)
  get_current_kurtosis()         -> float
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
MIN_OBSERVATIONS: int = 15             # minimum returns to compute kurtosis
MAX_KURTOSIS: float = 6.0              # kurtosis threshold triggering block (Gaussian is 3.0)
MIN_VARIANCE: float = 1e-12            # floor to prevent zero-variance division
COOLDOWN_SECONDS: float = 60.0         # duration of protective block


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_price: Optional[float] = None
_returns = collections.deque(maxlen=WINDOW_SIZE)
_blocked_until: float = 0.0
_last_kurtosis: float = 3.0            # default to standard Gaussian kurtosis


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_tick(price, ts=None) -> None:
    """Record tick price, compute return, and evaluate distribution kurtosis."""
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return

    curr_p = float(price)

    global _prev_price, _blocked_until, _last_kurtosis
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

            if var > MIN_VARIANCE:
                m4 = sum((x - mean_r) ** 4 for x in _returns) / n
                kurt = m4 / (var ** 2)
            else:
                kurt = 3.0

            _last_kurtosis = kurt

            if kurt >= MAX_KURTOSIS:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(price, ts=None) -> None:
    """Alias for record_tick()."""
    record_tick(price, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if leptokurtic fat-tail shock has triggered protection."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_current_kurtosis() -> float:
    """Return the most recently computed return kurtosis."""
    with _lock:
        return _last_kurtosis


def reset() -> None:
    """Reset price history, return buffer, and active block."""
    global _prev_price, _blocked_until, _last_kurtosis
    with _lock:
        _prev_price = None
        _returns.clear()
        _blocked_until = 0.0
        _last_kurtosis = 3.0
