"""
wave273_trade_size_pareto_tail_alpha_guard.py
--------------------------------------------
Guard: Trade Size Power-Law Tail Index (Pareto Alpha) Fragility Guard

Monitors institutional block execution, heavy-tailed trade size distributions, and Pareto alpha degradation
(Gabaix et al. 2003; Clauset, Shalizi & Newman 2009):
    Trade Volumes:              V_1, V_2, ... V_N
    Upper-Tail Order Stats:     v_{(1)} >= v_{(2)} >= ... >= v_{(k)} with threshold v_{min} = v_{(k)}
    Hill Tail Index Estimator:  \\alpha_{Hill} = ( (1 / k) * \\sum_{i=1}^k ln(v_{(i)} / v_{min}) )^{-1}
    Acute Whale Block Size:     V >= ACUTE_WHALE_SIZE (20.0 lots)

Under normal, retail and market-making double-auction conditions:
    - Trade sizes follow a stable, moderate tail distribution with finite variance (\\alpha_{Hill} >= 1.50 - 2.50).
    - Block trades are rare and within standard book-depth capacity.

During predatory institutional liquidation sweeps, whale dumping, or iceberg clearing cascades:
    - Extreme block sizes disproportionately dominate the upper tail, driving tail index below critical thresholds:
        1) Heavy-Tailed Pareto Alpha Collapse:
           \\alpha_{Hill} <= MIN_PARETO_ALPHA (default: 1.15) with top trade v_{(1)} >= MIN_WHALE_THRESHOLD (8.0 lots)
           over k >= MIN_TAIL_SAMPLES (10 upper-tail trades).
        2) Acute Single Whale Block Execution:
           V >= ACUTE_WHALE_SIZE (default: 20.0 lots).

Trading during Pareto tail index collapse exposes scalping positions to extreme market impact displacement,
immediate quote exhaustion, and catastrophic adverse selection.

When tail index collapse or an acute whale block is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade sizes via record_trade_size(volume, ts=None) or
  direct tail index via record_alpha(alpha, top_size=None, sample_count=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 30 trade sizes.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive trade volumes are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade_size(volume, ts=None)                                                           -> None
  record_alpha(alpha, top_size=None, sample_count=None, ts=None)                                -> None
  update(volume, ts=None)                                                                      -> None   (alias)
  get_tail_metrics()                                                                           -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any, Deque, List

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 30                   # 30 trade volumes rolling window
MIN_TAIL_SAMPLES: int = 10              # 10 upper-tail order statistics for Hill estimator
MIN_PARETO_ALPHA: float = 1.15          # 1.15 minimum Pareto tail index floor
MIN_WHALE_THRESHOLD: float = 8.0        # 8.0 lots minimum top trade size for condition 1
ACUTE_WHALE_SIZE: float = 20.0          # 20.0 lots acute single whale block size
COOLDOWN_SECONDS: float = 45.0          # 45.0s block duration

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_sizes: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_latest_alpha: float = 2.50
_latest_top_size: float = 1.0
_latest_single_size: float = 1.0
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


def record_alpha(
    alpha: float,
    top_size: Optional[float] = None,
    sample_count: Optional[int] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Directly ingest precomputed Pareto tail index alpha and top trade size.
    """
    global _latest_alpha, _latest_top_size, _blocked_until

    if not _is_valid_numeric(alpha):
        return

    a = max(0.0, float(alpha))
    top = float(top_size) if (top_size is not None and _is_valid_positive(top_size)) else 10.0
    k = int(sample_count) if (sample_count is not None and isinstance(sample_count, int) and not isinstance(sample_count, bool) and sample_count > 0) else 10

    with _lock:
        _latest_alpha = a
        _latest_top_size = top

        # Condition 1: Heavy-Tailed Pareto Alpha Collapse
        if a <= MIN_PARETO_ALPHA and top >= MIN_WHALE_THRESHOLD and k >= MIN_TAIL_SAMPLES:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_trade_size(volume: float, ts: Optional[float] = None) -> None:
    """
    Ingest a trade size in lots, maintain rolling window, and compute Hill tail index.
    """
    global _sizes, _latest_alpha, _latest_top_size, _latest_single_size, _blocked_until

    if not _is_valid_positive(volume):
        return

    vol = float(volume)

    with _lock:
        _latest_single_size = vol

        # Condition 2: Acute Single Whale Block Execution
        if vol >= ACUTE_WHALE_SIZE:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            _sizes.append(vol)
            return

        _sizes.append(vol)

        if len(_sizes) >= MIN_TAIL_SAMPLES:
            sorted_sizes = sorted(_sizes, reverse=True)
            top_k = sorted_sizes[:MIN_TAIL_SAMPLES]
            _latest_top_size = top_k[0]
            v_min = top_k[-1]

            if v_min > 0.0 and top_k[0] > v_min:
                log_sum = sum(math.log(v / v_min) for v in top_k)
                if log_sum > 0.0:
                    alpha = float(MIN_TAIL_SAMPLES) / log_sum
                    _latest_alpha = alpha

                    # Condition 1: Heavy-Tailed Pareto Alpha Collapse
                    if alpha <= MIN_PARETO_ALPHA and top_k[0] >= MIN_WHALE_THRESHOLD:
                        _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                        return


def update(volume: float, ts: Optional[float] = None) -> None:
    """Module alias for record_trade_size."""
    record_trade_size(volume, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if entry is currently blocked by Pareto tail guard."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked."""
    return is_entry_blocked()


def get_tail_metrics() -> Dict[str, Any]:
    """Return dictionary of current Pareto tail metrics."""
    with _lock:
        return {
            "pareto_alpha": round(_latest_alpha, 4),
            "top_size": round(_latest_top_size, 4),
            "latest_single_size": round(_latest_single_size, 4),
            "sample_count": len(_sizes),
            "min_pareto_alpha": MIN_PARETO_ALPHA,
            "min_whale_threshold": MIN_WHALE_THRESHOLD,
            "acute_whale_size": ACUTE_WHALE_SIZE,
            "is_blocked": is_entry_blocked(),
        }


def get_status() -> Dict[str, Any]:
    """Return complete status dictionary."""
    with _lock:
        remaining_cd = max(0.0, _blocked_until - time.monotonic())
        metrics = get_tail_metrics()
        metrics["cooldown_remaining_sec"] = round(remaining_cd, 2)
        return metrics


def reset() -> None:
    """Reset all state to initial defaults."""
    global _sizes, _latest_alpha, _latest_top_size, _latest_single_size, _blocked_until
    with _lock:
        _sizes.clear()
        _latest_alpha = 2.50
        _latest_top_size = 1.0
        _latest_single_size = 1.0
        _blocked_until = 0.0
