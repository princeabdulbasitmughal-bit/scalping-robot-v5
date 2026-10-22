"""
wave270_lob_quote_life_entropy_guard.py
---------------------------------------
Guard: LOB Quote Life Duration Distribution & Exponential Decay Guard

Monitors limit order book quote lifetime duration, fleeting liquidity share, and phantom quote churn
(Biais, Hillion & Spatt 1995; Hautsch 2012; Hasbrouck 2018):
    Quote Lifespan:             tau_{quote} = t_{cancel} - t_{insert} (milliseconds)
    Fleeting Threshold:         tau_{fleeting} <= 50.0 ms
    Fleeting Quote Share:       R_{fleeting} = N(tau <= 50 ms) / N_{total}
    Median Quote Lifespan:      tau_{med} = median(tau_{quote}, N=25)
    Ultra-Fleeting Streak:      L_{fleeting} = consecutive quotes with tau <= 25.0 ms

Under standard genuine market making conditions:
    - Limit orders rest in queues to earn spread: median quote lifespans exceed 500 ms (tau_{med} >= 200 ms).
    - Fleeting quotes represent a minor fraction of total quote activity (R_{fleeting} <= 0.35).

During predatory phantom quote flickering, spoofing, or high-frequency order book churning:
    - Quotes vanish almost immediately after submission without providing real fill liquidity:
        1) Dominant Fleeting Quote Share:
           R_{fleeting} >= MAX_FLEETING_RATIO (default: 0.75) over rolling N >= MIN_SAMPLES (20 cancellations).
        2) Acute Median Lifespan Decay:
           tau_{med} <= ACUTE_MEDIAN_LIFETIME_MS (default: 40.0 ms) over N >= 15 cancellations.
        3) Ultra-Fleeting Cancellation Streak:
           L_{fleeting} >= MAX_FLEETING_STREAK (default: 8 consecutive quotes with tau <= 25.0 ms).

Submitting market orders into fleeting liquidity guarantees phantom fills, quote fade slippage,
and negative execution markouts.

When dominant fleeting share or acute lifespan decay is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests quote lifetimes via record_quote_lifetime(lifetime_ms, ts=None) or
  direct metrics via record_fleeting_metrics(fleeting_ratio, median_lifetime_ms=None, sample_count=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 25 quote lifespans.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative lifespans are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_quote_lifetime(lifetime_ms, ts=None)                                                  -> None
  record_fleeting_metrics(fleeting_ratio, median_lifetime_ms=None, sample_count=None, ts=None)  -> None
  update(lifetime_ms, ts=None)                                                                 -> None   (alias)
  get_lifetime_metrics()                                                                       -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Dict, Optional, Any, Deque

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 25                   # 25 quote lifetimes rolling window
MIN_SAMPLES: int = 20                   # 20 observations minimum for fleeting share evaluation
MAX_FLEETING_RATIO: float = 0.75        # 75% fleeting quote share threshold
FLEETING_THRESHOLD_MS: float = 50.0     # 50.0 ms threshold for fleeting quote definition
ACUTE_MEDIAN_LIFETIME_MS: float = 40.0  # 40.0 ms acute median lifespan floor
MAX_FLEETING_STREAK: int = 8            # 8 consecutive ultra-fleeting quotes (<= 25 ms)
ULTRA_FLEETING_MS: float = 25.0         # 25.0 ms ultra-fleeting threshold
COOLDOWN_SECONDS: float = 45.0          # 45.0s block duration

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_lifetimes: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_current_fleeting_streak: int = 0
_latest_fleeting_ratio: float = 0.0
_latest_median_lifetime_ms: float = 500.0
_blocked_until: float = 0.0


def _is_valid_non_negative(val: Any) -> bool:
    """Validate value is a non-negative finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val >= 0.0


