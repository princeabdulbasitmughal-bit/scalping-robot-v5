"""
wave276_lob_cross_level_liquidity_gradient_guard.py
---------------------------------------------------
Guard: LOB Cross-Level Liquidity Gradient Asymmetry & Book Steepness Guard

Monitors multi-tier order book depth slopes, liquidity gradient asymmetry, and directional steepness disparity
(Biais et al. 1995; Potters & Bouchaud 2003; Gould et al. 2013):
    Bid / Ask Depth Gradient:  G_{bid} = (Q_{bid,3} - Q_{bid,1}) / max(P_{bid,1} - P_{bid,3}, 0.10) (lots/pt)
                                G_{ask} = (Q_{ask,3} - Q_{ask,1}) / max(P_{ask,3} - P_{ask,1}, 0.10) (lots/pt)
    Gradient Asymmetry:         \\Gamma_{asym} = (G_{bid} - G_{ask}) / (G_{bid} + G_{ask} + 10^{-4}) in [-1.0, 1.0]
    Acute Gradient Freeze:      min(G_{bid}, G_{ask}) <= 0.10 AND max(G_{bid}, G_{ask}) >= 8.0 (ratio >= 80x)

Under balanced double-auction conditions:
    - Limit order queues deepen symmetrically on both sides as price moves away from mid: |\\Gamma_{asym}| <= 0.40.
    - Liquidity resistance is balanced across buyer and seller flanks.

During directional order book manipulation, queue cliff layering, or asymmetric inventory defense:
    - One flank steepens heavily while the opposite flank flattens into a vacuum:
        1) Severe Cross-Level Gradient Asymmetry:
           Rolling mean |\\bar{\\Gamma}_{asym}| >= MAX_GRADIENT_ASYMMETRY (default: 0.78) with combined depth
           Q_{total} >= MIN_COMBINED_DEPTH (6.0 lots) over N >= MIN_SAMPLES (12 observations).
        2) Acute Flank Gradient Freeze:
           One side gradient <= ACUTE_FLANK_MIN (0.10) while opposite gradient >= ACUTE_FLANK_MAX (8.0).

Placing orders into an asymmetric liquidity gradient results in severe one-sided execution slippage
and predatory adverse queue traps.

When severe gradient asymmetry or an acute gradient freeze is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests gradients via record_level_gradients(grad_bid, grad_ask, total_depth=None, ts=None) or
  direct asymmetry via record_gradient_asymmetry(asymmetry, total_depth=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 20 gradient observations.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative gradients are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_level_gradients(grad_bid, grad_ask, total_depth=None, ts=None)                         -> None
  record_gradient_asymmetry(asymmetry, total_depth=None, ts=None)                              -> None
  update(grad_bid, grad_ask=None, total_depth=None, ts=None)                                   -> None   (alias)
  get_gradient_metrics()                                                                       -> dict
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
MAX_GRADIENT_ASYMMETRY: float = 0.78    # 78% gradient asymmetry threshold
MIN_COMBINED_DEPTH: float = 6.0         # 6.0 lots minimum combined depth for condition 1
ACUTE_FLANK_MIN: float = 0.10           # 0.10 lots/pt acute flattened flank floor
ACUTE_FLANK_MAX: float = 8.00           # 8.00 lots/pt acute heavy flank ceiling
COOLDOWN_SECONDS: float = 45.0          # 45.0s block duration

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_asymmetry_history: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_latest_asymmetry: float = 0.0
_latest_grad_bid: float = 3.0
_latest_grad_ask: float = 3.0
_latest_total_depth: float = 10.0
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


def record_gradient_asymmetry(
    asymmetry: float,
    total_depth: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Directly ingest precomputed gradient asymmetry ratio and combined depth.
    """
    global _latest_asymmetry, _latest_total_depth, _blocked_until

    if not _is_valid_numeric(asymmetry):
        return

    a = max(-1.0, min(1.0, float(asymmetry)))
    tot = float(total_depth) if (total_depth is not None and _is_valid_non_negative(total_depth)) else 10.0

    with _lock:
        _latest_asymmetry = a
        _latest_total_depth = tot

        _asymmetry_history.append(a)

        # Condition 1: Severe Cross-Level Gradient Asymmetry
        if len(_asymmetry_history) >= MIN_SAMPLES:
            mean_a = statistics.mean(_asymmetry_history)
            if abs(mean_a) >= MAX_GRADIENT_ASYMMETRY and tot >= MIN_COMBINED_DEPTH:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return


