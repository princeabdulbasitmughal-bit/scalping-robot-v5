"""
wave268_lob_depth_decay_curvature_guard.py
------------------------------------------
Guard: Order Book Depth Decay Curvature & Convexity Guard

Monitors multi-level limit order book depth cushion, liquidity convexity, and outer queue decay
(Biais, Hillion & Spatt 1995; Bouchaud et al. 2004; Gould et al. 2013):
    Top Depth (Level 1):        Q_{top} = Q_{bid,1} + Q_{ask,1}
    Outer Cushion (Levels 2-3): Q_{deep} = Q_{bid,2+3} + Q_{ask,2+3}
    Depth Cushion Ratio:        R_{cushion} = Q_{deep} / max(Q_{top}, 0.10)
    Cushion Decay Delta:        Delta R = R_{curr} - R_{prev}

Under healthy continuous double-auction market conditions:
    - Order book depth exhibits positive convexity: outer depth queues accumulate volume (R_{cushion} >= 1.50 - 3.00x).
    - Large aggressive orders are buffered by deep outer cushions, preventing cascade slippage.

During liquidity withdrawal, iceberg clearance, or predatory sweep preparation:
    - Outer order book depth evaporates, creating a hollow, fragile book:
        1) Persistent Depth Cushion Collapse:
           Rolling mean \\bar{R}_{cushion} <= MIN_CUSHION_RATIO (default: 0.65) over N >= MIN_SAMPLES (12 observations)
           with Q_{top} <= MAX_VULNERABLE_TOP_DEPTH (4.0 lots).
        2) Acute Outer Depth Vanishing:
           R_{cushion} <= ACUTE_HOLLOW_RATIO (0.20) with Q_{deep} <= 1.0 lot.

Submitting market orders into a hollow, low-curvature order book guarantees deep tier slippage,
spread widening, and extreme execution markouts.

When depth cushion collapse or acute outer depth vanishing is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests multi-level depths via record_depth_levels(top_depth, deep_depth, ts=None) or
  direct curvature metrics via record_curvature(cushion_ratio, top_depth=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 20 cushion observations.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative depths are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_depth_levels(top_depth, deep_depth, ts=None)                                          -> None
  record_curvature(cushion_ratio, top_depth=None, ts=None)                                     -> None
  update(top_depth, deep_depth=None, ts=None)                                                  -> None   (alias)
  get_curvature_metrics()                                                                      -> dict
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
MIN_CUSHION_RATIO: float = 0.65         # 0.65 minimum acceptable mean cushion ratio
MAX_VULNERABLE_TOP_DEPTH: float = 4.0   # 4.0 lots max top depth for condition 1
ACUTE_HOLLOW_RATIO: float = 0.20        # 0.20 acute hollow book cushion ratio floor
ACUTE_DEEP_DEPTH_CAP: float = 1.0       # 1.0 lot max deep depth for acute trigger
COOLDOWN_SECONDS: float = 45.0          # 45.0s block duration

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_cushion_history: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_latest_top_depth: float = 5.0
_latest_deep_depth: float = 10.0
_latest_cushion_ratio: float = 2.0
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


def record_curvature(
    cushion_ratio: float,
    top_depth: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Directly ingest precomputed depth cushion ratio.
    """
    global _latest_cushion_ratio, _latest_top_depth, _blocked_until

    if not _is_valid_numeric(cushion_ratio):
        return

    r = max(0.0, float(cushion_ratio))
    top = float(top_depth) if (top_depth is not None and _is_valid_non_negative(top_depth)) else 3.0

    with _lock:
        _latest_cushion_ratio = r
        _latest_top_depth = top

        # Condition 2: Acute Outer Depth Vanishing
        if r <= ACUTE_HOLLOW_RATIO:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        _cushion_history.append(r)

        # Condition 1: Persistent Depth Cushion Collapse
        if len(_cushion_history) >= MIN_SAMPLES:
            mean_r = statistics.mean(_cushion_history)
            if mean_r <= MIN_CUSHION_RATIO and top <= MAX_VULNERABLE_TOP_DEPTH:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return


def record_depth_levels(
    top_depth: float,
    deep_depth: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest Level-1 top depth and Level-2+3 outer deep depth, calculate cushion ratio.
    """
    global _latest_top_depth, _latest_deep_depth, _latest_cushion_ratio, _blocked_until

    if not (_is_valid_non_negative(top_depth) and _is_valid_non_negative(deep_depth)):
        return

    top = float(top_depth)
    deep = float(deep_depth)
    ratio = deep / max(top, 0.10)

    with _lock:
        _latest_top_depth = top
        _latest_deep_depth = deep
        _latest_cushion_ratio = ratio

        # Condition 2: Acute Outer Depth Vanishing
        if ratio <= ACUTE_HOLLOW_RATIO and deep <= ACUTE_DEEP_DEPTH_CAP:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        _cushion_history.append(ratio)

        # Condition 1: Persistent Depth Cushion Collapse
        if len(_cushion_history) >= MIN_SAMPLES:
            mean_r = statistics.mean(_cushion_history)
            if mean_r <= MIN_CUSHION_RATIO and top <= MAX_VULNERABLE_TOP_DEPTH:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return


def update(
    top_depth: float,
    deep_depth: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """Module alias for record_depth_levels or record_curvature."""
    if deep_depth is None:
        record_curvature(top_depth, ts=ts)
    else:
        record_depth_levels(top_depth, deep_depth, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if entry is currently blocked by depth curvature guard."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked."""
    return is_entry_blocked()


def get_curvature_metrics() -> Dict[str, Any]:
    """Return dictionary of current depth curvature and cushion metrics."""
    with _lock:
        mean_r = statistics.mean(_cushion_history) if _cushion_history else 2.0
        return {
            "latest_cushion_ratio": round(_latest_cushion_ratio, 4),
            "mean_cushion_ratio": round(mean_r, 4),
            "sample_count": len(_cushion_history),
            "latest_top_depth": round(_latest_top_depth, 4),
            "latest_deep_depth": round(_latest_deep_depth, 4),
            "min_cushion_ratio": MIN_CUSHION_RATIO,
            "acute_hollow_ratio": ACUTE_HOLLOW_RATIO,
            "is_blocked": is_entry_blocked(),
        }


def get_status() -> Dict[str, Any]:
    """Return complete status dictionary."""
    with _lock:
        remaining_cd = max(0.0, _blocked_until - time.monotonic())
        metrics = get_curvature_metrics()
        metrics["cooldown_remaining_sec"] = round(remaining_cd, 2)
        return metrics


def reset() -> None:
    """Reset all state to initial defaults."""
    global _cushion_history, _latest_top_depth, _latest_deep_depth
    global _latest_cushion_ratio, _blocked_until
    with _lock:
        _cushion_history.clear()
        _latest_top_depth = 5.0
        _latest_deep_depth = 10.0
        _latest_cushion_ratio = 2.0
        _blocked_until = 0.0
