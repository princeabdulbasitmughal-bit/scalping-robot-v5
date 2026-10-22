"""
wave260_lob_slope_decay_elasticity_guard.py
--------------------------------------------
Guard: LOB Slope Decay & Price-Impact Elasticity Guard

Monitors order book slope degradation and price-impact elasticity under high-frequency tick transitions
(Bouchaud et al. 2004; Farmer et al. 2004; Gould et al. 2013):
    Spread (bps):               S_{bps} = ((P_{ask} - P_{bid}) / P_{mid}) * 10^4
    Total Depth:                Q_{total} = Q_{bid} + Q_{ask}
    Book Slope:                 Slope = Q_{total} / max(S_{bps}, 0.10)  (lots / bps)
    Price-Impact Elasticity:    E_{impact} = (Delta P_{mid, bps}) / max(|Delta Q_{total}| / Q_{total-1}, 0.01)

Under robust continuous double-auction liquidity provision:
    - Order book depth is deep relative to the bid-ask spread: Slope is high (e.g. >= 2.0 lots/bps).
    - Elasticity is subdued: E_{impact} <= 1.20 (small price reaction to fractional depth deltas).

During liquidity withdrawal, phantom quote fading, or predatory depth evacuation:
    - Order book slope collapses and impact elasticity spikes:
        1) Elevated Price-Impact Elasticity Persistence:
           Rolling mean \\bar{E}_{impact} >= MAX_MEAN_ELASTICITY (default: 2.20) over N >= MIN_SAMPLES (12 ticks).
        2) Acute Order Book Slope Collapse:
           Slope <= MIN_ACUTE_SLOPE (default: 0.50 lots/bps) with spread expansion S_{bps} >= MIN_SPREAD_BPS (2.50 bps).

Executing orders into an elastic, low-slope order book produces extreme market impact, slippage,
and negative fill selection.

When excessive impact elasticity or acute slope collapse is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests quotes via record_quote(bid_price, ask_price, bid_depth, ask_depth, ts=None) or
  elasticity via record_elasticity(elasticity, slope=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 20 elasticity observations.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive prices/depths, or crossed quotes (bid >= ask) are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_quote(bid_price, ask_price, bid_depth, ask_depth, ts=None)                            -> None
  record_elasticity(elasticity, slope=None, ts=None)                                           -> None
  update(bid_price, ask_price=None, bid_depth=None, ask_depth=None, ts=None)                   -> None   (alias)
  get_elasticity_metrics()                                                                     -> dict
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
MIN_SAMPLES: int = 12                   # Minimum 12 observations for mean elasticity
MAX_MEAN_ELASTICITY: float = 2.20       # 2.20 maximum acceptable mean price-impact elasticity
MIN_ACUTE_SLOPE: float = 0.50           # 0.50 lots/bps minimum acute book slope floor
MIN_SPREAD_BPS: float = 2.50            # 2.50 bps minimum spread for acute slope condition
COOLDOWN_SECONDS: float = 45.0          # 45.0s block duration

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_elasticity_history: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_prev_mid_price: Optional[float] = None
_prev_total_depth: Optional[float] = None
_latest_elasticity: float = 0.0
_latest_slope: float = 5.0
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


def record_elasticity(
    elasticity: float,
    slope: Optional[float] = None,
    spread_bps: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Directly ingest precomputed price-impact elasticity and book slope.
    """
    global _latest_elasticity, _latest_slope, _latest_spread_bps, _blocked_until

    if not _is_valid_numeric(elasticity):
        return

    e = float(elasticity)
    s = float(slope) if (slope is not None and _is_valid_positive(slope)) else 5.0
    sp = float(spread_bps) if (spread_bps is not None and _is_valid_positive(spread_bps)) else 1.0

    with _lock:
        _latest_elasticity = e
        _latest_slope = s
        _latest_spread_bps = sp

        # Condition 2: Acute Order Book Slope Collapse
        if s <= MIN_ACUTE_SLOPE and sp >= MIN_SPREAD_BPS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        _elasticity_history.append(e)

        # Condition 1: Elevated Price-Impact Elasticity Persistence
        if len(_elasticity_history) >= MIN_SAMPLES:
            mean_e = statistics.mean(_elasticity_history)
            if mean_e >= MAX_MEAN_ELASTICITY:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return