def record_level_gradients(
    grad_bid: float,
    grad_ask: float,
    total_depth: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest bid and ask liquidity gradients, calculate gradient asymmetry.
    """
    global _latest_grad_bid, _latest_grad_ask, _latest_asymmetry, _latest_total_depth, _blocked_until

    if not (_is_valid_non_negative(grad_bid) and _is_valid_non_negative(grad_ask)):
        return

    gb = float(grad_bid)
    ga = float(grad_ask)
    tot = float(total_depth) if (total_depth is not None and _is_valid_non_negative(total_depth)) else 10.0

    denom = gb + ga + 1e-4
    asym = (gb - ga) / denom

    with _lock:
        _latest_grad_bid = gb
        _latest_grad_ask = ga
        _latest_asymmetry = asym
        _latest_total_depth = tot

        # Condition 2: Acute Flank Gradient Freeze
        if (gb <= ACUTE_FLANK_MIN and ga >= ACUTE_FLANK_MAX) or (ga <= ACUTE_FLANK_MIN and gb >= ACUTE_FLANK_MAX):
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        _asymmetry_history.append(asym)

        # Condition 1: Severe Cross-Level Gradient Asymmetry
        if len(_asymmetry_history) >= MIN_SAMPLES:
            mean_a = statistics.mean(_asymmetry_history)
            if abs(mean_a) >= MAX_GRADIENT_ASYMMETRY and tot >= MIN_COMBINED_DEPTH:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return


def update(
    grad_bid: float,
    grad_ask: Optional[float] = None,
    total_depth: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """Module alias for record_level_gradients or record_gradient_asymmetry."""
    if grad_ask is None:
        record_gradient_asymmetry(grad_bid, total_depth=total_depth, ts=ts)
    else:
        record_level_gradients(grad_bid, grad_ask, total_depth=total_depth, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if entry is currently blocked by gradient asymmetry guard."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked."""
    return is_entry_blocked()


def get_gradient_metrics() -> Dict[str, Any]:
    """Return dictionary of current gradient asymmetry metrics."""
    with _lock:
        mean_a = statistics.mean(_asymmetry_history) if _asymmetry_history else 0.0
        return {
            "latest_asymmetry": round(_latest_asymmetry, 4),
            "mean_asymmetry": round(mean_a, 4),
            "latest_grad_bid": round(_latest_grad_bid, 4),
            "latest_grad_ask": round(_latest_grad_ask, 4),
            "latest_total_depth": round(_latest_total_depth, 4),
            "sample_count": len(_asymmetry_history),
            "max_gradient_asymmetry": MAX_GRADIENT_ASYMMETRY,
            "min_combined_depth": MIN_COMBINED_DEPTH,
            "is_blocked": is_entry_blocked(),
        }


def get_status() -> Dict[str, Any]:
    """Return complete status dictionary."""
    with _lock:
        remaining_cd = max(0.0, _blocked_until - time.monotonic())
        metrics = get_gradient_metrics()
        metrics["cooldown_remaining_sec"] = round(remaining_cd, 2)
        return metrics


def reset() -> None:
    """Reset all state to initial defaults."""
    global _asymmetry_history, _latest_asymmetry, _latest_grad_bid
    global _latest_grad_ask, _latest_total_depth, _blocked_until
    with _lock:
        _asymmetry_history.clear()
        _latest_asymmetry = 0.0
        _latest_grad_bid = 3.0
        _latest_grad_ask = 3.0
        _latest_total_depth = 10.0
        _blocked_until = 0.0
