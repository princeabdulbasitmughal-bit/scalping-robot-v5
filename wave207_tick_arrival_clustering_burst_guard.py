"""
wave207_tick_arrival_clustering_burst_guard.py
-----------------------------------------------
Guard: High-Frequency Tick Arrival Burst Fano Factor & Cluster Dispersion Guard

Monitors temporal clustering and packet bursts in market tick/quote arrival processes using the
Fano Factor (Index of Dispersion) across 1-second observation bins over a 10-second rolling window
(Engle & Russell 1998; Bowsher 2007):
    Mean count:   mu = (1 / M) * sum_{m=1}^M k_m
    Variance:     sigma^2 = (1 / (M - 1)) * sum_{m=1}^M (k_m - mu)^2
    Fano Factor:  FF = sigma^2 / max(1.0, mu)
where M = 10 one-second bins (total 10.0 seconds).

Under standard homogeneous Poisson arrival models where quotes arrive independently:
    FF is stably centered near 1.0 (0.50 <= FF <= 2.50).

During high-frequency market microstructure shocks—such as feed burst packet chokes, sudden quote
stuffing cascades, or news release tick flurries—the arrival process exhibits extreme overdispersion:
    FF >= MAX_FANO_FACTOR (default: 5.0)
    with peak single-second burst count k_{max} >= MIN_PEAK_BURST (default: 25 ticks/sec).

This extreme temporal clustering creates socket buffer queue delays, price quotation stale-lock,
and violent fills as liquidity evaporates during the flurry.

When arrival clustering breaches the Fano Factor safety limit, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests tick events via record_tick(ts=None).
- Records timestamps in a rolling 10.0-second deque.
- Bins arrivals into 10 discrete 1.0-second sub-intervals.
- Computes sample mean, sample variance, peak burst count, and Fano Factor FF.
- Blocks entries for COOLDOWN_SECONDS (45.0s) if FF >= 5.0 and peak >= 25 ticks.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric or invalid timestamps are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_tick(ts=None)                                     -> None
  update(ts=None)                                          -> None   (alias)
  get_fano_metrics()                                       -> dict
  get_status()                                             -> dict
  reset()                                                  -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SECONDS: float = 10.0
BIN_COUNT: int = 10
BIN_SECONDS: float = 1.0
MAX_FANO_FACTOR: float = 5.0           # 5.0x dispersion indicates extreme non-Poisson clustering
MIN_PEAK_BURST: int = 25               # 25 ticks in a single second minimum
COOLDOWN_SECONDS: float = 45.0
MAX_TIMESTAMP_HISTORY: int = 1000

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_timestamps = collections.deque(maxlen=MAX_TIMESTAMP_HISTORY)
_latest_fano_factor: float = 1.0
_latest_mean_count: float = 0.0
_latest_peak_burst: int = 0
_blocked_until: float = 0.0


def record_tick(ts: Optional[float] = None) -> None:
    """
    Ingest a new tick event and calculate rolling arrival Fano Factor.
    """
    global _latest_fano_factor, _latest_mean_count, _latest_peak_burst, _blocked_until

    if ts is not None:
        if isinstance(ts, bool):
            return
        if not isinstance(ts, (int, float)):
            return
        if math.isnan(ts) or math.isinf(ts) or ts <= 0.0:
            return

    with _lock:
        now = time.monotonic() if ts is None else float(ts)
        _timestamps.append(now)

        cutoff = now - WINDOW_SECONDS
        while _timestamps and _timestamps[0] < cutoff:
            _timestamps.popleft()

        # Partition into BIN_COUNT bins
        bins = [0] * BIN_COUNT
        for t in _timestamps:
            idx = int((t - cutoff) / BIN_SECONDS)
            if idx < 0:
                idx = 0
            elif idx >= BIN_COUNT:
                idx = BIN_COUNT - 1
            bins[idx] += 1

        mean_val = sum(bins) / float(BIN_COUNT)
        _latest_mean_count = mean_val

        variance = sum((k - mean_val) ** 2 for k in bins) / float(BIN_COUNT - 1)
        fano = variance / max(1.0, mean_val)
        _latest_fano_factor = fano

        peak = max(bins)
        _latest_peak_burst = peak

        # Check Condition: Extreme Fano Factor clustering with high peak burst
        if fano >= MAX_FANO_FACTOR and peak >= MIN_PEAK_BURST:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(ts: Optional[float] = None) -> None:
    """Alias for record_tick()."""
    record_tick(ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to tick arrival clustering."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_fano_metrics() -> Dict[str, float]:
    """Return latest calculated Fano Factor, mean count, and peak burst."""
    with _lock:
        return {
            "fano_factor": _latest_fano_factor,
            "mean_count": _latest_mean_count,
            "peak_burst": float(_latest_peak_burst),
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the tick clustering guard."""
    with _lock:
        now = time.monotonic()
        return {
            "fano_factor": _latest_fano_factor,
            "mean_count": _latest_mean_count,
            "peak_burst": _latest_peak_burst,
            "sample_count": len(_timestamps),
            "window_seconds": WINDOW_SECONDS,
            "bin_count": BIN_COUNT,
            "max_fano_threshold": MAX_FANO_FACTOR,
            "min_peak_burst": MIN_PEAK_BURST,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset tick timestamp history and active cooldown blocks."""
    global _latest_fano_factor, _latest_mean_count, _latest_peak_burst, _blocked_until
    with _lock:
        _timestamps.clear()
        _latest_fano_factor = 1.0
        _latest_mean_count = 0.0
        _latest_peak_burst = 0
        _blocked_until = 0.0
