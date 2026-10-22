"""
wave131_cross_market_lead_lag_guard.py
---------------------------------------
Guard: Cross-Asset Lead-Lag Divergence Z-Score Guard

Monitors statistical cointegration and relative divergence between the traded
scalping instrument (Asset A) and its correlated benchmark / lead-lag pair (Asset B).
When divergence between log prices blows out beyond statistical tolerance,
it signals a cross-market regime shock, broken correlation, or liquidity desynchronization.

Logic:
- Records simultaneous price observations for Asset A and Benchmark B.
- Computes log price spread:
    spread = ln(price_a) - ln(price_b)
- Stores spread in a rolling buffer of size WINDOW_SIZE (default: 30 ticks).
- When buffer contains at least MIN_OBSERVATIONS (default: 15):
    mean = sum(spreads) / N
    std = sqrt(sum((s - mean)^2) / (N - 1))
    z_score = abs(current_spread - mean) / std
- If z_score >= MAX_DIVERGENCE_ZSCORE (default: 3.0 standard deviations):
    blocks entries for COOLDOWN_SECONDS (default: 60.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Fail-closed: non-numeric, boolean, NaN, Inf, and non-positive prices ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()                           -> bool
  is_blocked()                                 -> bool   (alias)
  record_prices(price_a, price_b, ts=None)     -> None
  update(price_a, price_b, ts=None)            -> None   (alias)
  get_divergence_zscore()                      -> float
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
WINDOW_SIZE: int = 30                  # rolling observations for spread distribution
MIN_OBSERVATIONS: int = 15             # minimum observations to compute reliable z-score
MAX_DIVERGENCE_ZSCORE: float = 3.0     # divergence threshold in standard deviations
COOLDOWN_SECONDS: float = 60.0         # duration of block on divergence blow-out


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_spreads = collections.deque(maxlen=WINDOW_SIZE)
_blocked_until: float = 0.0
_last_zscore: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_prices(price_a, price_b, ts=None) -> None:
    """Record pair prices and evaluate log spread divergence z-score."""
    for p in (price_a, price_b):
        if isinstance(p, bool) or not isinstance(p, (int, float)):
            return
        if math.isnan(p) or math.isinf(p) or p <= 0.0:
            return

    pa = float(price_a)
    pb = float(price_b)

    global _blocked_until, _last_zscore
    with _lock:
        spread = math.log(pa) - math.log(pb)
        _spreads.append(spread)

        if len(_spreads) >= MIN_OBSERVATIONS:
            n = len(_spreads)
            mean = sum(_spreads) / n
            var = sum((s - mean) ** 2 for s in _spreads) / (n - 1)
            std = math.sqrt(var)

            if std > 1e-9:
                z = abs(spread - mean) / std
                _last_zscore = z
                if z >= MAX_DIVERGENCE_ZSCORE:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(price_a, price_b, ts=None) -> None:
    """Alias for record_prices()."""
    record_prices(price_a, price_b, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if cross-asset divergence is blocking entries."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_divergence_zscore() -> float:
    """Return the most recently computed divergence z-score."""
    with _lock:
        return _last_zscore


def reset() -> None:
    """Reset all spread observations, z-score metrics, and active block."""
    global _blocked_until, _last_zscore
    with _lock:
        _spreads.clear()
        _blocked_until = 0.0
        _last_zscore = 0.0
