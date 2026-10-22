"""
wave188_trade_size_clustering_power_law_guard.py
-------------------------------------------------
Guard: Institutional Trade Size Power-Law Alpha & Whale Pareto Tail Guard

Estimates the power-law tail index (alpha) of executed trade volumes using Hill's maximum likelihood
estimator (Gabaix et al., Farmer & Lillo):
    alpha_Hill = 1.0 + N * [ sum_{i=1}^N ln(V_i / V_min) ]^(-1)

In healthy, diversified retail and market making liquidity, order sizes follow a thin or moderately
dispersed power-law tail:
    alpha >= 2.50  (finite mean and finite variance regime)

When predatory institutional whale traders, sovereign block desks, or massive iceberg algorithms
dump aggressive block sizes into the book, the volume distribution becomes extremely fat-tailed.
Hill's tail index collapses:
    alpha_Hill <= MIN_POWER_LAW_ALPHA (default: 1.50)

In this sub-exponential regime (alpha <= 1.50), the order size variance is mathematically infinite
or undefined under heavy-tailed Pareto distributions. A single outsized block execution can wipe out
multiple limit order book levels in a millisecond, causing catastrophic adverse selection for scalpers.

When Hill's power-law alpha drops below MIN_POWER_LAW_ALPHA, the guard blocks entry orders for
COOLDOWN_SECONDS (default: 60.0s) until normal retail size distribution returns.

Logic:
- Ingests trade execution volumes (volume > 0.0).
- Filters for trades meeting minimum qualifying size (V >= V_MIN = 1.0 lot).
- Maintains a rolling window of qualifying volumes (WINDOW_SIZE = 25 volumes).
- Requires at least MIN_SAMPLES = 15 volumes before evaluation.
- Identifies V_min = min(V_1, ..., V_N) over the window.
- Computes Hill's estimator: alpha = 1.0 + N / sum(ln(V_i / V_min)).
- If alpha <= MIN_POWER_LAW_ALPHA (1.50):
    blocks entries for COOLDOWN_SECONDS (60.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive volumes are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_trade(volume, ts=None)                            -> None
  update(volume, ts=None)                                  -> None   (alias)
  get_power_law_alpha()                                    -> float
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
MIN_POWER_LAW_ALPHA: float = 1.50     # Alpha <= 1.50 indicates infinite variance whale tail regime
V_MIN: float = 1.0                    # Minimum qualifying trade volume
WINDOW_SIZE: int = 25                 # Rolling window of trade volumes
MIN_SAMPLES: int = 15                 # Minimum samples required before evaluation
COOLDOWN_SECONDS: float = 60.0        # Block duration on whale fat-tail volume surge


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_volumes: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_latest_alpha: float = 3.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_trade(volume, ts=None) -> None:
    """Record an executed trade volume and evaluate Hill's power-law tail index."""
    if isinstance(volume, bool) or not isinstance(volume, (int, float)):
        return
    if math.isnan(volume) or math.isinf(volume) or volume <= 0.0:
        return

    v = float(volume)

    global _latest_alpha, _blocked_until
    with _lock:
        if v >= V_MIN:
            _volumes.append(v)

        if len(_volumes) < MIN_SAMPLES:
            return

        v_list = list(_volumes)
        n = len(v_list)
        v_min_emp = min(v_list)

        # Log ratio sum
        log_sum = sum(math.log(x / v_min_emp) for x in v_list)

        if log_sum > 1e-6:
            alpha = 1.0 + float(n) / log_sum
        else:
            # All volumes identical in window -> thin bounded distribution
            alpha = 10.0

        _latest_alpha = alpha

        if alpha <= MIN_POWER_LAW_ALPHA:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(volume, ts=None) -> None:
    """Alias for record_trade()."""
    record_trade(volume, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if whale power-law fat-tail regime has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_power_law_alpha() -> float:
    """Return the most recently computed Hill's power-law alpha index."""
    with _lock:
        return _latest_alpha


def get_status() -> Dict[str, Any]:
    """Return a diagnostic snapshot of the power-law tail guard state."""
    with _lock:
        now = time.monotonic()
        return {
            "alpha": _latest_alpha,
            "sample_count": len(_volumes),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "min_volume_threshold": V_MIN,
            "min_alpha_threshold": MIN_POWER_LAW_ALPHA,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset volume history, alpha metrics, and active blocks."""
    global _latest_alpha, _blocked_until
    with _lock:
        _volumes.clear()
        _latest_alpha = 3.0
        _blocked_until = 0.0