def record_quote(
    bid_price: float,
    ask_price: float,
    bid_depth: float,
    ask_depth: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest top-of-book bid/ask quotes and depths, compute slope and price-impact elasticity.
    """
    global _prev_mid_price, _prev_total_depth, _latest_elasticity, _latest_slope, _latest_spread_bps, _blocked_until

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

    # Reject crossed or inverted quote
    if bp >= ap:
        return

    mid = (bp + ap) / 2.0
    spread_pts = ap - bp
    if mid <= 0.0:
        return

    spread_bps = (spread_pts / mid) * 10000.0
    total_depth = bq + aq
    slope = total_depth / max(spread_bps, 0.10)

    with _lock:
        _latest_slope = slope
        _latest_spread_bps = spread_bps

        # Acute slope collapse check
        if slope <= MIN_ACUTE_SLOPE and spread_bps >= MIN_SPREAD_BPS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        if _prev_mid_price is not None and _prev_total_depth is not None:
            # Calculate price return and depth delta
            d_mid_bps = (abs(mid - _prev_mid_price) / _prev_mid_price) * 10000.0
            frac_d_depth = abs(total_depth - _prev_total_depth) / max(_prev_total_depth, 0.10)
            elasticity = d_mid_bps / max(frac_d_depth, 0.05)
            _latest_elasticity = elasticity

            _elasticity_history.append(elasticity)
            if len(_elasticity_history) >= MIN_SAMPLES:
                mean_e = statistics.mean(_elasticity_history)
                if mean_e >= MAX_MEAN_ELASTICITY:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                    return

        _prev_mid_price = mid
        _prev_total_depth = total_depth


def update(
    bid_price: float,
    ask_price: Optional[float] = None,
    bid_depth: Optional[float] = None,
    ask_depth: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """Module alias for record_quote or record_elasticity."""
    if ask_price is None or bid_depth is None or ask_depth is None:
        record_elasticity(bid_price, ts=ts)
    else:
        record_quote(bid_price, ask_price, bid_depth, ask_depth, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if entry is currently blocked by elasticity guard."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked."""
    return is_entry_blocked()


def get_elasticity_metrics() -> Dict[str, Any]:
    """Return dictionary of current elasticity and slope metrics."""
    with _lock:
        mean_e = statistics.mean(_elasticity_history) if _elasticity_history else 0.0
        return {
            "latest_elasticity": round(_latest_elasticity, 4),
            "mean_elasticity": round(mean_e, 4),
            "sample_count": len(_elasticity_history),
            "latest_slope": round(_latest_slope, 4),
            "latest_spread_bps": round(_latest_spread_bps, 4),
            "max_mean_elasticity": MAX_MEAN_ELASTICITY,
            "min_acute_slope": MIN_ACUTE_SLOPE,
            "is_blocked": is_entry_blocked(),
        }


def get_status() -> Dict[str, Any]:
    """Return complete status dictionary."""
    with _lock:
        remaining_cd = max(0.0, _blocked_until - time.monotonic())
        metrics = get_elasticity_metrics()
        metrics["cooldown_remaining_sec"] = round(remaining_cd, 2)
        return metrics


def reset() -> None:
    """Reset all state to initial defaults."""
    global _elasticity_history, _prev_mid_price, _prev_total_depth
    global _latest_elasticity, _latest_slope, _latest_spread_bps, _blocked_until
    with _lock:
        _elasticity_history.clear()
        _prev_mid_price = None
        _prev_total_depth = None
        _latest_elasticity = 0.0
        _latest_slope = 5.0
        _latest_spread_bps = 1.0
        _blocked_until = 0.0
