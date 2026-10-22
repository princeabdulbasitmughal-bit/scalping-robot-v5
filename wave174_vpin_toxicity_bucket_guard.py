"""
wave174_vpin_toxicity_bucket_guard.py
--------------------------------------
Guard: Volume-Synchronized Probability of Toxicity (VPIN) Guard

Implements Easley, Lopez de Prado, and O'Hara's Volume-Synchronized Probability of Toxicity (VPIN)
to detect toxic order flow and predatory adverse selection from informed institutional traders.

Under standard conditions, trading volume is balanced across buys and sells, resulting in low
volume-synchronized order flow imbalance (VPIN ~ 0.15 to 0.45).
When informed participants (e.g. front-running algorithms, institutional liquidation sweeps, or
breaking news traders) aggressively cross the spread, the directional volume imbalance per
volume bucket spikes dramatically.

When VPIN exceeds MAX_VPIN (default: 0.70, or 70% toxic imbalance across rolling buckets), the
scalping robot is at high risk of severe adverse selection and must suspend entry orders for
COOLDOWN_SECONDS (default: 60.0s) until balanced two-sided market making resumes.

Logic:
- Accumulates trades into fixed volume buckets (BUCKET_VOLUME = 50.0 lots/units).
- Determines trade direction using the tick rule:
    b_t = +1 if P_t > P_{t-1} (buyer initiated)
    b_t = -1 if P_t < P_{t-1} (seller initiated)
    b_t = b_{t-1} if P_t == P_{t-1} (tick rule continuation, default +1)
- Splits incoming volume across bucket boundaries so every completed bucket has exact volume V.
- For each completed bucket tau, tracks directional imbalance |V_tau^B - V_tau^S|.
- Maintains a rolling window of NUM_BUCKETS = 20 completed buckets.
- Computes VPIN = sum(|V_tau^B - V_tau^S|) / (N * V).
- Requires at least MIN_BUCKETS = 10 completed buckets before triggering blocks.
- If VPIN >= MAX_VPIN (0.70):
    blocks entries for COOLDOWN_SECONDS (60.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state mutations.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive price/volume inputs are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_trade(price, volume, ts=None)                     -> None
  update(price, volume, ts=None)                           -> None   (alias)
  get_vpin()                                               -> float
  get_status()                                             -> dict
  reset()                                                  -> None
"""

import collections
import math
import threading
import time
from typing import Deque, Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BUCKET_VOLUME: float = 50.0        # Volume units per standardized bucket
NUM_BUCKETS: int = 20              # Rolling window of completed buckets
MIN_BUCKETS: int = 10              # Minimum completed buckets before evaluating blocks
MAX_VPIN: float = 0.70             # VPIN >= 0.70 indicates severe adverse selection
COOLDOWN_SECONDS: float = 60.0     # Block duration on toxic order flow surge


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_price: Optional[float] = None
_prev_sign: int = 1
_curr_buy: float = 0.0
_curr_sell: float = 0.0
_buckets: Deque[float] = collections.deque(maxlen=NUM_BUCKETS)
_latest_vpin: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_trade(price, volume, ts=None) -> None:
    """Record a trade, allocate volume to VPIN buckets, and evaluate toxicity."""
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return
    if isinstance(volume, bool) or not isinstance(volume, (int, float)):
        return
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return
    if math.isnan(volume) or math.isinf(volume) or volume <= 0.0:
        return

    p = float(price)
    v = float(volume)

    global _prev_price, _prev_sign, _curr_buy, _curr_sell, _latest_vpin, _blocked_until
    with _lock:
        if _prev_price is None:
            sign = 1
        elif p > _prev_price:
            sign = 1
        elif p < _prev_price:
            sign = -1
        else:
            sign = _prev_sign

        _prev_price = p
        _prev_sign = sign

        remaining_vol = v
        while remaining_vol > 1e-9:
            space = BUCKET_VOLUME - (_curr_buy + _curr_sell)
            if space <= 1e-9:
                # Previous bucket was somehow filled exactly without clearing
                imbalance = abs(_curr_buy - _curr_sell)
                _buckets.append(imbalance)
                _curr_buy = 0.0
                _curr_sell = 0.0
                space = BUCKET_VOLUME

            if remaining_vol < space:
                if sign > 0:
                    _curr_buy += remaining_vol
                else:
                    _curr_sell += remaining_vol
                remaining_vol = 0.0
            else:
                fill = space
                if sign > 0:
                    _curr_buy += fill
                else:
                    _curr_sell += fill
                
                # Bucket completed
                imbalance = abs(_curr_buy - _curr_sell)
                _buckets.append(imbalance)
                _curr_buy = 0.0
                _curr_sell = 0.0
                remaining_vol -= fill

        if len(_buckets) >= MIN_BUCKETS:
            total_imbalance = sum(_buckets)
            total_volume = len(_buckets) * BUCKET_VOLUME
            vpin = total_imbalance / total_volume if total_volume > 0.0 else 0.0
            _latest_vpin = vpin

            if vpin >= MAX_VPIN:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(price, volume, ts=None) -> None:
    """Alias for record_trade()."""
    record_trade(price, volume, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if high VPIN toxicity has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_vpin() -> float:
    """Return the most recently calculated VPIN value."""
    with _lock:
        return _latest_vpin


def get_status() -> Dict[str, Any]:
    """Return a diagnostic snapshot of the VPIN guard state."""
    with _lock:
        now = time.monotonic()
        return {
            "vpin": _latest_vpin,
            "completed_buckets": len(_buckets),
            "max_buckets": NUM_BUCKETS,
            "min_buckets": MIN_BUCKETS,
            "bucket_volume": BUCKET_VOLUME,
            "max_vpin_threshold": MAX_VPIN,
            "current_buy_partial": _curr_buy,
            "current_sell_partial": _curr_sell,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset all bucket state, trade history, and active blocks."""
    global _prev_price, _prev_sign, _curr_buy, _curr_sell, _latest_vpin, _blocked_until
    with _lock:
        _prev_price = None
        _prev_sign = 1
        _curr_buy = 0.0
        _curr_sell = 0.0
        _buckets.clear()
        _latest_vpin = 0.0
        _blocked_until = 0.0
