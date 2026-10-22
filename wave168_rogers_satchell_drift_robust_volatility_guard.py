"""
wave168_rogers_satchell_drift_robust_volatility_guard.py
--------------------------------------------------------
Guard: Rogers-Satchell Non-Zero Drift Robust Volatility Guard

Calculates the Rogers-Satchell (1991) historical volatility estimator over micro-bars:
    sigma_RS^2 = (1 / N) * sum_{i=1}^N [ ln(H_i / C_i) * ln(H_i / O_i) + ln(L_i / C_i) * ln(L_i / O_i) ]
    sigma_RS = sqrt(sigma_RS^2)

Unlike classical estimators (e.g. Parkinson or Garman-Klass) which assume zero continuous price drift
and artificially overestimate volatility during strong persistent trends, the Rogers-Satchell estimator
is mathematically derived to remain unbiased in the presence of non-zero drift.
It precisely isolates true non-directional intraday price choppiness and spread dispersion.
When drift-robust volatility expands above MAX_RS_VOL (default: 0.0050 / 50 bps per bar),
it detects violent non-directional turbulence that destroys scalping edge,
triggering an entry block for COOLDOWN_SECONDS (default: 60.0s).

Logic:
- Records micro-bars (open, high, low, close).
- Validates OHLC ordering (high >= max(open, close), low <= min(open, close), low > 0).
- Computes single-bar Rogers-Satchell variance component.
- Maintains rolling window (WINDOW_SIZE = 10 bars).
- Evaluates Rogers-Satchell volatility sigma_RS.
- If sigma_RS >= MAX_RS_VOL (0.0050):
    blocks entries for COOLDOWN_SECONDS (60.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: invalid or corrupted OHLC geometries are ignored.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_bar(open_p, high_p, low_p, close_p, ts=None)      -> None
  update(open_p, high_p, low_p, close_p, ts=None)          -> None   (alias)
  get_rogers_satchell_vol()                                -> float
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
MAX_RS_VOL: float = 0.0050         # 50 bps drift-robust volatility triggers burst guard
WINDOW_SIZE: int = 10              # Number of micro-bars in rolling evaluation window
COOLDOWN_SECONDS: float = 60.0     # Block duration in seconds on volatility burst


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_rs_variances: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_latest_rs_vol: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_bar(open_p, high_p, low_p, close_p, ts=None) -> None:
    """Record an OHLC micro-bar and update the Rogers-Satchell volatility estimator."""
    for val in (open_p, high_p, low_p, close_p):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return
        if math.isnan(val) or math.isinf(val):
            return

    o = float(open_p)
    h = float(high_p)
    l = float(low_p)
    c = float(close_p)

    if o <= 0.0 or h <= 0.0 or l <= 0.0 or c <= 0.0:
        return
    if h < l or h < o or h < c or l > o or l > c:
        return

    # Single-bar Rogers-Satchell variance component
    u = math.log(h / c) * math.log(h / o)
    d = math.log(l / c) * math.log(l / o)
    bar_var = max(0.0, u + d)

    global _latest_rs_vol, _blocked_until
    with _lock:
        _rs_variances.append(bar_var)
        if len(_rs_variances) < 3:
            return

        mean_var = sum(_rs_variances) / len(_rs_variances)
        rs_vol = math.sqrt(mean_var)
        _latest_rs_vol = rs_vol

        if rs_vol >= MAX_RS_VOL:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(open_p, high_p, low_p, close_p, ts=None) -> None:
    """Alias for record_bar()."""
    record_bar(open_p, high_p, low_p, close_p, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if Rogers-Satchell volatility burst has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_rogers_satchell_vol() -> float:
    """Return the most recently calculated Rogers-Satchell volatility."""
    with _lock:
        return _latest_rs_vol


def reset() -> None:
    """Reset bar variance history, latest volatility, and active cooldown."""
    global _latest_rs_vol, _blocked_until
    with _lock:
        _rs_variances.clear()
        _latest_rs_vol = 0.0
        _blocked_until = 0.0
