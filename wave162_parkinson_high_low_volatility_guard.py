"""
wave162_parkinson_high_low_volatility_guard.py
----------------------------------------------
Guard: Parkinson Extreme-Value Range Volatility Guard

Calculates the classic Parkinson (1980) High-Low range volatility estimator over micro-bars:
    sigma_P^2 = (1 / (4 * ln(2) * N)) * sum_{i=1}^N (ln(High_i / Low_i))^2
    sigma_P = sqrt(sigma_P^2)

Parkinson's volatility estimator is approximately 5x more statistically efficient than standard
close-to-close estimators because it utilizes the continuous diffusion extremes (High and Low),
capturing true geometric Brownian motion range without distortion from discrete close sampling.
When range volatility expands above MAX_PARKINSON_VOL (default: 0.0055 / 55 bps per bar),
it detects violent range expansion that breaches standard scalping risk brackets,
triggering an entry block for COOLDOWN_SECONDS (default: 60.0s).

Logic:
- Records High and Low price extremes for incoming micro-bars.
- Validates boundaries (High >= Low > 0, numeric, non-NaN, non-Inf, non-boolean).
- Computes single-bar squared logarithmic range: (ln(High / Low))^2.
- Maintains rolling window (WINDOW_SIZE = 10 bars).
- Evaluates Parkinson volatility sigma_P.
- If sigma_P >= MAX_PARKINSON_VOL (0.0055):
    blocks entries for COOLDOWN_SECONDS (60.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: invalid or inverted High/Low extremes are ignored.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_bar(high_p, low_p, ts=None)                       -> None
  update(high_p, low_p, ts=None)                           -> None   (alias)
  get_parkinson_vol()                                      -> float
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
MAX_PARKINSON_VOL: float = 0.0055  # 55 bps range volatility per bar triggers burst guard
WINDOW_SIZE: int = 10              # Number of micro-bars in rolling window
COOLDOWN_SECONDS: float = 60.0     # Block duration in seconds on range volatility expansion
_CONST_4LN2: float = 4.0 * math.log(2.0)  # ~2.77258872


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_log_ranges_sq: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_latest_p_vol: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_bar(high_p, low_p, ts=None) -> None:
    """Record High and Low extremes for a micro-bar, evaluating Parkinson volatility."""
    for val in (high_p, low_p):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return
        if math.isnan(val) or math.isinf(val):
            return

    h = float(high_p)
    l = float(low_p)

    if h <= 0.0 or l <= 0.0 or h < l:
        return

    log_range = math.log(h / l)
    sq_range = log_range ** 2

    global _latest_p_vol, _blocked_until
    with _lock:
        _log_ranges_sq.append(sq_range)
        if len(_log_ranges_sq) < 3:
            return

        n = len(_log_ranges_sq)
        var = sum(_log_ranges_sq) / (_CONST_4LN2 * n)
        p_vol = math.sqrt(max(0.0, var))
        _latest_p_vol = p_vol

        if p_vol >= MAX_PARKINSON_VOL:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(high_p, low_p, ts=None) -> None:
    """Alias for record_bar()."""
    record_bar(high_p, low_p, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if Parkinson volatility burst has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_parkinson_vol() -> float:
    """Return the most recently calculated Parkinson range volatility."""
    with _lock:
        return _latest_p_vol


def reset() -> None:
    """Reset range history, latest volatility, and active cooldown."""
    global _latest_p_vol, _blocked_until
    with _lock:
        _log_ranges_sq.clear()
        _latest_p_vol = 0.0
        _blocked_until = 0.0
