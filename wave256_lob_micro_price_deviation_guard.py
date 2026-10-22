"""
wave256_lob_micro_price_deviation_guard.py
--------------------------------------------
Guard: Order Book Micro-Price Deviation & Fair Value Drift Guard

Monitors short-term fair value micro-price displacement relative to the simple midpoint
(Stoikov 2018):
    Simple Midpoint:         P_{mid} = (P_{bid} + P_{ask}) / 2
    Stoikov Micro-Price:     P_{micro} = (Q_{bid} * P_{ask} + Q_{ask} * P_{bid}) / (Q_{bid} + Q_{ask})
    Micro-Price Drift (bps): \\delta_{micro} = ((P_{micro} - P_{mid}) / P_{mid}) * 10^4

Under balanced, symmetrical continuous double-auction conditions:
    - Top-of-book depths are balanced: Q_{bid} ~ Q_{ask}
    - Micro-price coincides with the simple mid-price: |\\delta_{micro}| <= 0.50 bps.

During aggressive predatory book tilting, queue exhaustion, or impending price jumps:
    - Micro-price strongly pulls toward the thinner side, forecasting an imminent step:
        1) Severe Micro-Price Fair Value Displacement:
           |\\delta_{micro}| >= MAX_MICRO_DEVIATION_BPS (default: 1.50 bps) AND
           (Q_{bid} + Q_{ask}) >= MIN_COMBINED_DEPTH (default: 4.0 lots).
        2) Acute Micro-Price Displacement Spike:
           |\\delta_{micro}| >= MAX_ACUTE_SPIKE_BPS (default: 2.50 bps).

Attempting to fade or trade against strong micro-price deviations results in
immediate price-step slippage, adverse fill selection, and negative alpha.

When micro-price displacement or acute spike is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests quote depths via record_quote_depths(bid_price, ask_price, bid_depth, ask_depth, ts=None) or
  direct deviation via record_micro_deviation(deviation_bps, total_depth=None, ts=None).
- Calculates micro-price P_{micro} and basis-point deviation \\delta_{micro}.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive prices/depths, or crossed quotes (bid >= ask) are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_quote_depths(bid_price, ask_price, bid_depth, ask_depth, ts=None)                     -> None
  record_micro_deviation(deviation_bps, total_depth=None, ts=None)                             -> None
  update(bid_price, ask_price=None, bid_depth=None, ask_depth=None, ts=None)                   -> None   (alias)
  get_micro_price_metrics()                                                                    -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import math
import threading
import time
from typing import Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_MICRO_DEVIATION_BPS: float = 1.50  # 1.50 bps fair value deviation from midpoint
MIN_COMBINED_DEPTH: float = 4.00       # 4.00 lots minimum combined depth
MAX_ACUTE_SPIKE_BPS: float = 2.50      # 2.50 bps acute deviation spike
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_latest_mid_price: float = 2000.0
_latest_micro_price: float = 2000.0
_latest_deviation_bps: float = 0.0
_latest_total_depth: float = 10.0
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


def record_micro_deviation(
    deviation_bps: float,
    total_depth: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Directly ingest precomputed micro-price deviation in basis points.
    """
    global _latest_deviation_bps, _latest_total_depth, _blocked_until

    if not _is_valid_numeric(deviation_bps):
        return

    dev = float(deviation_bps)
    tot = float(total_depth) if (total_depth is not None and _is_valid_positive(total_depth)) else 10.0

    with _lock:
        _latest_deviation_bps = dev
        _latest_total_depth = tot

        # Condition 1: Acute micro-price displacement spike
        if abs(dev) >= MAX_ACUTE_SPIKE_BPS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 2: Severe fair value displacement with sufficient depth
        if abs(dev) >= MAX_MICRO_DEVIATION_BPS and tot >= MIN_COMBINED_DEPTH:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_quote_depths(
    bid_price: float,
    ask_price: float,
    bid_depth: float,
    ask_depth: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest top-of-book bid/ask prices and depths, calculate Stoikov micro-price and deviation.
    """
    global _latest_mid_price, _latest_micro_price

    if not (
        _is_valid_positive(bid_price)
        and _is_valid_positive(ask_price)
        and _is_valid_positive(bid_depth)
        and _is_valid_positive(ask_depth)
    ):
        return

    bp = float(bid_price)
    ap = float(ask_price)
    bq = float(bid_depth)
    aq = float(ask_depth)

    # Inverted or crossed quote
    if bp >= ap:
        return

    mid = (bp + ap) / 2.0
    tot_depth = bq + aq
    if mid <= 0.0 or tot_depth <= 0.0:
        return

    micro = (bq * ap + aq * bp) / tot_depth
    dev_bps = ((micro - mid) / mid) * 10000.0

    with _lock:
        _latest_mid_price = mid
        _latest_micro_price = micro

    record_micro_deviation(dev_bps, total_depth=tot_depth, ts=ts)


def update(
    bid_price: float,
    ask_price: Optional[float] = None,
    bid_depth: Optional[float] = None,
    ask_depth: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Flexible alias:
    If 4 arguments provided, calls record_quote_depths().
    If single argument provided, calls record_micro_deviation().
    """
    if ask_price is not None and bid_depth is not None and ask_depth is not None:
        record_quote_depths(bid_price, ask_price, bid_depth, ask_depth, ts)
    else:
        record_micro_deviation(bid_price, ts=ts)


def is_entry_blocked() -> bool:
    """Check if new entries are blocked by micro-price deviation."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_micro_price_metrics() -> Dict[str, float]:
    """Retrieve current micro-price metrics."""
    with _lock:
        return {
            "mid_price": _latest_mid_price,
            "micro_price": _latest_micro_price,
            "deviation_bps": _latest_deviation_bps,
            "total_depth": _latest_total_depth,
        }


def get_status() -> Dict[str, Any]:
    """Retrieve complete guard status."""
    with _lock:
        now = time.monotonic()
        blocked = now < _blocked_until
        remaining = max(0.0, _blocked_until - now) if blocked else 0.0
        return {
            "guard_name": "wave256_lob_micro_price_deviation_guard",
            "is_blocked": blocked,
            "blocked_seconds_remaining": remaining,
            "mid_price": _latest_mid_price,
            "micro_price": _latest_micro_price,
            "deviation_bps": _latest_deviation_bps,
            "total_depth": _latest_total_depth,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "max_micro_deviation_bps": MAX_MICRO_DEVIATION_BPS,
            "min_combined_depth": MIN_COMBINED_DEPTH,
            "max_acute_spike_bps": MAX_ACUTE_SPIKE_BPS,
        }


def reset() -> None:
    """Reset all guard state and clear cooldowns."""
    global _latest_mid_price, _latest_micro_price, _latest_deviation_bps
    global _latest_total_depth, _blocked_until

    with _lock:
        _latest_mid_price = 2000.0
        _latest_micro_price = 2000.0
        _latest_deviation_bps = 0.0
        _latest_total_depth = 10.0
        _blocked_until = 0.0
