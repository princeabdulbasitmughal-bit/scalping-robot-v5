"""
wave275_trade_arrival_interevent_entropy_burst_guard.py
-------------------------------------------------------
Guard: Trade Inter-Event Duration Multi-Scale Entropy & Burstiness Guard

Monitors high-frequency trade inter-arrival time clustering, temporal memory, and burstiness dynamics
(Goh & Barabasi 2008; Karsai et al. 2012):
    Inter-Arrival Duration:     tau_i = t_i - t_{i-1} (milliseconds)
    Mean & Std of Durations:    mu_{tau}, sigma_{tau} over rolling N=25 trades
    Goh-Barabasi Burstiness:    B = (sigma_{tau} - mu_{tau}) / (sigma_{tau} + mu_{tau}) in [-1.0, 1.0]
    Rapid Cluster Streak:       L_{cluster} = consecutive trades with tau <= 15.0 ms

Under standard independent Poisson trade arrival processes:
    - Durations follow an exponential distribution: sigma_{tau} ~ mu_{tau}, so B ~ 0.0 (-0.15 to +0.25).
    - Trades arrive in a smooth, continuous sequence without extreme clustering.

During aggressive algorithmic queue sweeping, predatory sniping, or iceberg clearing bursts:
    - Trades bunch into ultra-tight microsecond clusters separated by long pauses, driving burstiness upward:
        1) Extreme Algorithmic Flow Burstiness:
           B >= MAX_BURSTINESS (default: 0.65) with mu_{tau} <= MAX_MEAN_DURATION_MS (150.0 ms)
           over rolling N >= MIN_TRADES (20 trades).
        2) Acute Rapid Arrival Cluster Streak:
           L_{cluster} >= MAX_CLUSTER_STREAK (default: 6 consecutive trades with tau <= 15.0 ms).

Submitting orders into an intensely bursty trade flow guarantees queue bypass, predatory adverse
fills, and negative execution alpha.

When extreme burstiness or an acute cluster streak is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade durations via record_duration(duration_ms, ts=None) or
  direct burstiness via record_burstiness(burstiness, mean_duration_ms=None, sample_count=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 25 trade durations.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive durations are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_duration(duration_ms, ts=None)                                                        -> None
  record_burstiness(burstiness, mean_duration_ms=None, sample_count=None, ts=None)             -> None
  update(duration_ms, ts=None)                                                                 -> None   (alias)
  get_burstiness_metrics()                                                                     -> dict
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
WINDOW_SIZE: int = 25                   # 25 trade durations rolling window
MIN_TRADES: int = 20                    # 20 observations minimum for burstiness evaluation
MAX_BURSTINESS: float = 0.65            # 0.65 Goh-Barabasi burstiness threshold
MAX_MEAN_DURATION_MS: float = 150.0     # 150.0 ms maximum mean duration for burst trigger
MAX_CLUSTER_STREAK: int = 6             # 6 consecutive ultra-rapid trades
CLUSTER_THRESHOLD_MS: float = 15.0      # 15.0 ms cluster duration threshold
COOLDOWN_SECONDS: float = 45.0          # 45.0s block duration

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_durations: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_current_cluster_streak: int = 0
_latest_burstiness: float = 0.0
_latest_mean_duration_ms: float = 250.0
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


def record_burstiness(
    burstiness: float,
    mean_duration_ms: Optional[float] = None,
    sample_count: Optional[int] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Directly ingest precomputed Goh-Barabasi burstiness metric and mean duration.
    """
    global _latest_burstiness, _latest_mean_duration_ms, _blocked_until

    if not _is_valid_numeric(burstiness):
        return

    b = max(-1.0, min(1.0, float(burstiness)))
    mu = float(mean_duration_ms) if (mean_duration_ms is not None and _is_valid_positive(mean_duration_ms)) else 100.0
    n = int(sample_count) if (sample_count is not None and isinstance(sample_count, int) and not isinstance(sample_count, bool) and sample_count > 0) else 20

    with _lock:
        _latest_burstiness = b
        _latest_mean_duration_ms = mu

        # Condition 1: Extreme Algorithmic Flow Burstiness
        if b >= MAX_BURSTINESS and mu <= MAX_MEAN_DURATION_MS and n >= MIN_TRADES:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_duration(duration_ms: float, ts: Optional[float] = None) -> None:
    """
    Ingest a single trade inter-arrival duration in milliseconds.
    """
    global _durations, _current_cluster_streak, _latest_burstiness
    global _latest_mean_duration_ms, _blocked_until

    if not _is_valid_positive(duration_ms):
        return

    dur = float(duration_ms)

    with _lock:
        # Update rapid cluster streak
        if dur <= CLUSTER_THRESHOLD_MS:
            _current_cluster_streak += 1
        else:
            _current_cluster_streak = 0

        # Condition 2: Acute Rapid Arrival Cluster Streak
        if _current_cluster_streak >= MAX_CLUSTER_STREAK:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            _durations.append(dur)
            return

        _durations.append(dur)

        if len(_durations) >= MIN_TRADES:
            mu = statistics.mean(_durations)
            sigma = statistics.stdev(_durations)
            _latest_mean_duration_ms = mu

            denom = sigma + mu
            if denom > 0.0:
                b = (sigma - mu) / denom
                _latest_burstiness = b

                # Condition 1: Extreme Algorithmic Flow Burstiness
                if b >= MAX_BURSTINESS and mu <= MAX_MEAN_DURATION_MS:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                    return


def update(duration_ms: float, ts: Optional[float] = None) -> None:
    """Module alias for record_duration."""
    record_duration(duration_ms, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if entry is currently blocked by burstiness guard."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked."""
    return is_entry_blocked()


def get_burstiness_metrics() -> Dict[str, Any]:
    """Return dictionary of current burstiness metrics."""
    with _lock:
        return {
            "burstiness": round(_latest_burstiness, 4),
            "mean_duration_ms": round(_latest_mean_duration_ms, 2),
            "current_streak": _current_cluster_streak,
            "sample_count": len(_durations),
            "max_burstiness": MAX_BURSTINESS,
            "max_mean_duration_ms": MAX_MEAN_DURATION_MS,
            "max_cluster_streak": MAX_CLUSTER_STREAK,
            "is_blocked": is_entry_blocked(),
        }


def get_status() -> Dict[str, Any]:
    """Return complete status dictionary."""
    with _lock:
        remaining_cd = max(0.0, _blocked_until - time.monotonic())
        metrics = get_burstiness_metrics()
        metrics["cooldown_remaining_sec"] = round(remaining_cd, 2)
        return metrics


def reset() -> None:
    """Reset all state to initial defaults."""
    global _durations, _current_cluster_streak, _latest_burstiness
    global _latest_mean_duration_ms, _blocked_until
    with _lock:
        _durations.clear()
        _current_cluster_streak = 0
        _latest_burstiness = 0.0
        _latest_mean_duration_ms = 250.0
        _blocked_until = 0.0
