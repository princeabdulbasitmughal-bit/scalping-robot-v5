"""
wave134_fractal_dimension_guard.py
-----------------------------------
Guard: Microstructure Sevcik Fractal Dimension Guard

Measures the fractal dimension / topological roughness of high-frequency price paths
using the Sevcik normalized metric space estimator.
In balanced liquid markets, price movements exhibit fractal dimension around D ~= 1.4 - 1.5.
When D collapses towards 1.0, price exhibits straight-line runaway momentum (liquidity vacuum).
When D surges towards 2.0, price exhibits hyper-erratic ping-pong noise or spoofing.

Logic:
- Records rolling window of WINDOW_SIZE (default: 20) tick prices.
- When at least MIN_TICKS (default: 15) prices are collected:
    n = len(prices) - 1
    p_min = min(prices), p_max = max(prices)
    If p_max - p_min <= 1e-9:
        D = 1.0 (flat path)
    Else:
        x_i = i / n
        y_i = (prices[i] - p_min) / (p_max - p_min)
        L' = sum(sqrt((x_{i+1} - x_i)^2 + (y_{i+1} - y_i)^2))
        D = 1.0 + ln(L') / ln(2 * n)
- If D < MIN_FRACTAL_DIM (default: 1.15) or D > MAX_FRACTAL_DIM (default: 1.75):
    blocks entries for COOLDOWN_SECONDS (default: 60.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Fail-closed: invalid, non-numeric, boolean, NaN, Inf, and non-positive prices ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()             -> bool
  is_blocked()                   -> bool   (alias)
  record_tick(price, ts=None)    -> None
  update(price, ts=None)         -> None   (alias)
  get_fractal_dimension()        -> float
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
WINDOW_SIZE: int = 20                  # rolling tick buffer size
MIN_TICKS: int = 15                    # minimum prices to evaluate fractal dimension
MIN_FRACTAL_DIM: float = 1.15          # lower boundary (runaway knife move)
MAX_FRACTAL_DIM: float = 1.75          # upper boundary (excessive erratic ping-pong)
COOLDOWN_SECONDS: float = 60.0         # duration of protective block


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prices = collections.deque(maxlen=WINDOW_SIZE)
_blocked_until: float = 0.0
_last_d: float = 1.50                  # default to balanced random walk


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_tick(price, ts=None) -> None:
    """Record tick price and evaluate Sevcik fractal dimension."""
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return

    curr_p = float(price)

    global _blocked_until, _last_d
    with _lock:
        _prices.append(curr_p)

        if len(_prices) >= MIN_TICKS:
            n = len(_prices) - 1
            p_min = min(_prices)
            p_max = max(_prices)
            spread = p_max - p_min

            if spread <= 1e-9:
                dim = 1.0
            else:
                l_prime = 0.0
                inv_n = 1.0 / n
                for i in range(n):
                    dx = inv_n
                    dy = (_prices[i + 1] - _prices[i]) / spread
                    l_prime += math.sqrt(dx * dx + dy * dy)

                if l_prime > 1e-9 and n > 0:
                    dim = 1.0 + math.log(l_prime) / math.log(2.0 * n)
                else:
                    dim = 1.0

            _last_d = dim

            if dim < MIN_FRACTAL_DIM or dim > MAX_FRACTAL_DIM:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(price, ts=None) -> None:
    """Alias for record_tick()."""
    record_tick(price, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if fractal dimension anomaly is blocking entries."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_fractal_dimension() -> float:
    """Return the most recently computed fractal dimension."""
    with _lock:
        return _last_d


def reset() -> None:
    """Reset price history, fractal dimension metrics, and active block."""
    global _blocked_until, _last_d
    with _lock:
        _prices.clear()
        _blocked_until = 0.0
        _last_d = 1.50
