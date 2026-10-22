"""
wave164_yang_zhang_drift_independent_volatility_guard.py
--------------------------------------------------------
Guard: Yang-Zhang Drift-Independent Minimum-Variance Volatility Guard

Calculates the Yang-Zhang (2000) historical volatility estimator over micro-bars:
    sigma_YZ^2 = sigma_open^2 + k * sigma_close^2 + (1 - k) * sigma_RS^2
where:
    sigma_open^2 = Var(ln(Open_t / Close_{t-1}))  (inter-bar / gap jump variance)
    sigma_close^2 = Var(ln(Close_t / Open_t))     (intraday open-to-close drift variance)
    sigma_RS^2 = mean(ln(High_t/Close_t)*ln(High_t/Open_t) + ln(Low_t/Close_t)*ln(Low_t/Open_t)) (Rogers-Satchell)
    k = 0.34 / (1.34 + (N + 1) / (N - 1))
    sigma_YZ = sqrt(sigma_YZ^2)

The Yang-Zhang estimator has the lowest theoretical variance among all OHLC volatility estimators
and is strictly independent of both non-zero continuous price drift and opening price jumps.
When unadulterated multi-bar volatility expands above MAX_YZ_VOL (default: 0.0050 / 50 bps per bar),
it detects true systemic diffusion turbulence across both inter-bar gaps and intraday trend excursions,
triggering an entry block for COOLDOWN_SECONDS (default: 60.0s).

Logic:
- Records micro-bars (open, high, low, close).
- Validates OHLC ordering (high >= max(open, close), low <= min(open, close), low > 0).
- Maintains rolling window (WINDOW_SIZE = 10 bars).
- Evaluates Yang-Zhang minimum-variance volatility sigma_YZ.
- If sigma_YZ >= MAX_YZ_VOL (0.0050):
    blocks entries for COOLDOWN_SECONDS (60.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: invalid or corrupted OHLC geometries are ignored.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_bar(open_p, high_p, low_p, close_p, ts=None)      -> None
  update(open_p, high_p, low_p, close_p, ts=None)          -> None   (alias)
  get_yang_zhang_vol()                                     -> float
  reset()                                                  -> None
"""

import collections
import math
import threading
import time
from typing import Deque, Optional, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_YZ_VOL: float = 0.0050         # 50 bps drift-independent volatility triggers burst guard
WINDOW_SIZE: int = 10              # Number of micro-bars in rolling window
COOLDOWN_SECONDS: float = 60.0     # Block duration in seconds on volatility burst


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_bars: Deque[Tuple[float, float, float, float]] = collections.deque(maxlen=WINDOW_SIZE + 1)
_latest_yz_vol: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_bar(open_p, high_p, low_p, close_p, ts=None) -> None:
    """Record an OHLC micro-bar and update the Yang-Zhang volatility estimator."""
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

    global _latest_yz_vol, _blocked_until
    with _lock:
        _bars.append((o, h, l, c))
        if len(_bars) < 4:
            return

        bars = list(_bars)
        m = len(bars) - 1  # number of transitions

        o_terms = []
        c_terms = []
        rs_terms = []

        for i in range(1, len(bars)):
            prev_c = bars[i - 1][3]
            cur_o, cur_h, cur_l, cur_c = bars[i]

            # Overnight jump
            o_terms.append(math.log(cur_o / prev_c))
            # Open to close drift
            c_terms.append(math.log(cur_c / cur_o))
            # Rogers-Satchell component
            rs = (math.log(cur_h / cur_c) * math.log(cur_h / cur_o) +
                  math.log(cur_l / cur_c) * math.log(cur_l / cur_o))
            rs_terms.append(max(0.0, rs))

        # Sample variances
        mean_o = sum(o_terms) / m
        var_o = sum((x - mean_o) ** 2 for x in o_terms) / (m - 1 if m > 1 else 1)

        mean_c = sum(c_terms) / m
        var_c = sum((x - mean_c) ** 2 for x in c_terms) / (m - 1 if m > 1 else 1)

        sigma_rs = sum(rs_terms) / m

        # Weight k
        if m > 1:
            k = 0.34 / (1.34 + float(m + 1) / float(m - 1))
        else:
            k = 0.5

        yz_var = max(0.0, var_o + k * var_c + (1.0 - k) * sigma_rs)
        yz_vol = math.sqrt(yz_var)
        _latest_yz_vol = yz_vol

        if yz_vol >= MAX_YZ_VOL:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(open_p, high_p, low_p, close_p, ts=None) -> None:
    """Alias for record_bar()."""
    record_bar(open_p, high_p, low_p, close_p, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if Yang-Zhang volatility burst has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_yang_zhang_vol() -> float:
    """Return the most recently calculated Yang-Zhang volatility."""
    with _lock:
        return _latest_yz_vol


def reset() -> None:
    """Reset bar history, latest volatility, and active cooldown."""
    global _latest_yz_vol, _blocked_until
    with _lock:
        _bars.clear()
        _latest_yz_vol = 0.0
        _blocked_until = 0.0
