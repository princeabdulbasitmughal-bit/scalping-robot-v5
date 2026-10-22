"""
wave238_effective_quoted_spread_wedge_guard.py
------------------------------------------------
Guard: Effective vs Quoted Spread Wedge & Outside-Quote Trade Distortion Guard

Monitors execution dislocation between effective spread and quoted spread
(Lee & Ready 1991; Bessembinder 2003; Boehmer et al. 2005):
    Midpoint Price:        P_{mid} = (P_{bid} + P_{ask}) / 2
    Quoted Spread (bps):   S_{quoted} = ((P_{ask} - P_{bid}) / P_{mid}) * 10^4
    Effective Spread (bps):S_{eff} = (2 * |P_{trade} - P_{mid}| / P_{mid}) * 10^4
    Spread Wedge (bps):    W_{spread} = S_{eff} - S_{quoted}

Under orderly continuous double-auction market conditions:
    - Normal trades execute at or inside the quoted touch:
      P_{bid} <= P_{trade} <= P_{ask}  =>  S_{eff} <= S_{quoted}  =>  W_{spread} <= 0.
    - Inside-quote trades (price improvement / dark liquidity / midpoint crosses):
      W_{spread} < 0.

During acute liquidity vacuums, intermarket sweep orders (ISO), latency arbitrage,
or predatory book-clearing sweeps:
    - Fills occur beyond the best bid or best ask (outside-quote trades):
      P_{trade} > P_{ask} or P_{trade} < P_{bid}  =>  S_{eff} > S_{quoted}  =>  W_{spread} > 0.
    - Systematic outside-quote execution indicates severe adverse selection, quote stale lag,
      or aggressive predatory sweeps consuming multiple book levels.

Trip Conditions:
    1) Sustained Outside-Quote Wedge Dislocation:
       Mean wedge over rolling N=20 window (minimum N >= 10):
       \\bar{W}_{spread} >= MAX_MEAN_WEDGE_BPS (default: 1.50 bps) AND
       Outside-quote trade ratio R_{outside} >= MAX_OUTSIDE_RATIO (default: 0.50 or 50%).
    2) Single Extreme Trade Blowout:
       Single trade wedge W_{spread} >= MAX_SINGLE_WEDGE_BPS (default: 4.0 bps).

When sustained wedge dislocation or single-trade blowout is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade execution vs prevailing quote via record_trade_execution(trade_price, bid_price, ask_price, ts=None).
- Maintains rolling history of WINDOW_SIZE = 20 trade executions.
- Minimum MIN_SAMPLES = 10 trades required for rolling window trip evaluation.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive prices, or inverted quotes (bid >= ask) are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade_execution(trade_price, bid_price, ask_price, ts=None)                          -> None
  update(trade_price, bid_price, ask_price, ts=None)                                          -> None   (alias)
  get_spread_metrics()                                                                         -> dict
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
WINDOW_SIZE: int = 20
MIN_SAMPLES: int = 10
MAX_MEAN_WEDGE_BPS: float = 1.50       # Mean wedge >= 1.50 bps
MAX_OUTSIDE_RATIO: float = 0.50        # Outside-quote trade ratio >= 50%
MAX_SINGLE_WEDGE_BPS: float = 4.00     # Single trade blowout >= 4.00 bps
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_trades_history = collections.deque(maxlen=WINDOW_SIZE)  # stores dict(wedge_bps=..., is_outside=...)
_latest_quoted_spread_bps: float = 0.0
_latest_effective_spread_bps: float = 0.0
_latest_wedge_bps: float = 0.0
_latest_mean_wedge_bps: float = 0.0
_latest_outside_ratio: float = 0.0
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


def record_trade_execution(
    trade_price: float,
    bid_price: float,
    ask_price: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest a trade execution price and prevailing top-of-book bid and ask.
    Computes quoted spread, effective spread, and spread wedge.
    """
    global _latest_quoted_spread_bps, _latest_effective_spread_bps, _latest_wedge_bps
    global _latest_mean_wedge_bps, _latest_outside_ratio, _blocked_until

    # Validate inputs
    if not (
        _is_valid_positive(trade_price)
        and _is_valid_positive(bid_price)
        and _is_valid_positive(ask_price)
    ):
        return

    tp = float(trade_price)
    bp = float(bid_price)
    ap = float(ask_price)

    # Inverted or crossed market guard
    if bp >= ap:
        return

    mid = (bp + ap) / 2.0
    if mid <= 0.0:
        return

    # Spreads in basis points (1 bp = 0.01% = 1e-4)
    quoted_spread_bps = ((ap - bp) / mid) * 10000.0
    effective_spread_bps = (2.0 * abs(tp - mid) / mid) * 10000.0
    wedge_bps = effective_spread_bps - quoted_spread_bps
    is_outside = (tp < bp) or (tp > ap)

    with _lock:
        _latest_quoted_spread_bps = quoted_spread_bps
        _latest_effective_spread_bps = effective_spread_bps
        _latest_wedge_bps = wedge_bps

        # Record trade in window
        _trades_history.append({"wedge_bps": wedge_bps, "is_outside": is_outside})

        n = len(_trades_history)
        mean_wedge = sum(t["wedge_bps"] for t in _trades_history) / n
        outside_count = sum(1 for t in _trades_history if t["is_outside"])
        outside_ratio = outside_count / n

        _latest_mean_wedge_bps = mean_wedge
        _latest_outside_ratio = outside_ratio

        # Condition 1: Single extreme trade blowout
        if wedge_bps >= MAX_SINGLE_WEDGE_BPS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 2: Sustained outside-quote wedge dislocation
        if n >= MIN_SAMPLES:
            if mean_wedge >= MAX_MEAN_WEDGE_BPS and outside_ratio >= MAX_OUTSIDE_RATIO:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return


