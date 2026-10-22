"""
wave274_lob_flow_depth_correlation_guard.py
--------------------------------------------
Guard: LOB Order Flow Imbalance & Level-1 Depth Correlation Breakdown Guard

Monitors empirical coupling between order flow imbalance (OFI) and net changes in top-of-book depth
(Cont, Kukanov & Stoikov 2014; Hasbrouck & Saar 2013; Biais et al. 2015):
    Order Flow Imbalance:       OFI = Delta Q_{bid}^{arr} - Delta Q_{ask}^{arr} (lots)
    Top-of-Book Depth Delta:    Delta Q_{net} = Delta Q_{bid} - Delta Q_{ask} (lots)
    Flow-Depth Correlation:     \\rho(OFI, Delta Q_{net}) over rolling N=15 event transitions
    Acute Opposing Mismatch:    OFI * Delta Q_{net} <= -20.0 lots^2

Under normal continuous double-auction mechanics:
    - Order flow imbalance directly translates into conforming order book depth displacement:
      \\rho(OFI, Delta Q_{net}) >= 0.50 to 0.85 (strong positive co-movement).

During predatory queue gaming, phantom liquidity layering, or latency front-running:
    - Order book depth disconnects or moves inverted to true trade flow:
        1) Flow-Depth Coupling Breakdown:
           \\rho(OFI, Delta Q_{net}) <= MIN_CORRELATION (default: 0.15) with active cumulative flow
           sum(|OFI|) >= MIN_ACTIVE_FLOW (10.0 lots) over N >= MIN_SAMPLES (15 events).
        2) Acute Opposing Flow Mismatch:
           OFI * Delta Q_{net} <= ACUTE_OPPOSING_FLOW_PROD (-20.0 lots^2).

Entering orders during flow-depth decoupling exposes executions to phantom queue collapses,
predatory adverse selection, and false liquidity illusions.

When correlation breakdown or an acute flow mismatch is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests OFI and depth delta via record_flow_and_depth(ofi_lots, depth_delta_lots, ts=None) or
  direct correlation via record_correlation(corr, active_volume=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 15 event pairs.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf values are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_flow_and_depth(ofi_lots, depth_delta_lots, ts=None)                                    -> None
  record_correlation(corr, active_volume=None, ts=None)                                        -> None
  update(ofi_lots, depth_delta_lots=None, ts=None)                                              -> None   (alias)
  get_correlation_metrics()                                                                    -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Dict, Optional, Any, Deque, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 15                   # 15 event transitions rolling window
MIN_SAMPLES: int = 15                   # 15 observations minimum for correlation evaluation
MIN_CORRELATION: float = 0.15           # 0.15 minimum acceptable flow-depth correlation
MIN_ACTIVE_FLOW: float = 10.0           # 10.0 lots minimum cumulative absolute OFI
ACUTE_OPPOSING_FLOW_PROD: float = -20.0 # -20.0 lots^2 acute inverted flow product
COOLDOWN_SECONDS: float = 45.0          # 45.0s block duration

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_events: Deque[Tuple[float, float]] = collections.deque(maxlen=WINDOW_SIZE)  # (ofi, depth_delta)
_latest_correlation: float = 0.80
_latest_active_flow: float = 0.0
_latest_product: float = 0.0
_blocked_until: float = 0.0


def _is_valid_numeric(val: Any) -> bool:
    """Validate value is a finite numeric float or int (not bool)."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return True


def record_correlation(
    corr: float,
    active_volume: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Directly ingest precomputed flow-depth correlation and active volume.
    """
    global _latest_correlation, _latest_active_flow, _blocked_until

    if not _is_valid_numeric(corr):
        return

    c = max(-1.0, min(1.0, float(corr)))
    act = float(active_volume) if (active_volume is not None and _is_valid_numeric(active_volume)) else 15.0

    with _lock:
        _latest_correlation = c
        _latest_active_flow = act

        # Condition 1: Flow-Depth Coupling Breakdown
        if c <= MIN_CORRELATION and act >= MIN_ACTIVE_FLOW:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_flow_and_depth(
    ofi_lots: float,
    depth_delta_lots: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest simultaneous OFI lots and net top depth change, compute Pearson correlation.
    """
    global _latest_correlation, _latest_active_flow, _latest_product, _blocked_until

    if not (_is_valid_numeric(ofi_lots) and _is_valid_numeric(depth_delta_lots)):
        return

    x = float(ofi_lots)
    y = float(depth_delta_lots)
    prod = x * y

    with _lock:
        _latest_product = prod

        # Condition 2: Acute Opposing Flow Mismatch
        if prod <= ACUTE_OPPOSING_FLOW_PROD:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            _events.append((x, y))
            return

        _events.append((x, y))

        if len(_events) >= MIN_SAMPLES:
            sum_abs_x = sum(abs(item[0]) for item in _events)
            _latest_active_flow = sum_abs_x

            xs = [item[0] for item in _events]
            ys = [item[1] for item in _events]
            mean_x = statistics.mean(xs)
            mean_y = statistics.mean(ys)

            cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(xs, ys))
            var_x = sum((xi - mean_x) ** 2 for xi in xs)
            var_y = sum((yi - mean_y) ** 2 for yi in ys)

            if var_x > 0.0 and var_y > 0.0:
                corr = cov / math.sqrt(var_x * var_y)
                corr = max(-1.0, min(1.0, corr))
                _latest_correlation = corr

                # Condition 1: Flow-Depth Coupling Breakdown
                if corr <= MIN_CORRELATION and sum_abs_x >= MIN_ACTIVE_FLOW:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                    return


def update(
    ofi_lots: float,
    depth_delta_lots: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """Module alias for record_flow_and_depth or record_correlation."""
    if depth_delta_lots is None:
        record_correlation(ofi_lots, ts=ts)
    else:
        record_flow_and_depth(ofi_lots, depth_delta_lots, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if entry is currently blocked by flow-depth correlation guard."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked."""
    return is_entry_blocked()


def get_correlation_metrics() -> Dict[str, Any]:
    """Return dictionary of current flow-depth correlation metrics."""
    with _lock:
        return {
            "flow_depth_correlation": round(_latest_correlation, 4),
            "active_flow_lots": round(_latest_active_flow, 4),
            "latest_product": round(_latest_product, 4),
            "sample_count": len(_events),
            "min_correlation": MIN_CORRELATION,
            "min_active_flow": MIN_ACTIVE_FLOW,
            "acute_opposing_flow_prod": ACUTE_OPPOSING_FLOW_PROD,
            "is_blocked": is_entry_blocked(),
        }


def get_status() -> Dict[str, Any]:
    """Return complete status dictionary."""
    with _lock:
        remaining_cd = max(0.0, _blocked_until - time.monotonic())
        metrics = get_correlation_metrics()
        metrics["cooldown_remaining_sec"] = round(remaining_cd, 2)
        return metrics


def reset() -> None:
    """Reset all state to initial defaults."""
    global _events, _latest_correlation, _latest_active_flow, _latest_product, _blocked_until
    with _lock:
        _events.clear()
        _latest_correlation = 0.80
        _latest_active_flow = 0.0
        _latest_product = 0.0
        _blocked_until = 0.0
