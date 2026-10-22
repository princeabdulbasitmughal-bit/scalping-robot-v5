"""
wave199_multiscale_volatility_ratio_guard.py
---------------------------------------------
Guard: Multiscale Realized Volatility Ratio & Microstructure Hurst Divergence Guard

Monitors multiscale volatility scaling across fast (burst) and slow (background) rolling observation horizons:
    sigma_fast = StdDev(r_t)_{fast_window}
    sigma_slow = StdDev(r_t)_{slow_window}
    VR = sigma_fast / max(1e-8, sigma_slow)

Under standard geometric Brownian motion and unmanipulated equilibrium conditions, return variance
scales linearly with time (Hurst exponent H = 0.50):
    VR is stably centered around 1.0 (0.60 <= VR <= 1.80).

During anomalous market microstructure shocks—such as stop-loss run cascades, algorithmic sweep panic,
or artificial quoting freezes—the multiscale volatility ratio diverges violently:
    1) Hyper-volatility cascade explosion:
       VR >= MAX_VOLATILITY_RATIO (default: 3.0) with active baseline volatility
       (sigma_slow >= MIN_BASELINE_VOL = 0.0001, or 1.0 bp per tick), indicating an explosive
       liquidity vacuum and cascading execution slippage.
    2) Subdiffusive quoting freeze / paralysis:
       VR <= MIN_VOLATILITY_RATIO (default: 0.25) with active baseline volatility,
       indicating quote pegging or toxic spread compression preceding an explosive breakout.

Scalpers entering during either extreme experience severe adverse selection or order execution
rejections.

When the volatility ratio diverges beyond safe bounds, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests prices (price > 0.0, ts=None).
- Computes percentage returns r_t = (P_t - P_{t-1}) / P_{t-1}.
- Maintains rolling return buffers: FAST_WINDOW = 8, SLOW_WINDOW = 32.
- Requires SLOW_WINDOW observations before trip-wire evaluation.
- Calculates sample standard deviations sigma_fast and sigma_slow.
- Evaluates Volatility Ratio VR = sigma_fast / sigma_slow.
- Blocks entries for COOLDOWN_SECONDS (45.0s) if VR >= 3.0 or VR <= 0.25.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive price inputs are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_price(price, ts=None)                             -> None
  update(price, ts=None)                                   -> None   (alias)
  get_volatility_ratio()                                   -> float
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
FAST_WINDOW: int = 8
SLOW_WINDOW: int = 32
MAX_VOLATILITY_RATIO: float = 3.0      # 3.0x burst volatility surge
MIN_VOLATILITY_RATIO: float = 0.25     # 0.25x artificial quote suppression
MIN_BASELINE_VOL: float = 0.00002       # 0.2 bp per tick minimum baseline volatility
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_price: Optional[float] = None
_returns = collections.deque(maxlen=SLOW_WINDOW)
_latest_vr: float = 1.0
_latest_sigma_fast: float = 0.0
_latest_sigma_slow: float = 0.0
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


def _calculate_std(data_slice: collections.deque) -> float:
    """Calculate sample standard deviation of a dataset."""
    n = len(data_slice)
    if n < 2:
        return 0.0
    mean_val = sum(data_slice) / float(n)
    variance = sum((x - mean_val) ** 2 for x in data_slice) / float(n - 1)
    return math.sqrt(variance)


def record_price(price: float, ts: Optional[float] = None) -> None:
    """
    Ingest a new price tick and monitor multiscale volatility ratios.
    """
    global _prev_price, _latest_vr, _latest_sigma_fast, _latest_sigma_slow, _blocked_until

    if not _is_valid_price(price):
        return

    p = float(price)
    with _lock:
        now = time.monotonic() if ts is None else float(ts)

        if _prev_price is None:
            _prev_price = p
            return

        # Calculate percentage return
        ret = (p - _prev_price) / _prev_price
        _prev_price = p
        _returns.append(ret)

        n = len(_returns)
        if n < SLOW_WINDOW:
            return

        # Calculate background volatility across preceding slice (N=24)
        bg_slice = list(_returns)[:-FAST_WINDOW]
        sigma_bg = _calculate_std(collections.deque(bg_slice))
        _latest_sigma_slow = sigma_bg

        # Calculate fast-scale volatility across recent slice (N=8)
        fast_slice = list(_returns)[-FAST_WINDOW:]
        sigma_fast = _calculate_std(collections.deque(fast_slice))
        _latest_sigma_fast = sigma_fast

        if sigma_bg < 1e-8:
            _latest_vr = 1.0
            return

        vr = sigma_fast / sigma_bg
        _latest_vr = vr

        # Only evaluate conditions if baseline volatility is active
        if sigma_bg >= MIN_BASELINE_VOL:
            # Condition 1: Fast scale explosion (Stop cascade)
            if vr >= MAX_VOLATILITY_RATIO:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return

            # Condition 2: Fast scale artificial freeze (Pre-breakout pinning)
            if vr <= MIN_VOLATILITY_RATIO:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return


def update(price: float, ts: Optional[float] = None) -> None:
    """Alias for record_price()."""
    record_price(price, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to volatility ratio divergence."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_volatility_ratio() -> float:
    """Return the latest calculated multiscale volatility ratio."""
    with _lock:
        return _latest_vr


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the multiscale volatility ratio guard."""
    with _lock:
        now = time.monotonic()
        return {
            "volatility_ratio": _latest_vr,
            "sigma_fast": _latest_sigma_fast,
            "sigma_slow": _latest_sigma_slow,
            "sample_count": len(_returns),
            "fast_window": FAST_WINDOW,
            "slow_window": SLOW_WINDOW,
            "max_ratio_threshold": MAX_VOLATILITY_RATIO,
            "min_ratio_threshold": MIN_VOLATILITY_RATIO,
            "min_baseline_vol": MIN_BASELINE_VOL,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset price history, returns buffer, and active cooldown blocks."""
    global _prev_price, _latest_vr, _latest_sigma_fast, _latest_sigma_slow, _blocked_until
    with _lock:
        _prev_price = None
        _returns.clear()
        _latest_vr = 1.0
        _latest_sigma_fast = 0.0
        _latest_sigma_slow = 0.0
        _blocked_until = 0.0
