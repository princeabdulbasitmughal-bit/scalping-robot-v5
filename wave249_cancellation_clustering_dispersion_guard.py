"""
wave249_cancellation_clustering_dispersion_guard.py
-----------------------------------------------------
Guard: Order Cancellation Clustering & Poisson Burst Dispersion Guard

Monitors empirical clustering and super-Poisson overdispersion in limit order cancellations
(Engle & Russell 1998; Hautsch 2004; Bowsher 2007):
    Binned Cancellation Counts:  x_k = cancellations in 0.5s interval k \\in [1, K], K = 10 (5.0s window)
    Mean Rate per Bin:           \\mu = (1 / K) * \\sum_{k=1}^K x_k
    Variance per Bin:            \\sigma^2 = (1 / (K - 1)) * \\sum_{k=1}^K (x_k - \\mu)^2
    Index of Dispersion (Fano):  D = \\sigma^2 / max(0.01, \\mu)
    Acute Mass Burst:            B_{1s} = cancellations in last 1.0s window

Under standard independent Poisson quote modification processes:
    - Cancellations arrive homogeneously across time bins:
      \\sigma^2 ~ \\mu  =>  D ~ 1.0 (typically 0.70 - 1.80 across K=10 bins).

During predatory quote stuffing, spoof teasing, or cascading phantom liquidity pulls:
    - High-frequency algorithms cancel resting depth in intense synchronized bursts:
        1) Super-Poisson Cancellation Clustering Surge:
           D >= MAX_DISPERSION_INDEX (default: 3.00) AND
           \\mu >= MIN_MEAN_RATE (default: 4.0 cancels/0.5s bin) over K=10 bins.
        2) Acute Mass Cancellation Burst:
           B_{1s} >= MAX_ACUTE_BURST (default: 30 cancellations in <= 1.0s).

Submitting limit orders or attempting to fade into highly clustered quote cancellation storms
results in immediate quote evaporation, front-running sweeps, and severe execution slippage.

When cancellation clustering surge or acute mass burst is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests cancellation events via record_cancellation(count=1, ts=None) or
  direct bin counts via record_bin_counts(counts_list, ts=None).
- Maintains sliding event history window of 5.0 seconds.
- Partitions into K=10 bins of 0.5s to evaluate Fano index of dispersion D.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative counts are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_cancellation(count=1, ts=None)                                                        -> None
  record_bin_counts(counts, ts=None)                                                           -> None
  update(count=1, ts=None)                                                                     -> None   (alias)
  get_dispersion_metrics()                                                                     -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any, List

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
NUM_BINS: int = 10                     # K = 10 bins
BIN_WIDTH_SECONDS: float = 0.5         # 0.5s per bin (5.0s total history)
MAX_DISPERSION_INDEX: float = 3.00     # D >= 3.00 super-Poisson overdispersion
MIN_MEAN_RATE: float = 4.00            # 4.00 cancels/bin minimum rate threshold
MAX_ACUTE_BURST: float = 30.0          # 30 cancellations in <= 1.0s
COOLDOWN_SECONDS: float = 45.0
HISTORY_WINDOW_SECONDS: float = NUM_BINS * BIN_WIDTH_SECONDS  # 5.0s

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_cancel_events: collections.deque = collections.deque()  # elements: (timestamp, count)
_latest_dispersion_index: float = 1.0
_latest_mean_rate: float = 0.0
_latest_acute_burst: float = 0.0
_blocked_until: float = 0.0


def _is_valid_non_negative(val: Any) -> bool:
    """Validate value is a non-negative finite numeric float or int."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val >= 0.0


