"""
wave158_garman_klass_volatility_burst_guard.py
----------------------------------------------
Guard: Garman-Klass Extreme-Value Efficient Volatility Burst Guard

Calculates the Garman-Klass (1980) OHLC volatility estimator over high-frequency micro-bars:
    u = ln(High / Low)
    c = ln(Close / Open)
    sigma_GK^2 = 0.5 * u^2 - (2 * ln(2) - 1) * c^2
    sigma_GK = sqrt(mean(sigma_GK^2))

The Garman-Klass estimator is up to 8x more statistically efficient than close-to-close estimators
because it captures intraday high/low extreme excursions and wick extensions that standard close
sampling misses.
When micro-bar range volatility surges above MAX_GK_VOL (default: 0.0060 / 60 bps per bar),
it detects violent wick expansions and stop-hunting cascades that blow through execution thresholds,
triggering an entry block for COOLDOWN_SECONDS (default: 60.0s).

Logic:
- Records micro-bars (open, high, low, close).
- Validates OHLC ordering (high >= max(open, close), low <= min(open, close), low > 0).
- Computes single-bar Garman-Klass variance component.
- Maintains rolling window (WINDOW_SIZE = 10 bars).
- Evaluates rolling root-mean-square Garman-Klass volatility.
- If sigma_GK >= MAX_GK_VOL (0.0060):
    blocks entries for COOLDOWN_SECONDS (60.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or invalid OHLC geometries are ignored.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_bar(open_p, high_p, low_p, close_p, ts=None)      -> None
  update(open_p, high_p, low_p, close_p, ts=None)          -> None   (alias)
  get_garman_klass_vol()                                   -> float
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
MAX_GK_VOL: float = 0.0060         # 60 bps range volatility per bar triggers burst guard
WINDOW_SIZE: int = 10              # Number of micro-bars in evaluation window
COOLDOWN_SECONDS: float = 60.0     # Block duration in seconds on volatility burst
_GK_CONST: float = 2.0 * math.log(2.0) - 1.0  # ~0.38629436


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_variances: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_latest_gk_vol: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_bar(open_p, high_p, low_p, close_p, ts=None) -> None:
    """Record an OHLC micro-bar and update the Garman-Klass volatility estimator."""
    for val in (open_p, high_p, low_p, close_p):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return
        if math.isnan(val) or math.isinf(val):
            return

    o = float(open_p)
    h = float(high_p)
    l = float(low_p)
    c = float(close_p)

    # Validate physical price boundaries
    if o <= 0.0 or h <= 0.0 or l <= 0.0 or c <= 0.0:
        return
    if h < l or h < o or h < c or l > o or l > c:
        return

    # Garman-Klass single-bar variance component
    u = math.log(h / l)
    c_term = math.log(c / o)
    bar_var = max(0.0, 0.5 * (u ** 2) - _GK_CONST * (c_term ** 2))

    global _latest_gk_vol, _blocked_until
    with _lock:
        _variances.append(bar_var)
        if len(_variances) < 3:
            return

        mean_var = sum(_variances) / len(_variances)
        gk_vol = math.sqrt(mean_var)
        _latest_gk_vol = gk_vol

        if gk_vol >= MAX_GK_VOL:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(open_p, high_p, low_p, close_p, ts=None) -> None:
    """Alias for record_bar()."""
    record_bar(open_p, high_p, low_p, close_p, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if Garman-Klass volatility burst has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_garman_klass_vol() -> float:
    """Return the most recently calculated Garman-Klass volatility."""
    with _lock:
        return _latest_gk_vol


def reset() -> None:
    """Reset bar variance history, latest volatility, and active cooldown."""
    global _latest_gk_vol, _blocked_until
    with _lock:
        _variances.clear()
        _latest_gk_vol = 0.0
        _blocked_until = 0.0
