"""
wave220_realized_semivariance_downside_asymmetry_guard.py
----------------------------------------------------------
Guard: Realized Semivariance & Downside Jump Asymmetry Guard

Decomposes high-frequency realized return variance into signed upside and downside
semivariance components (Barndorff-Nielsen, Kinnebrock & Shephard 2010; Patton & Sheppard 2015):
    Return:                    r_i = (P_i - P_{i-1}) / P_{i-1} * 10,000 (bps)
    Upside Semivariance:       RS^+ = sum( (max(0, r_i))^2 )
    Downside Semivariance:     RS^- = sum( (min(0, r_i))^2 )
    Total Realized Variance:   RV = RS^+ + RS^-
    Downside Semivariance Ratio: Q_- = RS^- / max(1e-6, RV)

In balanced continuous market making conditions:
    - Return shocks are approximately symmetric: Q_- ~ 0.50 (0.35 <= Q_- <= 0.65).
    - Market makers provide symmetric bid and ask liquidity.

During predatory directional runs, flash selloffs, or runaway liquidation cascades:
    - Realized variance concentrates almost exclusively in one signed direction.
    - Extreme Signed Semivariance Asymmetry:
        1) Downside liquidation cascade:
           Q_- >= MAX_DOWNSIDE_RATIO (default: 0.85, meaning 85% of total variance is pure downside).
        2) Parabolic upside squeeze:
           Q_- <= MIN_DOWNSIDE_RATIO (default: 0.15, meaning 85% of total variance is pure upside).
        3) Variance floor condition:
           RV >= MIN_RV_BPS2 (default: 2.50 bps^2, preventing false triggers during dead flat markets).

Scalping counter-trend or posting limit orders into an asymmetric semivariance cascade guarantees
immediate execution haircut, toxic adverse selection, and large drawdown.

When severe realized semivariance asymmetry is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests midquote via record_price(price, ts=None).
- Computes basis point return r_i.
- Maintains rolling window of WINDOW_SIZE = 25 returns.
- Requires MIN_SAMPLES = 15 returns before evaluating semivariance ratios.
- Computes RS^+, RS^-, RV, and Q_-.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive prices are rejected.

Aliases (required):
  is_entry_blocked()                       -> bool
  is_blocked()                             -> bool   (alias)
  record_price(price, ts=None)             -> None
  update(price, ts=None)                   -> None   (alias)
  get_semivariance_metrics()               -> dict
  get_status()                             -> dict
  reset()                                  -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 25
MIN_SAMPLES: int = 15
MAX_DOWNSIDE_RATIO: float = 0.85          # >= 85% of variance is downside
MIN_DOWNSIDE_RATIO: float = 0.15          # <= 15% of variance is downside (85% upside)
MIN_RV_BPS2: float = 2.50                 # 2.50 bps^2 minimum realized variance to trigger block
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_price: Optional[float] = None
_returns = collections.deque(maxlen=WINDOW_SIZE)
_latest_rs_plus: float = 0.0
_latest_rs_minus: float = 0.0
_latest_rv: float = 0.0
_latest_downside_ratio: float = 0.50
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
    Ingest a new midquote and evaluate realized semivariance asymmetry.
    """
    global _prev_price, _latest_rs_plus, _latest_rs_minus, _latest_rv, _latest_downside_ratio, _blocked_until

    if not _is_valid_price(price):
        return

    p = float(price)

    with _lock:
        if _prev_price is None:
            _prev_price = p
            return

        ret_bps = ((p - _prev_price) / _prev_price) * 10_000.0
        _prev_price = p
        _returns.append(ret_bps)

        n = len(_returns)
        if n < MIN_SAMPLES:
            return

        rs_plus = sum(r * r for r in _returns if r > 0.0)
        rs_minus = sum(r * r for r in _returns if r < 0.0)
        rv = rs_plus + rs_minus

        downside_ratio = rs_minus / max(1e-6, rv)

        _latest_rs_plus = rs_plus
        _latest_rs_minus = rs_minus
        _latest_rv = rv
        _latest_downside_ratio = downside_ratio

        # Check conditions with minimum variance floor
        if rv >= MIN_RV_BPS2:
            if downside_ratio >= MAX_DOWNSIDE_RATIO or downside_ratio <= MIN_DOWNSIDE_RATIO:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return


def update(price: float, ts: Optional[float] = None) -> None:
    """Alias for record_price()."""
    record_price(price, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to semivariance asymmetry."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_semivariance_metrics() -> Dict[str, float]:
    """Return latest calculated semivariance components and downside ratio."""
    with _lock:
        return {
            "rs_plus": _latest_rs_plus,
            "rs_minus": _latest_rs_minus,
            "realized_variance": _latest_rv,
            "downside_ratio": _latest_downside_ratio,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the realized semivariance guard."""
    with _lock:
        now = time.monotonic()
        return {
            "rs_plus": _latest_rs_plus,
            "rs_minus": _latest_rs_minus,
            "realized_variance": _latest_rv,
            "downside_ratio": _latest_downside_ratio,
            "sample_count": len(_returns),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "max_downside_ratio": MAX_DOWNSIDE_RATIO,
            "min_downside_ratio": MIN_DOWNSIDE_RATIO,
            "min_rv_bps2": MIN_RV_BPS2,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset price history, returns deque, semivariance metrics, and active cooldown blocks."""
    global _prev_price, _latest_rs_plus, _latest_rs_minus, _latest_rv, _latest_downside_ratio, _blocked_until
    with _lock:
        _prev_price = None
        _returns.clear()
        _latest_rs_plus = 0.0
        _latest_rs_minus = 0.0
        _latest_rv = 0.0
        _latest_downside_ratio = 0.50
        _blocked_until = 0.0