def record_cancellation(
    count: float = 1,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest cancellation count at given timestamp (or current time).
    Partitions into 10 bins of 0.5s and evaluates index of dispersion and acute burst.
    """
    global _latest_dispersion_index, _latest_mean_rate, _latest_acute_burst, _blocked_until

    if not _is_valid_non_negative(count):
        return

    c = float(count)
    if c == 0.0:
        return

    now = float(ts) if ts is not None else time.time()

    with _lock:
        _cancel_events.append((now, c))

        # Prune older than 5.0s relative to latest event
        cutoff = now - HISTORY_WINDOW_SECONDS
        while _cancel_events and _cancel_events[0][0] < cutoff:
            _cancel_events.popleft()

        # Acute burst in last 1.0s
        acute_burst = sum(cnt for t_evt, cnt in _cancel_events if (now - t_evt) <= 1.0)
        _latest_acute_burst = acute_burst

        # Condition 1: Acute mass burst
        if acute_burst >= MAX_ACUTE_BURST:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Binned dispersion across K=10 bins of 0.5s
        bins = [0.0] * NUM_BINS
        for t_evt, cnt in _cancel_events:
            age = now - t_evt
            if 0.0 <= age < HISTORY_WINDOW_SECONDS:
                bin_idx = min(NUM_BINS - 1, int(age / BIN_WIDTH_SECONDS))
                bins[bin_idx] += cnt

        mu = sum(bins) / NUM_BINS
        var = sum((x - mu) ** 2 for x in bins) / (NUM_BINS - 1)
        dispersion = var / max(0.01, mu)

        _latest_mean_rate = mu
        _latest_dispersion_index = dispersion

        # Condition 2: Super-Poisson clustering surge
        if dispersion >= MAX_DISPERSION_INDEX and mu >= MIN_MEAN_RATE:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_bin_counts(
    counts: List[float],
    ts: Optional[float] = None,
) -> None:
    """
    Directly ingest a list of K=10 bin counts.
    """
    global _latest_dispersion_index, _latest_mean_rate, _blocked_until

    if not isinstance(counts, (list, tuple)) or len(counts) < 2:
        return

    clean_counts = []
    for x in counts:
        if not _is_valid_non_negative(x):
            return
        clean_counts.append(float(x))

    k = len(clean_counts)
    mu = sum(clean_counts) / k
    var = sum((x - mu) ** 2 for x in clean_counts) / (k - 1)
    dispersion = var / max(0.01, mu)

    with _lock:
        _latest_mean_rate = mu
        _latest_dispersion_index = dispersion

        if dispersion >= MAX_DISPERSION_INDEX and mu >= MIN_MEAN_RATE:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(
    count: float = 1,
    ts: Optional[float] = None,
) -> None:
    """Alias for record_cancellation()."""
    record_cancellation(count, ts)


def is_entry_blocked() -> bool:
    """Check if new entries are blocked by cancellation clustering."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_dispersion_metrics() -> Dict[str, float]:
    """Retrieve current cancellation dispersion metrics."""
    with _lock:
        return {
            "mean_bin_rate": _latest_mean_rate,
            "dispersion_index": _latest_dispersion_index,
            "acute_burst": _latest_acute_burst,
        }


def get_status() -> Dict[str, Any]:
    """Retrieve complete guard status."""
    with _lock:
        now = time.monotonic()
        blocked = now < _blocked_until
        remaining = max(0.0, _blocked_until - now) if blocked else 0.0
        return {
            "guard_name": "wave249_cancellation_clustering_dispersion_guard",
            "is_blocked": blocked,
            "blocked_seconds_remaining": remaining,
            "event_count": len(_cancel_events),
            "mean_bin_rate": _latest_mean_rate,
            "dispersion_index": _latest_dispersion_index,
            "acute_burst": _latest_acute_burst,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "max_dispersion_index": MAX_DISPERSION_INDEX,
            "min_mean_rate": MIN_MEAN_RATE,
            "max_acute_burst": MAX_ACUTE_BURST,
        }


def reset() -> None:
    """Reset all guard state and clear cooldowns."""
    global _latest_dispersion_index, _latest_mean_rate, _latest_acute_burst, _blocked_until

    with _lock:
        _cancel_events.clear()
        _latest_dispersion_index = 1.0
        _latest_mean_rate = 0.0
        _latest_acute_burst = 0.0
        _blocked_until = 0.0
