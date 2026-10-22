"""
wave228_realized_kurtosis_heavy_tail_guard.py
----------------------------------------------
Guard: Realized Kurtosis Shock & Heavy-Tail Jump Blowup Guard

Monitors fourth-moment realized kurtosis and fat-tailed outlier return explosions
(Bollerslev 1987; Jondeau & Rockinger 2003):
    Return:            r_i = (P_i - P_{i-1}) / P_{i-1} * 10,000 (bps)
    Mean Return:       bar{r} = (1/N) * sum_{i=1}^N r_i
    Variance:          sigma^2 = (1/N) * sum_{i=1}^N (r_i - bar{r})^2
    Realized Kurtosis: K = [ (1/N) * sum_{i=1}^N (r_i - bar{r})^4 ] / max(1e-8, sigma^4)
                       over rolling N = 25 ticks.

In Gaussian or mild Brownian diffusion:
    - Return distributions are mesokurtic: K ~ 3.0 (excess kurtosis ~ 0.0).
    - Extreme outliers are statistically negligible.

During acute market dislocations, liquidity shockwaves, or jump cascades:
    - A massive outlier return shock inflates the fourth moment dramatically relative to variance:
        1) Realized Kurtosis Explosion:
           K >= MAX_KURTOSIS (default: 7.00, indicating severe leptokurtic fat-tail risk).
        2) Volatility Floor:
           sigma >= MIN_SIGMA_BPS (default: 1.0 bps, preventing numerical blowups on zero-vol ticks).

Posting passive limit orders or trading tight scalping bands during heavy-tailed kurtosis spikes
guarantees catastrophic tail risk exposure and severe adverse selection.

When severe realized kurtosis explosion is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests midquote via record_price(price, ts=None).
- Computes basis-point returns r_i.
- Maintains rolling window of WINDOW_SIZE = 25 returns.
- Requires MIN_SAMPLES = 15 returns before evaluating kurtosis.
- Evaluates sample kurtosis K vs MAX_KURTOSIS (7.00) with sigma floor >= 1.0 bps.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive prices are rejected.

Aliases (required):
  is_entry_blocked()                                                   -> bool
  is_blocked()                                                         -> bool   (alias)
  record_price(price, ts=None)                                         -> None
  update(price, ts=None)                                               -> None   (alias)
  get_kurtosis_metrics()                                               -> dict
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
WINDOW_SIZE: int = 25
MIN_SAMPLES: int = 15
MAX_KURTOSIS: float = 7.00                # Leptokurtic tail shock threshold (Gaussian K=3.0)
MIN_SIGMA_BPS: float = 1.0                # Minimum 1.0 bps stddev to validate tail risk
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_price: Optional[float] = None
_returns = collections.deque(maxlen=WINDOW_SIZE)
_latest_kurtosis: float = 3.0
_latest_sigma_bps: float = 0.0
_latest_mean_bps: float = 0.0
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
    Ingest a new midquote and evaluate fourth-moment realized kurtosis.
    """
    global _prev_price, _latest_kurtosis, _latest_sigma_bps, _latest_mean_bps, _blocked_until

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

        mean_r = sum(_returns) / float(n)
        var_r = sum((r - mean_r) ** 2 for r in _returns) / float(n)
        sigma = math.sqrt(var_r)

        _latest_mean_bps = mean_r
        _latest_sigma_bps = sigma

        if sigma < MIN_SIGMA_BPS or var_r <= 1e-8:
            return

        m4 = sum((r - mean_r) ** 4 for r in _returns) / float(n)
        kurtosis = m4 / (var_r ** 2)
        _latest_kurtosis = kurtosis

        # Check Condition: Extreme leptokurtic heavy-tail blowup
        if kurtosis >= MAX_KURTOSIS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(price: float, ts: Optional[float] = None) -> None:
    """Alias for record_price()."""
    record_price(price, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to realized kurtosis shock."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_kurtosis_metrics() -> Dict[str, float]:
    """Return latest calculated kurtosis, stddev, and mean return."""
    with _lock:
        return {
            "realized_kurtosis": _latest_kurtosis,
            "sigma_bps": _latest_sigma_bps,
            "mean_return_bps": _latest_mean_bps,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the realized kurtosis guard."""
    with _lock:
        now = time.monotonic()
        return {
            "realized_kurtosis": _latest_kurtosis,
            "sigma_bps": _latest_sigma_bps,
            "mean_return_bps": _latest_mean_bps,
            "sample_count": len(_returns),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "max_kurtosis": MAX_KURTOSIS,
            "min_sigma_bps": MIN_SIGMA_BPS,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset price history, return deque, metrics, and active cooldown blocks."""
    global _prev_price, _latest_kurtosis, _latest_sigma_bps, _latest_mean_bps, _blocked_until
    with _lock:
        _prev_price = None
        _returns.clear()
        _latest_kurtosis = 3.0
        _latest_sigma_bps = 0.0
        _latest_mean_bps = 0.0
        _blocked_until = 0.0
