"""
wave225_multiscale_fractal_variance_ratio_guard.py
---------------------------------------------------
Guard: Multi-Scale Realized Volatility Ratio & Fractal Dimension Shift Guard

Monitors cross-frequency variance scaling and deviations from Brownian motion
(Mandelbrot 1997; Peters 1994 Fractal Market Analysis; Calvet & Fisher 2002):
    1-Tick Return:         r_{1, i} = (P_i - P_{i-1}) / P_{i-1} * 10,000 (bps)
    4-Tick Return:         r_{4, j} = (P_{4j} - P_{4(j-1)}) / P_{4(j-1)} * 10,000 (bps)
    1-Tick Realized Var:   RV_1 = sum_{i=1}^N r_{1, i}^2
    4-Tick Realized Var:   RV_4 = sum_{j=1}^{N/4} r_{4, j}^2
    Scaling Ratio:         S_{scale} = RV_4 / max(1e-6, RV_1)

Under standard geometric Brownian motion (diffusive random walk):
    - Price variance scales linearly with time: E[RV_4] = E[RV_1].
    - Scaling ratio stays near parity: S_{scale} ~ 1.0 (0.60 <= S_{scale} <= 1.60).

During anomalous non-Brownian microstructure regimes:
    1) Super-Diffusive Runaway Trend (Hurst H > 0.75):
       Returns compound constructively, causing RV_4 to drastically exceed RV_1:
       S_{scale} >= MAX_SCALING_RATIO (default: 2.20x).
    2) Sub-Diffusive Noise Trap / Microstructure Friction (Hurst H < 0.25):
       Prices oscillate in bid-ask bounces, destroying multi-tick variance:
       S_{scale} <= MIN_SCALING_RATIO (default: 0.30x).
    3) Realized Variance Floor:
       RV_1 >= MIN_RV_BPS2 (default: 2.0 bps^2).

Scalpers relying on Gaussian mean-reversion or standard volatility models suffer
massive adverse selection when fractal scaling collapses or explodes.

When multi-scale variance scaling dislocation is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests midquote via record_price(price, ts=None).
- Maintains rolling window of WINDOW_SIZE = 24 prices.
- Computes 1-tick returns and non-overlapping 4-tick returns.
- Requires MIN_SAMPLES = 16 prices before evaluating scaling ratio.
- Evaluates scaling ratio S_{scale} vs bounds [0.30, 2.20] with RV_1 floor >= 2.0 bps^2.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive prices are rejected.

Aliases (required):
  is_entry_blocked()                                                   -> bool
  is_blocked()                                                         -> bool   (alias)
  record_price(price, ts=None)                                         -> None
  update(price, ts=None)                                               -> None   (alias)
  get_scaling_metrics()                                                -> dict
  get_status()                                                         -> dict
  reset()                                                              -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 24                     # 24 price points (23 1-tick returns, 5 4-tick returns)
MIN_SAMPLES: int = 16                     # 16 prices required (giving 3 4-tick returns)
SCALE_FACTOR: int = 4                     # 4-tick slow scale
MAX_SCALING_RATIO: float = 2.20           # >= 2.20 indicates super-diffusive runaway trend
MIN_SCALING_RATIO: float = 0.30           # <= 0.30 indicates sub-diffusive noise trap
MIN_RV_BPS2: float = 2.0                  # 2.0 bps^2 minimum realized variance floor
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prices = collections.deque(maxlen=WINDOW_SIZE)
_latest_rv1: float = 0.0
_latest_rv4: float = 0.0
_latest_scaling_ratio: float = 1.0
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


def record_price(price: float, ts: Optional[float] = None) -> None:
    """
    Ingest a new midquote and evaluate multiscale variance scaling ratio.
    """
    global _latest_rv1, _latest_rv4, _latest_scaling_ratio, _blocked_until

    if not _is_valid_price(price):
        return

    p = float(price)

    with _lock:
        _prices.append(p)
        n = len(_prices)
        if n < MIN_SAMPLES:
            return

        # Compute matched non-overlapping 4-tick blocks and 1-tick returns
        num_blocks = (n - 1) // SCALE_FACTOR
        if num_blocks < 3:
            return

        total_ticks = num_blocks * SCALE_FACTOR

        # 1-Tick Returns over the matched block window
        r1_list = []
        for i in range(1, total_ticks + 1):
            p_prev = _prices[i - 1]
            p_curr = _prices[i]
            ret_bps = ((p_curr - p_prev) / p_prev) * 10_000.0
            r1_list.append(ret_bps)

        rv1 = sum(r * r for r in r1_list)
        _latest_rv1 = rv1

        # 4-Tick Non-overlapping Returns
        r4_list = []
        for b in range(num_blocks):
            idx_start = b * SCALE_FACTOR
            idx_end = (b + 1) * SCALE_FACTOR
            p_start = _prices[idx_start]
            p_end = _prices[idx_end]
            ret4_bps = ((p_end - p_start) / p_start) * 10_000.0
            r4_list.append(ret4_bps)

        rv4 = sum(r * r for r in r4_list)
        _latest_rv4 = rv4

        # Scaling Ratio
        scaling_ratio = rv4 / max(1e-6, rv1)
        _latest_scaling_ratio = scaling_ratio

        # Check conditions with minimum variance floor
        if rv1 >= MIN_RV_BPS2:
            if scaling_ratio >= MAX_SCALING_RATIO or scaling_ratio <= MIN_SCALING_RATIO:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return


def update(price: float, ts: Optional[float] = None) -> None:
    """Alias for record_price()."""
    record_price(price, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to fractal scaling dislocation."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_scaling_metrics() -> Dict[str, float]:
    """Return latest calculated RV1, RV4, and Scaling Ratio."""
    with _lock:
        return {
            "realized_var_scale1": _latest_rv1,
            "realized_var_scale4": _latest_rv4,
            "scaling_ratio": _latest_scaling_ratio,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the multiscale fractal variance ratio guard."""
    with _lock:
        now = time.monotonic()
        return {
            "realized_var_scale1": _latest_rv1,
            "realized_var_scale4": _latest_rv4,
            "scaling_ratio": _latest_scaling_ratio,
            "sample_count": len(_prices),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "max_scaling_ratio": MAX_SCALING_RATIO,
            "min_scaling_ratio": MIN_SCALING_RATIO,
            "min_rv_bps2": MIN_RV_BPS2,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset price deque, variance metrics, and active cooldown blocks."""
    global _latest_rv1, _latest_rv4, _latest_scaling_ratio, _blocked_until
    with _lock:
        _prices.clear()
        _latest_rv1 = 0.0
        _latest_rv4 = 0.0
        _latest_scaling_ratio = 1.0
        _blocked_until = 0.0
