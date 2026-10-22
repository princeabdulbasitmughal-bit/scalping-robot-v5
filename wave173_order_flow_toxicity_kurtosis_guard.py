"""
wave173_order_flow_toxicity_kurtosis_guard.py
---------------------------------------------
Guard: Order Flow Volume Leptokurtic Fat-Tail Kurtosis Guard

Measures institutional order flow fat-tail concentration via sample excess kurtosis of trade volumes:
    Kurt_excess = ( (1 / N) * sum (Volume_i - mean_V)^4 ) / (std_V^4) - 3.0

In regular retail trading environments, trade volumes follow a moderately dispersed distribution
with well-behaved tails (Kurtosis ~ 0.0 to 2.0).
When toxic institutional block traders or predator sweep algorithms execute massive whale sizes
disguised among small retail order flow, the volume distribution becomes extremely leptokurtic
(Kurtosis >= MAX_KURTOSIS, default: 6.0).
These extreme volume outliers indicate that institutional orders are exhausting the available
liquidity book, triggering an entry block for COOLDOWN_SECONDS (default: 60.0s).

Logic:
- Records trade volumes (volume > 0).
- Maintains rolling window (WINDOW_SIZE = 25 trade volumes).
- Requires at least MIN_SAMPLES = 15 volumes before evaluation.
- Computes sample excess kurtosis.
- If Kurt_excess >= MAX_KURTOSIS (6.0):
    blocks entries for COOLDOWN_SECONDS (60.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive volumes are ignored.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_volume(volume, ts=None)                           -> None
  update(volume, ts=None)                                  -> None   (alias)
  get_volume_kurtosis()                                    -> float
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
MAX_KURTOSIS: float = 6.0          # Excess kurtosis >= 6.0 indicates extreme leptokurtic volume fat-tails
WINDOW_SIZE: int = 25              # Rolling window of volume observations
MIN_SAMPLES: int = 15              # Minimum samples required before evaluation
COOLDOWN_SECONDS: float = 60.0     # Block duration in seconds on fat-tail volume shock


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_volumes: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_latest_kurtosis: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_volume(volume, ts=None) -> None:
    """Record an incoming trade volume and update volume excess kurtosis."""
    if isinstance(volume, bool) or not isinstance(volume, (int, float)):
        return
    if math.isnan(volume) or math.isinf(volume) or volume <= 0.0:
        return

    v = float(volume)

    global _latest_kurtosis, _blocked_until
    with _lock:
        _volumes.append(v)
        if len(_volumes) < MIN_SAMPLES:
            return

        n = len(_volumes)
        mean_v = sum(_volumes) / n
        var_v = sum((x - mean_v) ** 2 for x in _volumes) / n

        if var_v <= 1e-12:
            kurt = 0.0
        else:
            m4 = sum((x - mean_v) ** 4 for x in _volumes) / n
            kurt = (m4 / (var_v ** 2)) - 3.0

        _latest_kurtosis = kurt

        if kurt >= MAX_KURTOSIS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(volume, ts=None) -> None:
    """Alias for record_volume()."""
    record_volume(volume, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if volume kurtosis fat-tail shock has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_volume_kurtosis() -> float:
    """Return the most recently calculated trade volume excess kurtosis."""
    with _lock:
        return _latest_kurtosis


def reset() -> None:
    """Reset volume history, latest kurtosis, and active cooldown."""
    global _latest_kurtosis, _blocked_until
    with _lock:
        _volumes.clear()
        _latest_kurtosis = 0.0
        _blocked_until = 0.0
