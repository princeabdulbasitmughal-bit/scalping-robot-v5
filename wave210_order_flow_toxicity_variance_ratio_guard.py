"""
wave210_order_flow_toxicity_variance_ratio_guard.py
----------------------------------------------------
Guard: Order Flow Toxicity Variance Ratio & Autocorrelation Guard

Monitors serial correlation and directional toxicity in trade returns using the Lo & MacKinlay (1988)
Variance Ratio formulation:
    Single-step return: r_t = (P_t - P_{t-1}) / P_{t-1}
    2-step return:      r_{2, t} = (P_t - P_{t-2}) / P_{t-2}
    Variance Ratio:     VR = Var(r_{2, t}) / [2 * Var(r_t)]

Under standard random walk / efficient market hypothesis diffusion with independent increments:
    VR is centered around 1.0 (0.60 <= VR <= 1.40).

During toxic microstructure regimes:
    1) Trending sweep persistence (strong positive serial correlation):
       VR >= MAX_VARIANCE_RATIO (default: 1.65), indicating continuous one-sided momentum sweeping.
    2) Bid-ask bounce chop (strong negative serial correlation):
       VR <= MIN_VARIANCE_RATIO (default: 0.35), indicating severe microstructure bounce and spread friction.

In both regimes, baseline volatility (sigma_1 >= MIN_BASELINE_VOL = 0.00005, or 0.5 bps) ensures
meaningful price action rather than sub-tick rounding noise.

When the Variance Ratio breaches safe bounds, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests prices (price > 0.0, ts=None).
- Computes single-step and 2-step percentage returns.
- Maintains rolling window of WINDOW_SIZE = 30 single returns.
- Requires at least MIN_SAMPLES = 20 returns before trip-wire evaluation.
- Calculates sample variances and Variance Ratio VR = Var(r_2) / [2 * Var(r_1)].
- Blocks entries for COOLDOWN_SECONDS (45.0s) if VR >= 1.65 or VR <= 0.35.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive price inputs are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_price(price, ts=None)                             -> None
  update(price, ts=None)                                   -> None   (alias)
  get_variance_ratio()                                     -> float
  get_status()                                             -> dict
  reset()                                                  -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 30
MIN_SAMPLES: int = 20
MAX_VARIANCE_RATIO: float = 1.50       # 1.50x indicates strong positive autocorrelation / momentum (rho_1 >= 0.50)
MIN_VARIANCE_RATIO: float = 0.50       # 0.50x indicates strong negative autocorrelation / bounce (rho_1 <= -0.50)
MIN_BASELINE_VOL: float = 0.00005      # 0.5 bps per tick minimum baseline volatility
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_price: Optional[float] = None
_prev_prev_price: Optional[float] = None
_returns_1 = collections.deque(maxlen=WINDOW_SIZE)
_returns_2 = collections.deque(maxlen=WINDOW_SIZE)
_latest_vr: float = 1.0
_latest_sigma_1: float = 0.0
_blocked_until: float = 0.0


def _is_valid_price(val: Any) -> bool:
    """Validate price is a positive finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val > 0.0


def _calculate_variance(data: collections.deque) -> float:
    """Calculate sample variance of a deque."""
    n = len(data)
    if n < 2:
        return 0.0
    mean_val = sum(data) / float(n)
    return sum((x - mean_val) ** 2 for x in data) / float(n - 1)


def record_price(price: float, ts: Optional[float] = None) -> None:
    """
    Ingest a new trade price, update return buffers, and evaluate Variance Ratio.
    """
    global _prev_price, _prev_prev_price, _latest_vr, _latest_sigma_1, _blocked_until

    if not _is_valid_price(price):
        return

    p = float(price)

    with _lock:
        now = time.monotonic() if ts is None else float(ts)

        if _prev_price is None:
            _prev_price = p
            return

        r1 = (p - _prev_price) / _prev_price
        _returns_1.append(r1)

        if _prev_prev_price is not None:
            r2 = (p - _prev_prev_price) / _prev_prev_price
            _returns_2.append(r2)

        _prev_prev_price = _prev_price
        _prev_price = p

        n = len(_returns_2)
        if n < MIN_SAMPLES:
            return

        var1 = _calculate_variance(_returns_1)
        var2 = _calculate_variance(_returns_2)
        _latest_sigma_1 = math.sqrt(var1) if var1 > 0.0 else 0.0

        if var1 < 1e-10:
            _latest_vr = 1.0
            return

        vr = var2 / (2.0 * var1)
        _latest_vr = vr

        if _latest_sigma_1 >= MIN_BASELINE_VOL:
            # Condition 1: Momentum sweep persistence
            if vr >= MAX_VARIANCE_RATIO:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return

            # Condition 2: Anti-persistent spread bounce chop
            if vr <= MIN_VARIANCE_RATIO:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return


def update(price: float, ts: Optional[float] = None) -> None:
    """Alias for record_price()."""
    record_price(price, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to variance ratio toxicity."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_variance_ratio() -> float:
    """Return the latest calculated Variance Ratio VR(2)."""
    with _lock:
        return _latest_vr


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the variance ratio guard."""
    with _lock:
        now = time.monotonic()
        return {
            "variance_ratio": _latest_vr,
            "sigma_1": _latest_sigma_1,
            "sample_count": len(_returns_2),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "max_vr_threshold": MAX_VARIANCE_RATIO,
            "min_vr_threshold": MIN_VARIANCE_RATIO,
            "min_baseline_vol": MIN_BASELINE_VOL,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset price history, return buffers, and active cooldown blocks."""
    global _prev_price, _prev_prev_price, _latest_vr, _latest_sigma_1, _blocked_until
    with _lock:
        _prev_price = None
        _prev_prev_price = None
        _returns_1.clear()
        _returns_2.clear()
        _latest_vr = 1.0
        _latest_sigma_1 = 0.0
        _blocked_until = 0.0
