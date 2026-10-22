"""
wave170_realized_semivariance_downside_drag_guard.py
---------------------------------------------------
Guard: Realized Semi-Variance Downside Drag & Tail Risk Asymmetry Guard

Decomposes high-frequency realized return variance into upside vs downside realized semivariance
(Barndorff-Nielsen, Kinnebrock, Shephard, 2010):
    r_t = ln(P_t / P_{t-1})
    RS^+ = sum_{r_i > 0} r_i^2  (upside continuous variance)
    RS^- = sum_{r_i < 0} r_i^2  (downside semi-variance / crash risk)
    Downside Ratio Q^- = RS^- / (RS^+ + RS^-)

Under symmetrical liquid trading, upside and downside semivariance are roughly equal (Q^- ~ 0.50).
During asymmetric liquidation cascades or panic flash crashes, downside semivariance RS^-
monopolizes total volatility (Q^- >= MAX_DOWNSIDE_RATIO, default: 0.80). Conversely, during parabolic
melt-up squeezes, Q^- <= MIN_DOWNSIDE_RATIO (default: 0.20).
When asymmetric jump drag occurs alongside significant total volatility (total_vol >= 20 bps),
trade entries are blocked for COOLDOWN_SECONDS (default: 60.0s) to avoid fading a directional cascade.

Logic:
- Records price ticks and computes log returns.
- Maintains rolling window (WINDOW_SIZE = 25 returns).
- Requires at least MIN_SAMPLES = 15 returns.
- Computes RS^+, RS^-, and Downside Ratio Q^-.
- If (Q^- >= 0.80 OR Q^- <= 0.20) AND sqrt(RS^+ + RS^-) >= MIN_REALIZED_VOL (0.0020):
    blocks entries for COOLDOWN_SECONDS (60.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive prices are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_price(price, ts=None)                             -> None
  update(price, ts=None)                                   -> None   (alias)
  get_downside_ratio()                                     -> float
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
MAX_DOWNSIDE_RATIO: float = 0.80   # >= 80% downside semivariance indicates downside tail risk cascade
MIN_DOWNSIDE_RATIO: float = 0.20   # <= 20% downside (>= 80% upside) indicates parabolic melt-up squeeze
MIN_REALIZED_VOL: float = 0.0020   # 20 bps minimum realized volatility to filter out quiet tick noise
WINDOW_SIZE: int = 25              # Rolling window of return observations
MIN_SAMPLES: int = 15              # Minimum returns required before evaluation
COOLDOWN_SECONDS: float = 60.0     # Block duration in seconds on tail risk asymmetry


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_price: Optional[float] = None
_returns: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_latest_downside_ratio: float = 0.50
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_price(price, ts=None) -> None:
    """Record an incoming price tick and calculate upside/downside realized semivariance."""
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return

    p = float(price)

    global _prev_price, _latest_downside_ratio, _blocked_until
    with _lock:
        if _prev_price is None:
            _prev_price = p
            return

        ret = math.log(p / _prev_price)
        _prev_price = p
        _returns.append(ret)

        if len(_returns) < MIN_SAMPLES:
            return

        rs_pos = sum(r ** 2 for r in _returns if r > 0.0)
        rs_neg = sum(r ** 2 for r in _returns if r < 0.0)
        tot_var = rs_pos + rs_neg

        if tot_var <= 1e-12:
            ratio = 0.50
        else:
            ratio = rs_neg / tot_var

        _latest_downside_ratio = ratio
        tot_vol = math.sqrt(tot_var)

        if (ratio >= MAX_DOWNSIDE_RATIO or ratio <= MIN_DOWNSIDE_RATIO) and tot_vol >= MIN_REALIZED_VOL:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(price, ts=None) -> None:
    """Alias for record_price()."""
    record_price(price, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if realized semivariance asymmetry has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_downside_ratio() -> float:
    """Return the most recently calculated downside realized semivariance ratio."""
    with _lock:
        return _latest_downside_ratio


def reset() -> None:
    """Reset price history, returns deque, latest ratio, and active cooldown."""
    global _prev_price, _latest_downside_ratio, _blocked_until
    with _lock:
        _prev_price = None
        _returns.clear()
        _latest_downside_ratio = 0.50
        _blocked_until = 0.0
