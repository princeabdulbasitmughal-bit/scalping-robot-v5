"""
wave143_directional_volatility_ratio_guard.py
---------------------------------------------
Guard: Directional Semi-Variance Volatility Asymmetry Guard

Monitors asymmetry between upside semi-variance and downside semi-variance:
    sigma_+^2 = sum_{R > 0}(R^2)
    sigma_-^2 = sum_{R < 0}(R^2)
    Asymmetry Ratio = max(sigma_+^2 / sigma_-^2, sigma_-^2 / sigma_+^2)
Symmetric continuous markets exhibit balanced semi-variance (ratio ~= 1.0 - 2.0).
Severe directional asymmetry (ratio >= 4.0x) signals aggressive one-sided cascades:
either panic selling (downside dominance) or runaway short squeeze (upside dominance).

Logic:
- Records rolling window of WINDOW_SIZE (default: 25) fractional tick returns.
- When buffer contains at least MIN_OBSERVATIONS (default: 15):
    Evaluates upside and downside semi-variance.
    Computes ratio = max(up_var / down_var, down_var / up_var).
- If ratio >= MAX_ASYMMETRY_RATIO (default: 4.0x) and total variance >= MIN_TOTAL_VARIANCE (1e-8):
    blocks entries for COOLDOWN_SECONDS (default: 60.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Fail-closed: invalid, non-numeric, boolean, NaN, Inf, and non-positive prices ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()                      -> bool
  is_blocked()                            -> bool   (alias)
  record_tick(price, ts=None)             -> None
  update(price, ts=None)                  -> None   (alias)
  get_volatility_asymmetry_ratio()        -> float
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
WINDOW_SIZE: int = 25                  # rolling returns buffer size
MIN_OBSERVATIONS: int = 15             # minimum returns to evaluate asymmetry
MAX_ASYMMETRY_RATIO: float = 4.0       # 4.0x variance asymmetry triggers block
MIN_TOTAL_VARIANCE: float = 1e-8       # minimum return variance to evaluate ratio
COOLDOWN_SECONDS: float = 60.0         # duration of protective block


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_price: Optional[float] = None
_returns = collections.deque(maxlen=WINDOW_SIZE)
_blocked_until: float = 0.0
_last_ratio: float = 1.0               # default to balanced symmetric variance


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_tick(price, ts=None) -> None:
    """Record tick price, compute return, and evaluate directional semi-variance ratio."""
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return

    curr_p = float(price)

    global _prev_price, _blocked_until, _last_ratio
    with _lock:
        if _prev_price is None:
            _prev_price = curr_p
            return

        r = (curr_p - _prev_price) / _prev_price
        _returns.append(r)
        _prev_price = curr_p

        if len(_returns) >= MIN_OBSERVATIONS:
            up_sq = sum(x * x for x in _returns if x > 0.0)
            down_sq = sum(x * x for x in _returns if x < 0.0)
            total_var = up_sq + down_sq

            if total_var >= MIN_TOTAL_VARIANCE:
                if up_sq <= 1e-12 and down_sq > 0.0:
                    ratio = 100.0
                elif down_sq <= 1e-12 and up_sq > 0.0:
                    ratio = 100.0
                elif up_sq > 1e-12 and down_sq > 1e-12:
                    ratio = max(up_sq / down_sq, down_sq / up_sq)
                else:
                    ratio = 1.0

                _last_ratio = ratio

                if ratio >= MAX_ASYMMETRY_RATIO:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(price, ts=None) -> None:
    """Alias for record_tick()."""
    record_tick(price, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if directional volatility asymmetry is blocking entries."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_volatility_asymmetry_ratio() -> float:
    """Return the most recently computed semi-variance asymmetry ratio."""
    with _lock:
        return _last_ratio


def reset() -> None:
    """Reset price history, return buffer, and active block."""
    global _prev_price, _blocked_until, _last_ratio
    with _lock:
        _prev_price = None
        _returns.clear()
        _blocked_until = 0.0
        _last_ratio = 1.0
