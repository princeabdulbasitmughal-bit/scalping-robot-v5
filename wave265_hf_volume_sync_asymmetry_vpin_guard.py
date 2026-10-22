"""
wave265_hf_volume_sync_asymmetry_vpin_guard.py
----------------------------------------------
Guard: High-Frequency Volume-Synchronized Probability of Toxicity (VPIN) Guard

Monitors volume-clock order flow imbalance and informed trade toxicity
(Easley, Lopez de Prado & O'Hara 2011, 2012):
    Volume Bucket Size:         V_{bucket} = 5.0 lots
    Bucket Buy/Sell Volume:     V_{tau}^{buy}, V_{tau}^{sell} where V_{tau}^{buy} + V_{tau}^{sell} = V_{bucket}
    Bucket Absolute Imbalance:  Delta V_{tau} = |V_{tau}^{buy} - V_{tau}^{sell}|
    Rolling VPIN:               VPIN = (1 / (N * V_{bucket})) * sum_{tau=1}^N Delta V_{tau}
    Acute Bucket Toxicity:      Delta V_{tau} / V_{bucket} >= 0.95 within Delta t <= 1.0s

Under balanced double-auction trading without asymmetric private information:
    - Order flow is evenly distributed between buyer-initiated and seller-initiated volume:
      VPIN remains moderate (VPIN ~ 0.20 - 0.45).

During predatory directional sweeps, toxic informed cascades, or stop-loss chain reactions:
    - Trade flow exhibits continuous one-sided volume domination:
        1) Elevated Flow Toxicity Persistence:
           VPIN >= MAX_VPIN (default: 0.75) across rolling N >= MIN_BUCKETS (10 completed buckets).
        2) Acute Single-Bucket Toxicity Spike:
           Delta V_{tau} / V_{bucket} >= ACUTE_BUCKET_IMBALANCE (0.95) completed in Delta t <= ACUTE_BUCKET_TIME_SEC (1.0s).

Executing trades during elevated VPIN or acute volume toxicity spikes guarantees adverse execution,
severe markouts, and catastrophic fill selection.

When elevated VPIN or acute volume toxicity is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trades via record_trade(sign, volume, ts=None) or
  direct toxicity via record_vpin(vpin, bucket_imbalance=None, sample_count=None, ts=None).
- Synchronizes trade volume into discrete buckets of BUCKET_VOLUME = 5.0 lots.
- Maintains rolling history of WINDOW_BUCKETS = 10 completed volume buckets.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive volumes, or zero signs are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade(sign, volume, ts=None)                                                          -> None
  record_vpin(vpin, bucket_imbalance=None, sample_count=None, ts=None)                         -> None
  update(sign, volume=1.0, ts=None)                                                            -> None   (alias)
  get_vpin_metrics()                                                                           -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any, Deque

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BUCKET_VOLUME: float = 5.0              # 5.0 lots per volume bucket
WINDOW_BUCKETS: int = 10                # 10 completed buckets rolling window
MIN_BUCKETS: int = 10                   # 10 buckets minimum for rolling VPIN
MAX_VPIN: float = 0.75                  # 0.75 (75%) maximum acceptable VPIN threshold
ACUTE_BUCKET_IMBALANCE: float = 0.95    # 95% single-bucket imbalance threshold
ACUTE_BUCKET_TIME_SEC: float = 1.0      # 1.0s maximum duration for acute bucket fill
COOLDOWN_SECONDS: float = 45.0          # 45.0s block duration

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_bucket_imbalances: Deque[float] = collections.deque(maxlen=WINDOW_BUCKETS)
_curr_buy_vol: float = 0.0
_curr_sell_vol: float = 0.0
_curr_bucket_start_ts: Optional[float] = None
_latest_vpin: float = 0.30
_latest_bucket_imbalance: float = 0.0
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


def record_vpin(
    vpin: float,
    bucket_imbalance: Optional[float] = None,
    sample_count: Optional[int] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Directly ingest precomputed VPIN metric and bucket imbalance.
    """
    global _latest_vpin, _latest_bucket_imbalance, _blocked_until

    if not _is_valid_numeric(vpin):
        return

    vp = max(0.0, min(1.0, float(vpin)))
    b_imb = float(bucket_imbalance) if (bucket_imbalance is not None and _is_valid_numeric(bucket_imbalance)) else 0.0
    n = int(sample_count) if (sample_count is not None and isinstance(sample_count, int) and not isinstance(sample_count, bool) and sample_count > 0) else 10

    with _lock:
        _latest_vpin = vp
        _latest_bucket_imbalance = b_imb

        # Condition 2: Acute Single-Bucket Toxicity Spike
        if b_imb >= ACUTE_BUCKET_IMBALANCE:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 1: Elevated Flow Toxicity Persistence
        if vp >= MAX_VPIN and n >= MIN_BUCKETS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_trade(
    sign: int,
    volume: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest a trade sign (+1 buy, -1 sell) and volume in lots, update volume buckets.
    """
    global _curr_buy_vol, _curr_sell_vol, _curr_bucket_start_ts
    global _latest_vpin, _latest_bucket_imbalance, _blocked_until

    if not (_is_valid_numeric(sign) and _is_valid_positive(volume)):
        return

    s_val = int(sign)
    if s_val == 0:
        return
    is_buy = s_val > 0

    rem_vol = float(volume)
    now = float(ts) if (ts is not None and _is_valid_numeric(ts)) else time.time()

    with _lock:
        if _curr_bucket_start_ts is None:
            _curr_bucket_start_ts = now

        while rem_vol > 0.0:
            curr_total = _curr_buy_vol + _curr_sell_vol
            space = BUCKET_VOLUME - curr_total

            if rem_vol < space:
                if is_buy:
                    _curr_buy_vol += rem_vol
                else:
                    _curr_sell_vol += rem_vol
                rem_vol = 0.0
            else:
                # Complete current bucket
                if is_buy:
                    _curr_buy_vol += space
                else:
                    _curr_sell_vol += space
                rem_vol -= space

                # Evaluate completed bucket
                bucket_duration = max(0.001, now - _curr_bucket_start_ts)
                imb = abs(_curr_buy_vol - _curr_sell_vol)
                imb_frac = imb / BUCKET_VOLUME
                _latest_bucket_imbalance = imb_frac
                _bucket_imbalances.append(imb)

                # Condition 2: Acute Single-Bucket Toxicity Spike
                if imb_frac >= ACUTE_BUCKET_IMBALANCE and bucket_duration <= ACUTE_BUCKET_TIME_SEC:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                    # Reset bucket accumulator
                    _curr_buy_vol = 0.0
                    _curr_sell_vol = 0.0
                    _curr_bucket_start_ts = now
                    return

                # Calculate rolling VPIN
                if len(_bucket_imbalances) >= MIN_BUCKETS:
                    total_imb = sum(_bucket_imbalances)
                    vpin = total_imb / (len(_bucket_imbalances) * BUCKET_VOLUME)
                    _latest_vpin = vpin

                    # Condition 1: Elevated Flow Toxicity Persistence
                    if vpin >= MAX_VPIN:
                        _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                        _curr_buy_vol = 0.0
                        _curr_sell_vol = 0.0
                        _curr_bucket_start_ts = now
                        return

                # Reset for next bucket
                _curr_buy_vol = 0.0
                _curr_sell_vol = 0.0
                _curr_bucket_start_ts = now


def update(
    sign: int,
    volume: float = 1.0,
    ts: Optional[float] = None,
) -> None:
    """Module alias for record_trade."""
    record_trade(sign, volume, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if entry is currently blocked by VPIN guard."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked."""
    return is_entry_blocked()


def get_vpin_metrics() -> Dict[str, Any]:
    """Return dictionary of current VPIN and bucket imbalance metrics."""
    with _lock:
        return {
            "vpin": round(_latest_vpin, 4),
            "latest_bucket_imbalance": round(_latest_bucket_imbalance, 4),
            "completed_buckets": len(_bucket_imbalances),
            "bucket_volume": BUCKET_VOLUME,
            "window_buckets": WINDOW_BUCKETS,
            "min_buckets": MIN_BUCKETS,
            "max_vpin": MAX_VPIN,
            "acute_bucket_imbalance": ACUTE_BUCKET_IMBALANCE,
            "is_blocked": is_entry_blocked(),
        }


def get_status() -> Dict[str, Any]:
    """Return complete status dictionary."""
    with _lock:
        remaining_cd = max(0.0, _blocked_until - time.monotonic())
        metrics = get_vpin_metrics()
        metrics["cooldown_remaining_sec"] = round(remaining_cd, 2)
        return metrics


def reset() -> None:
    """Reset all state to initial defaults."""
    global _bucket_imbalances, _curr_buy_vol, _curr_sell_vol
    global _curr_bucket_start_ts, _latest_vpin, _latest_bucket_imbalance, _blocked_until
    with _lock:
        _bucket_imbalances.clear()
        _curr_buy_vol = 0.0
        _curr_sell_vol = 0.0
        _curr_bucket_start_ts = None
        _latest_vpin = 0.30
        _latest_bucket_imbalance = 0.0
        _blocked_until = 0.0
