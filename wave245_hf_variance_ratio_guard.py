"""
wave245_hf_variance_ratio_guard.py
------------------------------------
Guard: Microstructure High-Frequency Variance Ratio Non-Random Walk Guard

Monitors empirical Lo-MacKinlay (1988) Variance Ratio on tick price returns to detect
non-diffusive market states (persistent algorithmic trends vs violent whiplash chop):
    1-Tick Return:           r_1(t) = P_t - P_{t-1} (bps)
    q-Tick Return:           r_q(t) = P_t - P_{t-q} = \\sum_{k=0}^{q-1} r_1(t - k)
    Variance Ratio:          VR(q) = \\sigma^2(q) / (q * \\sigma^2(1)),  where q = 4

Under ideal Brownian motion / diffusive continuous double-auction conditions:
    - Returns are serially uncorrelated:
      VR(q) ~ 1.0 (typically 0.70 - 1.30 across rolling N=32 ticks).

During predatory directional momentum sweeps or severe microstructure ping-pong whiplash:
    - Price changes display extreme autocorrelation and structural deviation from random walk:
        1) Persistent Algorithmic Trend Drift:
           VR(q) >= MAX_VARIANCE_RATIO (default: 1.85) AND
           1-tick volatility \\sigma_1 >= MIN_VOLATILITY_BPS (default: 0.50 bps)
           over rolling N >= 24 ticks (strong directional auto-correlation).
        2) High-Frequency Whiplash Bounce:
           VR(q) <= MIN_VARIANCE_RATIO (default: 0.30) AND
           \\sigma_1 >= WHIPLASH_VOLATILITY_BPS (default: 0.80 bps)
           over rolling N >= 24 ticks (toxic mean-reverting pinball).

Fading strong trending sweeps or placing orders into toxic ping-pong whiplash results in
severe adverse selection, high cancel fees, and whipsaw stop-outs.

When non-random walk regime (persistent trend drift or violent whiplash) is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests prices via record_price(price, ts=None) or
  direct 1-tick returns via record_tick_return(return_bps, ts=None).
- Maintains rolling history of WINDOW_SIZE = 32 tick returns.
- Minimum MIN_SAMPLES = 24 ticks required for Variance Ratio trip evaluation.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive prices are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_price(price, ts=None)                                                                 -> None
  record_tick_return(return_bps, ts=None)                                                      -> None
  update(price_or_return, is_return=False, ts=None)                                            -> None   (alias)
  get_variance_ratio_metrics()                                                                 -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 32
MIN_SAMPLES: int = 24
AGGREGATION_Q: int = 4                 # q = 4 ticks
MAX_VARIANCE_RATIO: float = 1.85       # VR(4) >= 1.85 persistent trend drift
MIN_VARIANCE_RATIO: float = 0.30       # VR(4) <= 0.30 toxic whiplash bounce
MIN_VOLATILITY_BPS: float = 0.50       # 0.50 bps baseline volatility for trend
WHIPLASH_VOLATILITY_BPS: float = 0.80  # 0.80 bps baseline volatility for whiplash
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_price: Optional[float] = None
_returns_history = collections.deque(maxlen=WINDOW_SIZE)  # 1-tick returns in bps
_latest_vr: float = 1.0
_latest_sigma1: float = 0.0
_latest_sigma_q: float = 0.0
_blocked_until: float = 0.0


def _is_valid_positive(val: Any) -> bool:
    """Validate value is a positive finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val > 0.0


