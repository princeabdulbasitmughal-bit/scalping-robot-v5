"""
wave139_order_flow_toxicity_vpin_guard.py
-----------------------------------------
Guard: Volume-Synchronized Probability of Toxicity (VPIN) Proxy Guard

Monitors high-frequency order flow toxicity across volume-synchronized buckets.
Measures the directional order flow imbalance |V_B - V_S| relative to total volume
to detect aggressive institutional toxicity, predatory sweeps, and asymmetric informed trading.

Logic:
- Evaluates individual trades: price and volume.
- Infers trade aggressor direction via standard tick rule:
    price > prev_price -> buy-initiated
    price < prev_price -> sell-initiated
    price == prev_price -> persists previous trade direction
- Fills volume buckets of size BUCKET_VOLUME (default: 5.0 lots).
- When a bucket completes, stores the absolute volume imbalance |V_B - V_S|.
- Maintains a rolling window of NUM_BUCKETS (default: 5 buckets).
- Computes VPIN toxicity metric:
    VPIN = sum(imbalances) / (NUM_BUCKETS * BUCKET_VOLUME)
- If VPIN >= MAX_VPIN_TOXICITY (default: 0.70):
    blocks entries for COOLDOWN_SECONDS (default: 60.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Fail-closed: non-numeric, boolean, NaN, Inf, and non-positive inputs ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()                      -> bool
  is_blocked()                            -> bool   (alias)
  record_trade(price, volume, ts=None)    -> None
  update(price, volume, ts=None)          -> None   (alias)
  get_current_vpin()                      -> float
  reset()                                 -> None
"""

import collections
import math
import threading
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BUCKET_VOLUME: float = 5.0             # volume capacity per bucket in lots
NUM_BUCKETS: int = 5                   # rolling buckets to evaluate VPIN
MAX_VPIN_TOXICITY: float = 0.70        # VPIN threshold triggering protective block
COOLDOWN_SECONDS: float = 60.0         # duration of protective block


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_price: Optional[float] = None
_last_direction: int = 1
_current_bucket_vol: float = 0.0
_current_bucket_buy: float = 0.0
_current_bucket_sell: float = 0.0
_completed_buckets = collections.deque(maxlen=NUM_BUCKETS)
_blocked_until: float = 0.0
_last_vpin: float = 0.20               # default baseline VPIN


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_trade(price, volume, ts=None) -> None:
    """Record trade price and volume, slice into volume buckets, and compute VPIN."""
    for val in (price, volume):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return
        if math.isnan(val) or math.isinf(val) or val <= 0.0:
            return

    curr_p = float(price)
    vol = float(volume)

    global _prev_price, _last_direction, _current_bucket_vol
    global _current_bucket_buy, _current_bucket_sell, _blocked_until, _last_vpin

    with _lock:
        if _prev_price is None:
            _prev_price = curr_p
            return

        diff = curr_p - _prev_price
        if diff > 1e-9:
            direction = 1
        elif diff < -1e-9:
            direction = -1
        else:
            direction = _last_direction

        _last_direction = direction
        _prev_price = curr_p

        # Accumulate volume into buckets
        remaining = vol
        while remaining > 1e-9:
            needed = BUCKET_VOLUME - _current_bucket_vol
            chunk = min(remaining, needed)

            if direction > 0:
                _current_bucket_buy += chunk
            else:
                _current_bucket_sell += chunk

            _current_bucket_vol += chunk
            remaining -= chunk

            if _current_bucket_vol >= BUCKET_VOLUME - 1e-9:
                imbalance = abs(_current_bucket_buy - _current_bucket_sell)
                _completed_buckets.append(imbalance)
                _current_bucket_vol = 0.0
                _current_bucket_buy = 0.0
                _current_bucket_sell = 0.0

        if len(_completed_buckets) >= NUM_BUCKETS:
            total_imbalance = sum(_completed_buckets)
            total_vol = len(_completed_buckets) * BUCKET_VOLUME
            vpin = total_imbalance / total_vol
            _last_vpin = vpin

            if vpin >= MAX_VPIN_TOXICITY:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(price, volume, ts=None) -> None:
    """Alias for record_trade()."""
    record_trade(price, volume, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if order flow toxicity (VPIN) has triggered an entry block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_current_vpin() -> float:
    """Return the most recently computed VPIN toxicity metric."""
    with _lock:
        return _last_vpin


def reset() -> None:
    """Reset trade history, bucket state, and active block."""
    global _prev_price, _last_direction, _current_bucket_vol
    global _current_bucket_buy, _current_bucket_sell, _blocked_until, _last_vpin

    with _lock:
        _prev_price = None
        _last_direction = 1
        _current_bucket_vol = 0.0
        _current_bucket_buy = 0.0
        _current_bucket_sell = 0.0
        _completed_buckets.clear()
        _blocked_until = 0.0
        _last_vpin = 0.20