def _is_valid_numeric(val: Any) -> bool:
    """Validate value is a finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return True


def record_fleeting_metrics(
    fleeting_ratio: float,
    median_lifetime_ms: Optional[float] = None,
    sample_count: Optional[int] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Directly ingest precomputed fleeting quote ratio and median lifetime.
    """
    global _latest_fleeting_ratio, _latest_median_lifetime_ms, _blocked_until

    if not _is_valid_numeric(fleeting_ratio):
        return

    r = max(0.0, min(1.0, float(fleeting_ratio)))
    med = float(median_lifetime_ms) if (median_lifetime_ms is not None and _is_valid_non_negative(median_lifetime_ms)) else 500.0
    n = int(sample_count) if (sample_count is not None and isinstance(sample_count, int) and not isinstance(sample_count, bool) and sample_count > 0) else 20

    with _lock:
        _latest_fleeting_ratio = r
        _latest_median_lifetime_ms = med

        # Condition 2: Acute Median Lifespan Decay
        if med <= ACUTE_MEDIAN_LIFETIME_MS and n >= 15:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 1: Dominant Fleeting Quote Share
        if r >= MAX_FLEETING_RATIO and n >= MIN_SAMPLES:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_quote_lifetime(lifetime_ms: float, ts: Optional[float] = None) -> None:
    """
    Ingest a single cancelled quote's lifespan in milliseconds.
    """
    global _lifetimes, _current_fleeting_streak, _latest_fleeting_ratio
    global _latest_median_lifetime_ms, _blocked_until

    if not _is_valid_non_negative(lifetime_ms):
        return

    lt = float(lifetime_ms)

    with _lock:
        # Update ultra-fleeting streak
        if lt <= ULTRA_FLEETING_MS:
            _current_fleeting_streak += 1
        else:
            _current_fleeting_streak = 0

        # Condition 3: Ultra-Fleeting Cancellation Streak
        if _current_fleeting_streak >= MAX_FLEETING_STREAK:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            _lifetimes.append(lt)
            return

        _lifetimes.append(lt)

        if len(_lifetimes) >= 15:
            med = statistics.median(_lifetimes)
            _latest_median_lifetime_ms = med

            # Condition 2: Acute Median Lifespan Decay
            if med <= ACUTE_MEDIAN_LIFETIME_MS:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return

        if len(_lifetimes) >= MIN_SAMPLES:
            fleeting_count = sum(1 for x in _lifetimes if x <= FLEETING_THRESHOLD_MS)
            ratio = fleeting_count / float(len(_lifetimes))
            _latest_fleeting_ratio = ratio

            # Condition 1: Dominant Fleeting Quote Share
            if ratio >= MAX_FLEETING_RATIO:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return


def update(lifetime_ms: float, ts: Optional[float] = None) -> None:
    """Module alias for record_quote_lifetime."""
    record_quote_lifetime(lifetime_ms, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if entry is currently blocked by quote life guard."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked."""
    return is_entry_blocked()


def get_lifetime_metrics() -> Dict[str, Any]:
    """Return dictionary of current quote lifetime metrics."""
    with _lock:
        med = statistics.median(_lifetimes) if _lifetimes else _latest_median_lifetime_ms
        return {
            "fleeting_ratio": round(_latest_fleeting_ratio, 4),
            "median_lifetime_ms": round(med, 2),
            "current_streak": _current_fleeting_streak,
            "sample_count": len(_lifetimes),
            "max_fleeting_ratio": MAX_FLEETING_RATIO,
            "acute_median_lifetime_ms": ACUTE_MEDIAN_LIFETIME_MS,
            "max_fleeting_streak": MAX_FLEETING_STREAK,
            "is_blocked": is_entry_blocked(),
        }


def get_status() -> Dict[str, Any]:
    """Return complete status dictionary."""
    with _lock:
        remaining_cd = max(0.0, _blocked_until - time.monotonic())
        metrics = get_lifetime_metrics()
        metrics["cooldown_remaining_sec"] = round(remaining_cd, 2)
        return metrics


def reset() -> None:
    """Reset all state to initial defaults."""
    global _lifetimes, _current_fleeting_streak, _latest_fleeting_ratio
    global _latest_median_lifetime_ms, _blocked_until
    with _lock:
        _lifetimes.clear()
        _current_fleeting_streak = 0
        _latest_fleeting_ratio = 0.0
        _latest_median_lifetime_ms = 500.0
        _blocked_until = 0.0
