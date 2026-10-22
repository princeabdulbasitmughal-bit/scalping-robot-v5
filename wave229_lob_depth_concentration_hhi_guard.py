"""
wave229_lob_depth_concentration_hhi_guard.py
----------------------------------------------
Guard: LOB Level Depth Concentration & Liquidity Herfindahl Deficit Guard

Monitors spatial depth concentration across order book levels and detects fragile
liquidity distribution and outer-level air pockets (Kyle 1985; Glosten 1994):
    Total Depth:           Q_{tot} = sum_{k=1}^L q_k
    Level Shares:          s_k = q_k / Q_{tot}
    Depth Herfindahl HHI:  HHI_{depth} = sum_{k=1}^L s_k^2  in [1/L, 1.0]
    Touch Dominance:       R_{touch} = q_1 / Q_{tot}

In deep, resilient, multi-level order books:
    - Liquidity is well distributed across price tiers (e.g. 5 levels with ~20% each):
      HHI_{depth} ~ 0.20, R_{touch} < 0.40.
    - Market sweeps encounter progressively denser depth barriers.

During predatory spoofing or fragile pre-gap market states:
    - Standing liquidity is monopolized at the touch while outer levels are barren:
        1) Severe Depth Concentration:
           HHI_{depth} >= MAX_DEPTH_HHI (default: 0.75) AND
           Q_{tot} >= MIN_TOTAL_DEPTH (default: 5.0 lots).
        2) Touch Dominance / Air Pocket Hazard:
           R_{touch} >= MAX_TOUCH_DOMINANCE (default: 0.85, meaning 85%+ of visible depth is at touch).

Crossing the spread or posting passive orders into a book with an outer air pocket guarantees
catastrophic multi-pip slippage if the thin touch level gets breached.

When severe depth concentration / air pocket is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests level depths via record_depth_levels(level_depths, ts=None)
  or record_book_depth_distribution(touch_depth, outer_depth, ts=None).
- Computes level shares s_k, Herfindahl index HHI_{depth}, and touch dominance R_{touch}.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative depths are rejected.

Aliases (required):
  is_entry_blocked()                                                                   -> bool
  is_blocked()                                                                         -> bool   (alias)
  record_depth_levels(level_depths, ts=None)                                           -> None
  record_book_depth_distribution(touch_depth, outer_depth, ts=None)                    -> None
  update(level_depths, ts=None)                                                        -> None   (alias)
  get_concentration_metrics()                                                          -> dict
  get_status()                                                                         -> dict
  reset()                                                                              -> None
"""

import math
import threading
import time
from typing import Dict, Optional, Any, List, Union

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_DEPTH_HHI: float = 0.75               # HHI >= 0.75 indicates extreme concentration
MAX_TOUCH_DOMINANCE: float = 0.85         # 85% of book depth concentrated at touch
MIN_TOTAL_DEPTH: float = 5.0              # 5.0 lots minimum depth to prevent penny noise
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_latest_hhi: float = 0.20
_latest_touch_ratio: float = 0.20
_latest_total_depth: float = 0.0
_latest_level_count: int = 0
_blocked_until: float = 0.0


def _is_valid_depth(val: Any) -> bool:
    """Validate depth is a non-negative finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val >= 0.0


def record_depth_levels(
    level_depths: List[float],
    ts: Optional[float] = None,
) -> None:
    """
    Ingest a list of order book level depths and evaluate Herfindahl concentration HHI.
    """
    global _latest_hhi, _latest_touch_ratio, _latest_total_depth, _latest_level_count, _blocked_until

    if not isinstance(level_depths, (list, tuple)) or not level_depths:
        return

    valid_depths = []
    for d in level_depths:
        if not _is_valid_depth(d):
            return
        valid_depths.append(float(d))

    tot_q = sum(valid_depths)
    if tot_q < 0.1:
        return

    with _lock:
        n_levels = len(valid_depths)
        touch_q = valid_depths[0]

        shares = [q / tot_q for q in valid_depths]
        hhi = sum(s * s for s in shares)
        touch_ratio = touch_q / tot_q

        _latest_hhi = hhi
        _latest_touch_ratio = touch_ratio
        _latest_total_depth = tot_q
        _latest_level_count = n_levels

        # Condition 1: Extreme Herfindahl HHI concentration
        if hhi >= MAX_DEPTH_HHI and tot_q >= MIN_TOTAL_DEPTH:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 2: Touch dominance air pocket
        if touch_ratio >= MAX_TOUCH_DOMINANCE and tot_q >= MIN_TOTAL_DEPTH:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_book_depth_distribution(
    touch_depth: float,
    outer_depth: float,
    ts: Optional[float] = None,
) -> None:
    """
    Evaluate two-tier depth distribution: touch depth vs aggregate outer book depth.
    """
    if not _is_valid_depth(touch_depth) or not _is_valid_depth(outer_depth):
        return
    record_depth_levels([touch_depth, outer_depth], ts)


def update(
    level_depths: Union[List[float], float],
    outer_depth: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """Flexible alias supporting either level list or (touch, outer) pair."""
    if isinstance(level_depths, (list, tuple)):
        record_depth_levels(level_depths, ts)
    elif outer_depth is not None:
        record_book_depth_distribution(level_depths, outer_depth, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to depth concentration."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_concentration_metrics() -> Dict[str, float]:
    """Return latest calculated HHI, touch ratio, and total depth."""
    with _lock:
        return {
            "depth_hhi": _latest_hhi,
            "touch_dominance_ratio": _latest_touch_ratio,
            "total_depth": _latest_total_depth,
            "level_count": float(_latest_level_count),
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the depth concentration guard."""
    with _lock:
        now = time.monotonic()
        return {
            "depth_hhi": _latest_hhi,
            "touch_dominance_ratio": _latest_touch_ratio,
            "total_depth": _latest_total_depth,
            "level_count": _latest_level_count,
            "max_depth_hhi": MAX_DEPTH_HHI,
            "max_touch_dominance": MAX_TOUCH_DOMINANCE,
            "min_total_depth": MIN_TOTAL_DEPTH,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset concentration metrics, depth trackers, and active cooldown blocks."""
    global _latest_hhi, _latest_touch_ratio, _latest_total_depth, _latest_level_count, _blocked_until
    with _lock:
        _latest_hhi = 0.20
        _latest_touch_ratio = 0.20
        _latest_total_depth = 0.0
        _latest_level_count = 0
        _blocked_until = 0.0
