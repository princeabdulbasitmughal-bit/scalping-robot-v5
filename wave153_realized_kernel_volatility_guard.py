"""
wave153_realized_kernel_volatility_guard.py
-------------------------------------------
Guard: Non-Parametric Realized Kernel Volatility Jump Guard

Computes microstructure-noise-robust realized kernel volatility (Barndorff-Nielsen et al., 2008)
using a Bartlett-weighted autocovariance kernel over high-frequency tick returns:
    r_t = ln(P_t / P_{t-1})
    gamma_h = (1/N) * sum_{t=h+1}^N (r_t - r_mean) * (r_{t-h} - r_mean)
    RK_var = max(0.0, gamma_0 + 2 * sum_{h=1}^H (1 - h / (H + 1)) * gamma_h)
    sigma_RK = sqrt(RK_var)

Standard realized variance is corrupted by high-frequency bid-ask bounce and discrete rounding.
The Realized Kernel averages out microstructure friction to extract the true underlying price
jump continuous volatility. When sigma_RK spikes above MAX_RK_VOL (default: 0.0050 / 50 bps),
it detects true systemic price turbulence, blocking trade entries to prevent toxic fill execution.

Logic:
- Records price ticks into a rolling window (WINDOW_SIZE = 20 ticks).
- Calculates log returns r_t.
- Computes sample autocovariances gamma_h up to lag H = 3 with Bartlett kernel weights.
- Calculates noise-corrected volatility sigma_RK.
- If sigma_RK >= MAX_RK_VOL (0.0050):
    blocks entries for COOLDOWN_SECONDS (default: 60.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive prices are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_price(price, ts=None)                             -> None
  update(price, ts=None)                                   -> None   (alias)
  get_realized_kernel_vol()                                -> float
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
WINDOW_SIZE: int = 20              # Number of returns in rolling evaluation window
MAX_LAG_H: int = 3                 # Maximum autocovariance lag for Bartlett kernel
MAX_RK_VOL: float = 0.0050         # 50 bps noise-robust realized kernel volatility tripwire
COOLDOWN_SECONDS: float = 60.0     # Block duration in seconds on volatility burst


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prices: Deque[float] = collections.deque(maxlen=WINDOW_SIZE + 1)
_latest_rk_vol: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_price(price, ts=None) -> None:
    """Record an incoming price tick and calculate realized kernel volatility."""
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return

    p = float(price)

    global _latest_rk_vol, _blocked_until
    with _lock:
        _prices.append(p)
        if len(_prices) < MAX_LAG_H + 5:
            return

        # Calculate log returns
        returns = [math.log(_prices[i] / _prices[i - 1]) for i in range(1, len(_prices))]
        n = len(returns)
        if n < MAX_LAG_H + 2:
            return

        mean_r = sum(returns) / n

        # gamma_0 (variance)
        gamma_0 = sum((r - mean_r) ** 2 for r in returns) / n

        # Autocovariances with Bartlett kernel weights: k(h / (H + 1)) = 1 - h / (H + 1)
        kernel_sum = 0.0
        h_max = min(MAX_LAG_H, n - 2)
        for h in range(1, h_max + 1):
            gamma_h = sum((returns[t] - mean_r) * (returns[t - h] - mean_r) for t in range(h, n)) / n
            weight = 1.0 - (float(h) / float(h_max + 1))
            kernel_sum += 2.0 * weight * gamma_h

        rk_var = max(0.0, gamma_0 + kernel_sum)
        rk_vol = math.sqrt(rk_var)
        _latest_rk_vol = rk_vol

        if rk_vol >= MAX_RK_VOL:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(price, ts=None) -> None:
    """Alias for record_price()."""
    record_price(price, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if realized kernel volatility has triggered an active cooldown."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_realized_kernel_vol() -> float:
    """Return the latest noise-robust realized kernel volatility."""
    with _lock:
        return _latest_rk_vol


def reset() -> None:
    """Reset price history, calculated volatility, and active cooldown."""
    global _latest_rk_vol, _blocked_until
    with _lock:
        _prices.clear()
        _latest_rk_vol = 0.0
        _blocked_until = 0.0
