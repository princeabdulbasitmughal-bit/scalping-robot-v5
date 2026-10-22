"""
wave255_hf_return_skewness_extreme_guard.py
---------------------------------------------
Guard: Microstructure High-Frequency Return Skewness Extreme Guard

Monitors third-moment realized return skewness across rolling tick windows to detect
asymmetric liquidation cascades, crash jumps, or one-sided algorithmic sweeps
(Harvey & Siddique 2000; Amaya et al. 2015):
    Tick Return:             r_i in basis points (bps)
    Mean Return:             \\mu = (1 / N) * \\sum_{i=1}^N r_i
    Variance (2nd moment):   m_2 = (1 / N) * \\sum_{i=1}^N (r_i - \\mu)^2,  \\sigma = sqrt(m_2)
    3rd Central Moment:      m_3 = (1 / N) * \\sum_{i=1}^N (r_i - \\mu)^3
    Realized Skewness:       S_k = m_3 / max(1e-6, \\sigma^3)

In diffusive, symmetric continuous double-auction markets:
    - Tick returns oscillate symmetrically around the midpoint:
      |S_k| <= 1.0 - 1.5 across rolling N=25 ticks.

During predatory iceberg sweeps, sudden flash crashes, or directional stop runs:
    - Return distributions display extreme asymmetric fat tails:
        1) Severe Return Skewness Extreme:
           |S_k| >= MAX_SKEWNESS (default: 2.20) AND
           \\sigma >= MIN_VOLATILITY_BPS (default: 0.60 bps) over rolling N >= 20 ticks.
        2) Acute Crash Skewness Jump:
           |S_k| >= ACUTE_SKEWNESS (default: 3.00) AND
           \\sigma >= ACUTE_VOLATILITY_BPS (default: 1.00 bps).

Attempting to fade or trade against extreme return skewness guarantees catastrophic
tail risk, adverse fill selection, and steep drawdowns.

When return skewness extreme is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests prices via record_price(price, ts=None) or
  direct returns via record_return(return_bps, ts=None).
- Maintains rolling history of WINDOW_SIZE = 25 tick returns.
- Minimum MIN_SAMPLES = 20 ticks required for rolling skewness evaluation.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive prices are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_price(price, ts=None)                                                                 -> None
  record_return(return_bps, ts=None)                                                           -> None
  update(price_or_return, is_return=False, ts=None)                                            -> None   (alias)
  get_skewness_metrics()                                                                       -> dict
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
WINDOW_SIZE: int = 25
MIN_SAMPLES: int = 20
MAX_SKEWNESS: float = 2.20             # 2.20 realized skewness ceiling
MIN_VOLATILITY_BPS: float = 0.60       # 0.60 bps baseline volatility
ACUTE_SKEWNESS: float = 3.00           # 3.00 acute crash skewness
ACUTE_VOLATILITY_BPS: float = 1.00     # 1.00 bps acute volatility
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_price: Optional[float] = None
_returns_history = collections.deque(maxlen=WINDOW_SIZE)  # returns in bps
_latest_return_bps: float = 0.0
_latest_skewness: float = 0.0
_latest_volatility_bps: float = 0.0
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


def record_return(
    return_bps: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest a tick return directly in basis points and evaluate 3rd-moment skewness.
    """
    global _latest_return_bps, _latest_skewness, _latest_volatility_bps, _blocked_until

    if not _is_valid_numeric(return_bps):
        return

    r = float(return_bps)

    with _lock:
        _latest_return_bps = r
        _returns_history.append(r)

        n = len(_returns_history)
        if n >= MIN_SAMPLES:
            mu = sum(_returns_history) / n
            m2 = sum((x - mu) ** 2 for x in _returns_history) / n
            sigma = math.sqrt(max(0.0, m2))

            if sigma >= 1e-4:
                m3 = sum((x - mu) ** 3 for x in _returns_history) / n
                skewness = m3 / (sigma ** 3)
            else:
                skewness = 0.0

            _latest_skewness = skewness
            _latest_volatility_bps = sigma

            # Condition 1: Acute crash skewness jump
            if abs(skewness) >= ACUTE_SKEWNESS and sigma >= ACUTE_VOLATILITY_BPS:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return

            # Condition 2: Severe return skewness extreme
            if abs(skewness) >= MAX_SKEWNESS and sigma >= MIN_VOLATILITY_BPS:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return
        else:
            _latest_skewness = 0.0
            _latest_volatility_bps = 0.0


def record_price(
    price: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest price, compute tick return in basis points, and record.
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

    record_return(ret_bps, ts)


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
        record_return(price_or_return, ts)
    else:
        record_price(price_or_return, ts)


def is_entry_blocked() -> bool:
    """Check if new entries are blocked by return skewness extreme."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_skewness_metrics() -> Dict[str, float]:
    """Retrieve current return skewness metrics."""
    with _lock:
        return {
            "latest_return_bps": _latest_return_bps,
            "skewness": _latest_skewness,
            "volatility_bps": _latest_volatility_bps,
        }


def get_status() -> Dict[str, Any]:
    """Retrieve complete guard status."""
    with _lock:
        now = time.monotonic()
        blocked = now < _blocked_until
        remaining = max(0.0, _blocked_until - now) if blocked else 0.0
        return {
            "guard_name": "wave255_hf_return_skewness_extreme_guard",
            "is_blocked": blocked,
            "blocked_seconds_remaining": remaining,
            "sample_count": len(_returns_history),
            "latest_return_bps": _latest_return_bps,
            "skewness": _latest_skewness,
            "volatility_bps": _latest_volatility_bps,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "max_skewness": MAX_SKEWNESS,
            "min_volatility_bps": MIN_VOLATILITY_BPS,
            "acute_skewness": ACUTE_SKEWNESS,
            "acute_volatility_bps": ACUTE_VOLATILITY_BPS,
        }


def reset() -> None:
    """Reset all guard state and clear cooldowns."""
    global _prev_price, _latest_return_bps, _latest_skewness
    global _latest_volatility_bps, _blocked_until

    with _lock:
        _prev_price = None
        _returns_history.clear()
        _latest_return_bps = 0.0
        _latest_skewness = 0.0
        _latest_volatility_bps = 0.0
        _blocked_until = 0.0
