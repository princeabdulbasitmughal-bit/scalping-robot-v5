"""
wave180_cross_impact_spillover_guard.py
----------------------------------------
Guard: Cross-Asset Market Impact & Spillover Volatility Guard

Monitors cross-market price transmission between the traded target instrument (e.g. XAUUSD) and a
closely correlated proxy or benchmark instrument (e.g. DXY US Dollar Index, US 10Y Yields, or EURUSD).

In modern macro and high-frequency markets, liquidity shocks frequently originate in primary benchmark
assets before spilling over into satellite instruments.
The cross-asset sensitivity (beta) is estimated via rolling covariance and variance:
    beta_cross = Cov(r_target, r_proxy) / Var(r_proxy)
    Impact_spillover = |r_proxy_latest| * max(0.5, |beta_cross|)

When the correlated proxy experiences an abrupt directional shock:
    |r_proxy_latest| >= MAX_PROXY_SHOCK_BPS (default: 15 bps / 0.0015) or
    Impact_spillover >= MAX_SPILLOVER_BPS (default: 20 bps / 0.0020)
the target asset's order book is primed for violent sympathic repricing, widening spreads, and adverse
selection.

When cross-asset spillover impact exceeds safe thresholds, the guard blocks entry orders for
COOLDOWN_SECONDS (default: 45.0s) until cross-market equilibrium stabilizes.

Logic:
- Ingests synchronized prices: target_price and proxy_price.
- Computes percentage returns: r_target and r_proxy.
- Maintains rolling window of paired returns (WINDOW_SIZE = 30 pairs).
- Requires at least MIN_SAMPLES = 15 pairs before estimating beta.
- Computes instantaneous spillover impact.
- If |r_proxy| >= MAX_PROXY_SHOCK_BPS (0.0015) or Impact_spillover >= MAX_SPILLOVER_BPS (0.0020):
    blocks entries for COOLDOWN_SECONDS (45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive prices are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_prices(target_price, proxy_price, ts=None)        -> None
  update(target_price, proxy_price, ts=None)               -> None   (alias)
  get_spillover_impact()                                   -> float
  get_beta()                                               -> float
  get_status()                                             -> dict
  reset()                                                  -> None
"""

import collections
import math
import threading
import time
from typing import Deque, Dict, Optional, Tuple, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_PROXY_SHOCK_BPS: float = 0.0015   # 15 basis points shock in proxy asset triggers spillover guard
MAX_SPILLOVER_BPS: float = 0.0020     # 20 basis points cross-impact spillover ceiling
WINDOW_SIZE: int = 30                 # Rolling window of paired returns
MIN_SAMPLES: int = 15                 # Minimum paired returns required for beta estimation
COOLDOWN_SECONDS: float = 45.0        # Block duration on cross-market spillover shock


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_target_price: Optional[float] = None
_prev_proxy_price: Optional[float] = None
_returns_pairs: Deque[Tuple[float, float]] = collections.deque(maxlen=WINDOW_SIZE)
_latest_beta: float = 1.0
_latest_spillover: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_prices(target_price, proxy_price, ts=None) -> None:
    """Record synchronized prices for target and proxy assets and evaluate cross-impact."""
    for val in (target_price, proxy_price):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return
        if math.isnan(val) or math.isinf(val) or val <= 0.0:
            return

    tp = float(target_price)
    pp = float(proxy_price)

    global _prev_target_price, _prev_proxy_price, _latest_beta, _latest_spillover, _blocked_until
    with _lock:
        if _prev_target_price is None or _prev_proxy_price is None:
            _prev_target_price = tp
            _prev_proxy_price = pp
            return

        r_target = (tp - _prev_target_price) / _prev_target_price
        r_proxy = (pp - _prev_proxy_price) / _prev_proxy_price

        _prev_target_price = tp
        _prev_proxy_price = pp

        _returns_pairs.append((r_target, r_proxy))

        if len(_returns_pairs) < MIN_SAMPLES:
            # Check standalone proxy shock even before full beta estimation
            if abs(r_proxy) >= MAX_PROXY_SHOCK_BPS:
                _latest_spillover = abs(r_proxy)
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Instantaneous spillover impact based on established cross-asset beta
        spillover = abs(r_proxy) * max(0.5, abs(_latest_beta))
        _latest_spillover = spillover

        # Calculate updated rolling beta
        n = len(_returns_pairs)
        sum_t = sum(p[0] for p in _returns_pairs)
        sum_p = sum(p[1] for p in _returns_pairs)
        mean_t = sum_t / n
        mean_p = sum_p / n

        var_p = sum((p[1] - mean_p) ** 2 for p in _returns_pairs) / n
        cov_tp = sum((p[0] - mean_t) * (p[1] - mean_p) for p in _returns_pairs) / n

        if var_p > 1e-12:
            _latest_beta = cov_tp / var_p
        else:
            _latest_beta = 1.0

        if abs(r_proxy) >= MAX_PROXY_SHOCK_BPS or spillover >= MAX_SPILLOVER_BPS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(target_price, proxy_price, ts=None) -> None:
    """Alias for record_prices()."""
    record_prices(target_price, proxy_price, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if cross-asset market impact spillover has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_spillover_impact() -> float:
    """Return the most recently computed cross-asset spillover impact."""
    with _lock:
        return _latest_spillover


def get_beta() -> float:
    """Return the most recently estimated cross-asset beta."""
    with _lock:
        return _latest_beta


def get_status() -> Dict[str, Any]:
    """Return a diagnostic snapshot of the cross-impact spillover guard state."""
    with _lock:
        now = time.monotonic()
        return {
            "beta": _latest_beta,
            "spillover_impact": _latest_spillover,
            "max_proxy_shock_bps": MAX_PROXY_SHOCK_BPS,
            "max_spillover_bps": MAX_SPILLOVER_BPS,
            "sample_count": len(_returns_pairs),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset price history, paired returns, beta, spillover, and active blocks."""
    global _prev_target_price, _prev_proxy_price, _latest_beta, _latest_spillover, _blocked_until
    with _lock:
        _prev_target_price = None
        _prev_proxy_price = None
        _returns_pairs.clear()
        _latest_beta = 1.0
        _latest_spillover = 0.0
        _blocked_until = 0.0
