"""
wave227_cancellation_latency_asynchrony_guard.py
--------------------------------------------------
Guard: Limit Order Placement Cancellation Latency Gap Asynchrony Guard

Monitors asymmetric round-trip latency divergence between order cancellation and aggressive
fill execution (Pagnotta & Philippon 2018; Menkveld 2013):
    Mean Cancel Latency:   tau_{cancel, bar} = mean(tau_{cancel, 1..N}) (ms)
    Mean Fill Latency:     tau_{fill, bar} = mean(tau_{fill, 1..N}) (ms)
    Asynchrony Gap:        Delta tau = tau_{cancel, bar} - tau_{fill, bar} (ms)
    Asynchrony Ratio:      R_{asynch} = tau_{cancel, bar} / max(1.0, tau_{fill, bar})
                           over rolling N = 20 events.

In normal, symmetrical exchange matching environments:
    - Order cancellation and execution message round trips are balanced:
      tau_{cancel} ~ 30 - 80 ms, tau_{fill} ~ 30 - 80 ms, with R_{asynch} < 2.5x.

During severe venue queue congestion, gateway throttling, or asymmetric API latency:
    - Cancellation messages are delayed while fills process instantly:
        1) Severe Latency Asynchrony:
           tau_{cancel, bar} >= MAX_CANCEL_LATENCY_MS (default: 200.0 ms) AND
           (R_{asynch} >= MAX_ASYNCH_RATIO (default: 4.0x) OR Delta tau >= 150.0 ms).
        2) Acute Cancellation Hang:
           Single cancellation latency tau_{cancel} >= HANG_CANCEL_LATENCY_MS (default: 500.0 ms).

When cancellation latency blows out, scalpers are unable to pull resting limit quotes
ahead of adverse price moves, resulting in toxic stale-quote executions.

When cancellation latency asynchrony is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests latencies via record_latencies(cancel_latency_ms, fill_latency_ms=0.0, ts=None)
  or record_cancellation_latency(cancel_latency_ms, ts=None).
- Maintains rolling window of WINDOW_SIZE = 20 latency measurements.
- Requires MIN_SAMPLES = 8 events before evaluating rolling asynchrony.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative latencies are rejected.

Aliases (required):
  is_entry_blocked()                                                   -> bool
  is_blocked()                                                         -> bool   (alias)
  record_latencies(cancel_latency_ms, fill_latency_ms=0.0, ts=None)    -> None
  record_cancellation_latency(cancel_latency_ms, ts=None)              -> None
  update(cancel_latency_ms, fill_latency_ms=0.0, ts=None)              -> None   (alias)
  get_asynchrony_metrics()                                             -> dict
  get_status()                                                         -> dict
  reset()                                                              -> None
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
MIN_SAMPLES: int = 8
MAX_CANCEL_LATENCY_MS: float = 200.0      # 200 ms mean cancellation latency
MAX_ASYNCH_RATIO: float = 4.0             # 4.0x cancel-to-fill latency ratio
MIN_ASYNCH_GAP_MS: float = 150.0          # 150 ms gap between cancel and fill
HANG_CANCEL_LATENCY_MS: float = 500.0     # 500 ms single cancellation hang
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_cancel_latencies = collections.deque(maxlen=WINDOW_SIZE)
_fill_latencies = collections.deque(maxlen=WINDOW_SIZE)
_latest_mean_cancel_ms: float = 50.0
_latest_mean_fill_ms: float = 50.0
_latest_asynch_ratio: float = 1.0
_latest_asynch_gap_ms: float = 0.0
_blocked_until: float = 0.0


def _is_valid_latency(val: Any) -> bool:
    """Validate latency is a non-negative finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val >= 0.0


def record_latencies(
    cancel_latency_ms: float,
    fill_latency_ms: float = 0.0,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest cancellation and fill round-trip latencies and evaluate asynchrony.
    """
    global _latest_mean_cancel_ms, _latest_mean_fill_ms
    global _latest_asynch_ratio, _latest_asynch_gap_ms, _blocked_until

    if not _is_valid_latency(cancel_latency_ms):
        return
    if not _is_valid_latency(fill_latency_ms):
        return

    c_lat = float(cancel_latency_ms)
    f_lat = float(fill_latency_ms)

    with _lock:
        # Check Condition 2: Acute single cancellation hang
        if c_lat >= HANG_CANCEL_LATENCY_MS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        _cancel_latencies.append(c_lat)
        if f_lat > 0.0:
            _fill_latencies.append(f_lat)

        n_c = len(_cancel_latencies)
        if n_c < MIN_SAMPLES:
            return

        mean_c = sum(_cancel_latencies) / float(n_c)
        mean_f = sum(_fill_latencies) / float(len(_fill_latencies)) if _fill_latencies else 40.0

        gap = mean_c - mean_f
        ratio = mean_c / max(1.0, mean_f)

        _latest_mean_cancel_ms = mean_c
        _latest_mean_fill_ms = mean_f
        _latest_asynch_gap_ms = gap
        _latest_asynch_ratio = ratio

        # Check Condition 1: Severe Latency Asynchrony
        if mean_c >= MAX_CANCEL_LATENCY_MS:
            if ratio >= MAX_ASYNCH_RATIO or gap >= MIN_ASYNCH_GAP_MS:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return


def record_cancellation_latency(
    cancel_latency_ms: float,
    ts: Optional[float] = None,
) -> None:
    """Record single cancellation latency with default fill baseline."""
    record_latencies(cancel_latency_ms, 0.0, ts)


def update(
    cancel_latency_ms: float,
    fill_latency_ms: float = 0.0,
    ts: Optional[float] = None,
) -> None:
    """Alias for record_latencies()."""
    record_latencies(cancel_latency_ms, fill_latency_ms, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to cancellation latency asynchrony."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_asynchrony_metrics() -> Dict[str, float]:
    """Return latest calculated cancellation latency, fill latency, gap, and ratio."""
    with _lock:
        return {
            "mean_cancel_latency_ms": _latest_mean_cancel_ms,
            "mean_fill_latency_ms": _latest_mean_fill_ms,
            "asynchrony_gap_ms": _latest_asynch_gap_ms,
            "asynchrony_ratio": _latest_asynch_ratio,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the cancellation latency asynchrony guard."""
    with _lock:
        now = time.monotonic()
        return {
            "mean_cancel_latency_ms": _latest_mean_cancel_ms,
            "mean_fill_latency_ms": _latest_mean_fill_ms,
            "asynchrony_gap_ms": _latest_asynch_gap_ms,
            "asynchrony_ratio": _latest_asynch_ratio,
            "sample_count": len(_cancel_latencies),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "max_cancel_latency_ms": MAX_CANCEL_LATENCY_MS,
            "max_asynch_ratio": MAX_ASYNCH_RATIO,
            "hang_cancel_latency_ms": HANG_CANCEL_LATENCY_MS,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset latency histories, metrics, and active cooldown blocks."""
    global _latest_mean_cancel_ms, _latest_mean_fill_ms
    global _latest_asynch_ratio, _latest_asynch_gap_ms, _blocked_until
    with _lock:
        _cancel_latencies.clear()
        _fill_latencies.clear()
        _latest_mean_cancel_ms = 50.0
        _latest_mean_fill_ms = 50.0
        _latest_asynch_ratio = 1.0
        _latest_asynch_gap_ms = 0.0
        _blocked_until = 0.0
