"""
wave272_lob_spread_asymmetry_drift_guard.py
--------------------------------------------
Guard: LOB Bid-Ask Half-Spread Dynamic Asymmetry & Skew Drift Guard

Monitors dealer quote skewness, half-spread asymmetry relative to fair value, and directional adverse quote tilting
(Stoll 1978; Roll 1984; Amihud & Mendelson 1986):
    Simple Midpoint:            P_{mid} = (P_{bid} + P_{ask}) / 2
    Rolling Fair Value:         P* = EWMA(P_{mid}, alpha=0.10)
    Bid / Ask Half-Distance:    d_{bid} = |P* - P_{bid}|,  d_{ask} = |P_{ask} - P*|
    Half-Spread Asymmetry:      \\Sigma_{asym} = (d_{bid} - d_{ask}) / (d_{bid} + d_{ask} + 10^{-4}) in [-1.0, 1.0]
    Spread in Basis Points:     S_{bps} = ((P_{ask} - P_{bid}) / P_{mid}) * 10^4

Under balanced continuous double-auction dealer pricing:
    - Quotes are centered symmetrically around consensus fair value: |\\Sigma_{asym}| <= 0.35.
    - Dealers quote bilateral liquidity without structural directional skew.

During informed toxic positioning, inventory panic, or one-sided quote withdrawal:
    - Market makers heavily skew quote placement away from incoming toxic flow:
        1) Persistent Half-Spread Asymmetry Drift:
           Rolling mean |\\bar{\\Sigma}_{asym}| >= MAX_SPREAD_ASYMMETRY (default: 0.75) with S_{bps} >= MIN_SPREAD_BPS (2.50 bps)
           over N >= MIN_SAMPLES (12 observations).
        2) Acute Asymmetric Quote Shift:
           |\\Sigma_{asym}| >= ACUTE_ASYMMETRY_RATIO (0.90) with spread expansion S_{bps} >= ACUTE_SPREAD_BPS (3.50 bps).

Executing orders into a heavily skewed quote box results in extreme adverse fills, immediate spread
fade, and negative alpha.

When severe half-spread asymmetry or an acute quote skew shift is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests quotes via record_quote(bid_price, ask_price, fair_price=None, ts=None) or
  direct asymmetry via record_spread_asymmetry(asymmetry, spread_bps=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 20 asymmetry observations.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive prices, or crossed quotes (bid >= ask) are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_quote(bid_price, ask_price, fair_price=None, ts=None)                                 -> None
  record_spread_asymmetry(asymmetry, spread_bps=None, ts=None)                                  -> None
  update(bid_price, ask_price=None, fair_price=None, ts=None)                                  -> None   (alias)
  get_asymmetry_metrics()                                                                      -> dict
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
WINDOW_SIZE: int = 20                   # 20 observations rolling window
MIN_SAMPLES: int = 12                   # 12 observations minimum for mean evaluation
MAX_SPREAD_ASYMMETRY: float = 0.75      # 75% half-spread asymmetry threshold
MIN_SPREAD_BPS: float = 2.50            # 2.50 bps minimum spread for persistent trigger
ACUTE_ASYMMETRY_RATIO: float = 0.90     # 90% acute asymmetry threshold
ACUTE_SPREAD_BPS: float = 3.50          # 3.50 bps minimum spread for acute trigger
COOLDOWN_SECONDS: float = 45.0          # 45.0s block duration

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_asymmetry_history: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_ewma_fair_price: Optional[float] = None
_latest_asymmetry: float = 0.0
_latest_spread_bps: float = 1.0
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


def record_spread_asymmetry(
    asymmetry: float,
    spread_bps: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Directly ingest precomputed half-spread asymmetry ratio and spread in bps.
    """
    global _latest_asymmetry, _latest_spread_bps, _blocked_until

    if not _is_valid_numeric(asymmetry):
        return

    a = max(-1.0, min(1.0, float(asymmetry)))
    s = float(spread_bps) if (spread_bps is not None and _is_valid_positive(spread_bps)) else 3.0

    with _lock:
        _latest_asymmetry = a
        _latest_spread_bps = s

        # Condition 2: Acute Asymmetric Quote Shift
        if abs(a) >= ACUTE_ASYMMETRY_RATIO and s >= ACUTE_SPREAD_BPS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        _asymmetry_history.append(a)

        # Condition 1: Persistent Half-Spread Asymmetry Drift
        if len(_asymmetry_history) >= MIN_SAMPLES:
            mean_a = statistics.mean(_asymmetry_history)
            if abs(mean_a) >= MAX_SPREAD_ASYMMETRY and s >= MIN_SPREAD_BPS:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return


