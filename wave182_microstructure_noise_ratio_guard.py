"""
wave182_microstructure_noise_ratio_guard.py
--------------------------------------------
Guard: Market Microstructure Noise-to-Signal Ratio Guard

Estimates the high-frequency market microstructure noise-to-signal ratio (NMR) using the
two-time-scale realized variance ratio framework (Bandi & Russell 2006, Zhang et al. 2005):
    NMR = Total_Variance_Dense / max(1e-10, Signal_Variance_Sparse)

Total realized variance observed at ultra-high frequency (1-tick scale) decomposes into true
latent price variation plus market microstructure noise induced by discrete tick bouncing,
inventory control concessions, and order routing latency:
    r_t = ln(P_t / P_{t-1})
    Var_dense = (1 / N) * sum_{t=1}^N r_t^2
    Var_sparse = (1 / (N - k)) * sum_{t=k}^N (ln(P_t / P_{t-k}))^2
    Signal_Variance = Var_sparse / k

Under a pure diffusive random walk without microstructure noise:
    Var_sparse = k * Var_dense  ==>  Signal_Variance = Var_dense  ==>  NMR = 1.0.

In standard liquid markets with moderate bid-ask bounce, NMR fluctuates between 1.0 and 2.5.
When the order book degrades into extreme ping-pong oscillations, quote flickering, or spreads
whipsaw without persistent price direction, dense variance explodes relative to sparse multi-tick
variance:
    NMR >= MAX_NOISE_RATIO (default: 4.50)

In this hyper-noisy regime, technical indicators (e.g. moving averages, RSI, momentum) calculated
on raw ticks generate pure noise signals, causing scalpers to execute into toxic bid-ask bounce.

When the microstructure noise ratio exceeds MAX_NOISE_RATIO, the guard blocks entry orders for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests incoming price ticks.
- Computes log returns: r_t = ln(P_t / P_{t-1}).
- Maintains rolling window of prices (WINDOW_SIZE = 30 prices).
- Requires at least MIN_SAMPLES = 20 prices before evaluation.
- Computes dense 1-tick variance and sparse k-tick subsampled variance (k = SUBSAMPLE_K = 5).
- Evaluates NMR = Var_dense / Signal_Variance.
- If NMR >= MAX_NOISE_RATIO (4.50):
    blocks entries for COOLDOWN_SECONDS (45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive prices are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_price(price, ts=None)                             -> None
  update(price, ts=None)                                   -> None   (alias)
  get_noise_ratio()                                        -> float
  get_status()                                             -> dict
  reset()                                                  -> None
"""

import collections
import math
import threading
import time
from typing import Deque, Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_NOISE_RATIO: float = 4.50         # NMR >= 4.5 indicates extreme microstructure bid-ask noise
WINDOW_SIZE: int = 30                 # Rolling window of price ticks
MIN_SAMPLES: int = 20                 # Minimum ticks required before evaluation
SUBSAMPLE_K: int = 5                  # Sparse subsampling step size
COOLDOWN_SECONDS: float = 45.0        # Block duration on noise ratio surge


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prices: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_latest_noise_ratio: float = 1.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_price(price, ts=None) -> None:
    """Record an incoming price tick and evaluate microstructure noise ratio."""
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return

    p = float(price)

    global _latest_noise_ratio, _blocked_until
    with _lock:
        _prices.append(p)

        if len(_prices) < MIN_SAMPLES:
            return

        prices_list = list(_prices)
        n = len(prices_list)

        # 1. Dense 1-tick returns variance
        dense_sq_sum = 0.0
        for i in range(1, n):
            r = math.log(prices_list[i] / prices_list[i - 1])
            dense_sq_sum += r * r
        dense_var = dense_sq_sum / float(n - 1)

        # 2. Sparse k-tick subsampled returns variance
        sparse_sq_sum = 0.0
        k = SUBSAMPLE_K
        sparse_count = 0
        for i in range(k, n):
            r_k = math.log(prices_list[i] / prices_list[i - k])
            sparse_sq_sum += r_k * r_k
            sparse_count += 1

        if sparse_count > 0:
            sparse_var = sparse_sq_sum / float(sparse_count)
            signal_var = sparse_var / float(k)
        else:
            signal_var = dense_var

        # Compute Noise-to-Signal Ratio
        if signal_var > 1e-12:
            nmr = dense_var / signal_var
        else:
            # If sparse signal variance is essentially 0 while dense variance exists -> infinite noise
            nmr = 10.0 if dense_var > 1e-12 else 1.0

        _latest_noise_ratio = nmr

        if nmr >= MAX_NOISE_RATIO:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(price, ts=None) -> None:
    """Alias for record_price()."""
    record_price(price, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if high microstructure noise ratio has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_noise_ratio() -> float:
    """Return the most recently computed microstructure noise ratio."""
    with _lock:
        return _latest_noise_ratio


def get_status() -> Dict[str, Any]:
    """Return a diagnostic snapshot of the microstructure noise guard state."""
    with _lock:
        now = time.monotonic()
        return {
            "noise_ratio": _latest_noise_ratio,
            "sample_count": len(_prices),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "subsample_k": SUBSAMPLE_K,
            "max_noise_ratio_threshold": MAX_NOISE_RATIO,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset price history, noise ratio, and active blocks."""
    global _latest_noise_ratio, _blocked_until
    with _lock:
        _prices.clear()
        _latest_noise_ratio = 1.0
        _blocked_until = 0.0
