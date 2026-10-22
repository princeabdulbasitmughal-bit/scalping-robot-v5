"""
wave219_depth_cushion_asymmetric_exhaustion_guard.py
-----------------------------------------------------
Guard: Depth Cushion & Asymmetric LOB Cushion Depletion Guard

Monitors top-of-book standing depth cushion and asymmetric liquidity exhaustion
(Cont, Stoikov & Talreja 2010; Gould et al. 2013) to protect against imminent barrier
breaches and one-sided order book vacuum runs:
    Baseline Depth:       Q_{bar, bid} = mean(Q_{bid, 1..N}),  Q_{bar, ask} = mean(Q_{ask, 1..N})
    Depth Cushion Ratio:  C_{bid} = Q_{bid} / max(0.1, Q_{bar, bid})
                          C_{ask} = Q_{ask} / max(0.1, Q_{bar, ask})

In stable, healthy double-auction markets:
    - Both sides maintain balanced cushions: C_{bid} ~ 1.0, C_{ask} ~ 1.0.
    - Temporary dips are quickly replenished by market makers.

During impending level breakouts, stop runs, or predatory absorption:
    - Standing liquidity on one side completely evaporates while the opposite side remains saturated.
    - Asymmetric Cushion Collapse:
        1) One side is severely depleted:
           C_{depleted} <= MIN_CUSHION_RATIO (default: 0.15, meaning depth is <= 15% of recent mean).
        2) The opposite side is fully stocked:
           C_{opposite} >= OPPOSITE_HEALTHY_RATIO (default: 0.80).
        3) Baseline depth was meaningful:
           Q_{bar} >= MIN_BASELINE_DEPTH (default: 5.0 lots).
    - Bilateral Vacuum Shock:
        Both C_{bid} <= 0.10 and C_{ask} <= 0.10 (flash order book vacuum).

Submitting market orders or posting passive limit orders on the depleted side guarantees
instant level breakage, catastrophic slippage, and execution adverse selection.

When asymmetric depth cushion exhaustion is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests top-of-book updates via record_book(bid_price, bid_depth, ask_price, ask_depth, ts=None).
- Maintains rolling window of WINDOW_SIZE = 30 depth snapshots.
- Requires MIN_SAMPLES = 15 snapshots before calculating baseline.
- Computes C_{bid} and C_{ask}.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, negative depths, or inverted prices are rejected.

Aliases (required):
  is_entry_blocked()                                                  -> bool
  is_blocked()                                                        -> bool   (alias)
  record_book(bid_price, bid_depth, ask_price, ask_depth, ts=None)    -> None
  update(bid_price, bid_depth, ask_price, ask_depth, ts=None)         -> None   (alias)
  get_cushion_metrics()                                               -> dict
  get_status()                                                        -> dict
  reset()                                                             -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 30
MIN_SAMPLES: int = 15
MIN_CUSHION_RATIO: float = 0.15           # <= 15% of baseline depth is considered exhausted
OPPOSITE_HEALTHY_RATIO: float = 0.80      # >= 80% on opposite side proves extreme asymmetry
MIN_BASELINE_DEPTH: float = 5.0           # 5.0 lots minimum baseline to prevent penny-stock noise
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_bid_depths = collections.deque(maxlen=WINDOW_SIZE)
_ask_depths = collections.deque(maxlen=WINDOW_SIZE)
_latest_bid_cushion: float = 1.0
_latest_ask_cushion: float = 1.0
_latest_mean_bid_depth: float = 0.0
_latest_mean_ask_depth: float = 0.0
_blocked_until: float = 0.0


def _is_valid_price(val: Any) -> bool:
    """Validate price is a positive finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val > 0.0


def _is_valid_depth(val: Any) -> bool:
    """Validate depth is a non-negative finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val >= 0.0


def record_book(
    bid_price: float,
    bid_depth: float,
    ask_price: float,
    ask_depth: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest a top-of-book snapshot and evaluate standing depth cushion exhaustion.
    """
    global _latest_bid_cushion, _latest_ask_cushion
    global _latest_mean_bid_depth, _latest_mean_ask_depth, _blocked_until

    if not _is_valid_price(bid_price) or not _is_valid_price(ask_price):
        return
    if not _is_valid_depth(bid_depth) or not _is_valid_depth(ask_depth):
        return
    if float(ask_price) <= float(bid_price):
        return

    bq = float(bid_depth)
    aq = float(ask_depth)

    with _lock:
        _bid_depths.append(bq)
        _ask_depths.append(aq)

        n = len(_bid_depths)
        if n < MIN_SAMPLES:
            return

        mean_bid_q = sum(_bid_depths) / float(n)
        mean_ask_q = sum(_ask_depths) / float(n)

        _latest_mean_bid_depth = mean_bid_q
        _latest_mean_ask_depth = mean_ask_q

        cushion_bid = bq / max(0.1, mean_bid_q)
        cushion_ask = aq / max(0.1, mean_ask_q)

        _latest_bid_cushion = cushion_bid
        _latest_ask_cushion = cushion_ask

        # Condition 1: Asymmetric Bid Exhaustion (bid barrier failing)
        if (
            cushion_bid <= MIN_CUSHION_RATIO
            and cushion_ask >= OPPOSITE_HEALTHY_RATIO
            and mean_bid_q >= MIN_BASELINE_DEPTH
        ):
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 2: Asymmetric Ask Exhaustion (ask barrier failing)
        if (
            cushion_ask <= MIN_CUSHION_RATIO
            and cushion_bid >= OPPOSITE_HEALTHY_RATIO
            and mean_ask_q >= MIN_BASELINE_DEPTH
        ):
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 3: Flash bilateral vacuum shock
        if (
            cushion_bid <= 0.10
            and cushion_ask <= 0.10
            and (mean_bid_q >= MIN_BASELINE_DEPTH or mean_ask_q >= MIN_BASELINE_DEPTH)
        ):
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(
    bid_price: float,
    bid_depth: float,
    ask_price: float,
    ask_depth: float,
    ts: Optional[float] = None,
) -> None:
    """Alias for record_book()."""
    record_book(bid_price, bid_depth, ask_price, ask_depth, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to depth cushion exhaustion."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_cushion_metrics() -> Dict[str, float]:
    """Return latest calculated bid/ask depth cushions and mean baseline depths."""
    with _lock:
        return {
            "bid_cushion": _latest_bid_cushion,
            "ask_cushion": _latest_ask_cushion,
            "mean_bid_depth": _latest_mean_bid_depth,
            "mean_ask_depth": _latest_mean_ask_depth,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the depth cushion exhaustion guard."""
    with _lock:
        now = time.monotonic()
        return {
            "bid_cushion": _latest_bid_cushion,
            "ask_cushion": _latest_ask_cushion,
            "mean_bid_depth": _latest_mean_bid_depth,
            "mean_ask_depth": _latest_mean_ask_depth,
            "sample_count": len(_bid_depths),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "min_cushion_ratio": MIN_CUSHION_RATIO,
            "opposite_healthy_ratio": OPPOSITE_HEALTHY_RATIO,
            "min_baseline_depth": MIN_BASELINE_DEPTH,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset depth histories, cushion metrics, and active cooldown blocks."""
    global _latest_bid_cushion, _latest_ask_cushion
    global _latest_mean_bid_depth, _latest_mean_ask_depth, _blocked_until
    with _lock:
        _bid_depths.clear()
        _ask_depths.clear()
        _latest_bid_cushion = 1.0
        _latest_ask_cushion = 1.0
        _latest_mean_bid_depth = 0.0
        _latest_mean_ask_depth = 0.0
        _blocked_until = 0.0
