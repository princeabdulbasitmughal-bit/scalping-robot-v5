"""
wave117_volatility_of_volatility_guard.py
-------------------------------------------
Guard: Volatility-of-Volatility (Vol-of-Vol) Shock Guard

Detects erratic regime transitions and volatility clustering shocks by computing
the dispersion (sample standard deviation) of successive volatility estimates.

Logic:
- Maintains a rolling deque of recent realized volatility estimates (e.g., ATR or return std-dev).
- When len(deque) >= MIN_SAMPLES (default: 5), calculates sample std-dev of volatility values.
- If vol_of_vol >= MAX_VOL_OF_VOL (default: 0.0015), blocks entries for COOLDOWN_SECONDS (default: 90.0s).
- Fail-closed on corrupted inputs (ignored).
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()             -> bool
  is_blocked()                   -> bool   (alias)
  record_volatility(vol_metric)  -> None
  update(vol_metric)             -> None   (alias)
  reset()                        -> None
"""

import math
import threading
import time
from collections import deque

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 15              # rolling window of volatility metrics
MIN_SAMPLES: int = 5               # minimum samples required before evaluation
MAX_VOL_OF_VOL: float = 0.0015     # maximum acceptable std-dev of volatility
COOLDOWN_SECONDS: float = 90.0     # duration of block on vol-of-vol spike


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_vol_estimates: deque = deque(maxlen=WINDOW_SIZE)
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _calc_std(samples) -> float:
    n = len(samples)
    if n < 2:
        return 0.0
    mean = sum(samples) / n
    var = sum((x - mean) ** 2 for x in samples) / (n - 1)
    return math.sqrt(var)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_volatility(vol_metric) -> None:
    """Record a volatility metric (e.g. ATR, tick return std-dev)."""
    if isinstance(vol_metric, bool):
        return
    if not isinstance(vol_metric, (int, float)):
        return
    if math.isnan(vol_metric) or math.isinf(vol_metric) or vol_metric < 0.0:
        return

    v = float(vol_metric)

    global _blocked_until
    with _lock:
        _vol_estimates.append(v)
        if len(_vol_estimates) >= MIN_SAMPLES:
            vol_of_vol = _calc_std(_vol_estimates)
            if vol_of_vol >= MAX_VOL_OF_VOL:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(vol_metric) -> None:
    """Alias for record_volatility()."""
    record_volatility(vol_metric)


def is_entry_blocked() -> bool:
    """Return True if vol-of-vol shock has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Clear recorded volatility estimates and active block."""
    global _blocked_until
    with _lock:
        _vol_estimates.clear()
        _blocked_until = 0.0