def update(
    trade_price: float,
    bid_price: float,
    ask_price: float,
    ts: Optional[float] = None,
) -> None:
    """Alias for record_trade_execution()."""
    record_trade_execution(trade_price, bid_price, ask_price, ts)


def is_entry_blocked() -> bool:
    """Check if new entries are blocked by spread wedge dislocation."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_spread_metrics() -> Dict[str, float]:
    """Retrieve current spread and wedge metrics."""
    with _lock:
        return {
            "quoted_spread_bps": _latest_quoted_spread_bps,
            "effective_spread_bps": _latest_effective_spread_bps,
            "wedge_bps": _latest_wedge_bps,
            "mean_wedge_bps": _latest_mean_wedge_bps,
            "outside_ratio": _latest_outside_ratio,
        }


def get_status() -> Dict[str, Any]:
    """Retrieve complete guard status."""
    with _lock:
        now = time.monotonic()
        blocked = now < _blocked_until
        remaining = max(0.0, _blocked_until - now) if blocked else 0.0
        return {
            "guard_name": "wave238_effective_quoted_spread_wedge_guard",
            "is_blocked": blocked,
            "blocked_seconds_remaining": remaining,
            "sample_count": len(_trades_history),
            "quoted_spread_bps": _latest_quoted_spread_bps,
            "effective_spread_bps": _latest_effective_spread_bps,
            "wedge_bps": _latest_wedge_bps,
            "mean_wedge_bps": _latest_mean_wedge_bps,
            "outside_ratio": _latest_outside_ratio,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "max_mean_wedge_bps": MAX_MEAN_WEDGE_BPS,
            "max_outside_ratio": MAX_OUTSIDE_RATIO,
            "max_single_wedge_bps": MAX_SINGLE_WEDGE_BPS,
        }


def reset() -> None:
    """Reset all guard state and clear cooldowns."""
    global _latest_quoted_spread_bps, _latest_effective_spread_bps, _latest_wedge_bps
    global _latest_mean_wedge_bps, _latest_outside_ratio, _blocked_until

    with _lock:
        _trades_history.clear()
        _latest_quoted_spread_bps = 0.0
        _latest_effective_spread_bps = 0.0
        _latest_wedge_bps = 0.0
        _latest_mean_wedge_bps = 0.0
        _latest_outside_ratio = 0.0
        _blocked_until = 0.0