def _is_valid_numeric(val: Any) -> bool:
    """Validate value is a finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return True


def record_tick_return(
    return_bps: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest a 1-tick return in basis points and evaluate the Lo-MacKinlay Variance Ratio.
    """
    global _latest_vr, _latest_sigma1, _latest_sigma_q, _blocked_until

    if not _is_valid_numeric(return_bps):
        return

    r1 = float(return_bps)

    with _lock:
        _returns_history.append(r1)

        n = len(_returns_history)
        if n < MIN_SAMPLES:
            return

        # Compute 1-tick sample variance
        mean_1 = sum(_returns_history) / n
        var_1 = sum((x - mean_1) ** 2 for x in _returns_history) / (n - 1)
        sigma_1 = math.sqrt(max(0.0, var_1))

        if sigma_1 <= 1e-6:
            _latest_vr = 1.0
            _latest_sigma1 = 0.0
            _latest_sigma_q = 0.0
            return

        # Compute q-tick aggregated returns (overlapping)
        q = AGGREGATION_Q
        rets = list(_returns_history)
        q_returns = []
        for i in range(q - 1, n):
            q_ret = sum(rets[i - k] for k in range(q))
            q_returns.append(q_ret)

        m = len(q_returns)
        mean_q = q * mean_1
        var_q = sum((x - mean_q) ** 2 for x in q_returns) / max(1, m - 1)
        sigma_q = math.sqrt(max(0.0, var_q))

        vr = var_q / max(1e-6, q * var_1)

        _latest_vr = vr
        _latest_sigma1 = sigma_1
        _latest_sigma_q = sigma_q

        # Condition 1: Persistent algorithmic trend drift
        if vr >= MAX_VARIANCE_RATIO and sigma_1 >= MIN_VOLATILITY_BPS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 2: Toxic high-frequency whiplash bounce
        if vr <= MIN_VARIANCE_RATIO and sigma_1 >= WHIPLASH_VOLATILITY_BPS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_price(
    price: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest price, compute tick return in basis points, and evaluate Variance Ratio.
    """
    global _prev_price

    if not _is_valid_positive(price):
        return

    p = float(price)

    with _lock:
        if _prev_price is not None and _prev_price > 0.0:
            ret_bps = ((p - _prev_price) / _prev_price) * 10000.0
            _prev_price = p
        else:
            _prev_price = p
            return

    record_tick_return(ret_bps, ts)


def update(
    price_or_return: float,
    is_return: bool = False,
    ts: Optional[float] = None,
) -> None:
    """
    Flexible alias:
    If is_return is True, treats input as tick return in bps.
    If is_return is False, treats input as price.
    """
    if is_return:
        record_tick_return(price_or_return, ts)
    else:
        record_price(price_or_return, ts)


def is_entry_blocked() -> bool:
    """Check if new entries are blocked by non-random walk Variance Ratio."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_variance_ratio_metrics() -> Dict[str, float]:
    """Retrieve current variance ratio metrics."""
    with _lock:
        return {
            "variance_ratio": _latest_vr,
            "sigma_1_bps": _latest_sigma1,
            "sigma_q_bps": _latest_sigma_q,
        }


def get_status() -> Dict[str, Any]:
    """Retrieve complete guard status."""
    with _lock:
        now = time.monotonic()
        blocked = now < _blocked_until
        remaining = max(0.0, _blocked_until - now) if blocked else 0.0
        return {
            "guard_name": "wave245_hf_variance_ratio_guard",
            "is_blocked": blocked,
            "blocked_seconds_remaining": remaining,
            "sample_count": len(_returns_history),
            "variance_ratio": _latest_vr,
            "sigma_1_bps": _latest_sigma1,
            "sigma_q_bps": _latest_sigma_q,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "max_variance_ratio": MAX_VARIANCE_RATIO,
            "min_variance_ratio": MIN_VARIANCE_RATIO,
            "min_volatility_bps": MIN_VOLATILITY_BPS,
            "whiplash_volatility_bps": WHIPLASH_VOLATILITY_BPS,
        }


def reset() -> None:
    """Reset all guard state and clear cooldowns."""
    global _prev_price, _latest_vr, _latest_sigma1, _latest_sigma_q, _blocked_until

    with _lock:
        _prev_price = None
        _returns_history.clear()
        _latest_vr = 1.0
        _latest_sigma1 = 0.0
        _latest_sigma_q = 0.0
        _blocked_until = 0.0