def record_quote(
    bid_price: float,
    ask_price: float,
    fair_price: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest bid and ask quotes, update fair price benchmark, and compute half-spread asymmetry.
    """
    global _ewma_fair_price, _latest_asymmetry, _latest_spread_bps, _blocked_until

    if not (_is_valid_positive(bid_price) and _is_valid_positive(ask_price)):
        return

    bp = float(bid_price)
    ap = float(ask_price)

    # Reject crossed or inverted quote
    if bp >= ap:
        return

    mid = (bp + ap) / 2.0
    if mid <= 0.0:
        return

    spread_pts = ap - bp
    spread_bps = (spread_pts / mid) * 10000.0

    with _lock:
        # Update or set fair price
        if fair_price is not None and _is_valid_positive(fair_price):
            p_fair = float(fair_price)
        else:
            if _ewma_fair_price is None:
                _ewma_fair_price = mid
            else:
                _ewma_fair_price = 0.10 * mid + 0.90 * _ewma_fair_price
            p_fair = _ewma_fair_price

        d_bid = abs(p_fair - bp)
        d_ask = abs(ap - p_fair)
        denom = d_bid + d_ask + 1e-4
        asym = (d_bid - d_ask) / denom

        _latest_asymmetry = asym
        _latest_spread_bps = spread_bps

        # Condition 2: Acute Asymmetric Quote Shift
        if abs(asym) >= ACUTE_ASYMMETRY_RATIO and spread_bps >= ACUTE_SPREAD_BPS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        _asymmetry_history.append(asym)

        # Condition 1: Persistent Half-Spread Asymmetry Drift
        if len(_asymmetry_history) >= MIN_SAMPLES:
            mean_a = statistics.mean(_asymmetry_history)
            if abs(mean_a) >= MAX_SPREAD_ASYMMETRY and spread_bps >= MIN_SPREAD_BPS:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return


def update(
    bid_price: float,
    ask_price: Optional[float] = None,
    fair_price: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """Module alias for record_quote or record_spread_asymmetry."""
    if ask_price is None:
        record_spread_asymmetry(bid_price, ts=ts)
    else:
        record_quote(bid_price, ask_price, fair_price=fair_price, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if entry is currently blocked by spread asymmetry guard."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked."""
    return is_entry_blocked()


def get_asymmetry_metrics() -> Dict[str, Any]:
    """Return dictionary of current spread asymmetry metrics."""
    with _lock:
        mean_a = statistics.mean(_asymmetry_history) if _asymmetry_history else 0.0
        return {
            "latest_asymmetry": round(_latest_asymmetry, 4),
            "mean_asymmetry": round(mean_a, 4),
            "sample_count": len(_asymmetry_history),
            "latest_spread_bps": round(_latest_spread_bps, 4),
            "max_spread_asymmetry": MAX_SPREAD_ASYMMETRY,
            "acute_asymmetry_ratio": ACUTE_ASYMMETRY_RATIO,
            "is_blocked": is_entry_blocked(),
        }


def get_status() -> Dict[str, Any]:
    """Return complete status dictionary."""
    with _lock:
        remaining_cd = max(0.0, _blocked_until - time.monotonic())
        metrics = get_asymmetry_metrics()
        metrics["cooldown_remaining_sec"] = round(remaining_cd, 2)
        return metrics


def reset() -> None:
    """Reset all state to initial defaults."""
    global _asymmetry_history, _ewma_fair_price, _latest_asymmetry
    global _latest_spread_bps, _blocked_until
    with _lock:
        _asymmetry_history.clear()
        _ewma_fair_price = None
        _latest_asymmetry = 0.0
        _latest_spread_bps = 1.0
        _blocked_until = 0.0
