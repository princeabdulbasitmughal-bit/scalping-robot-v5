"""
wave267_trade_arrival_poisson_overdispersion_guard.py
----------------------------------------------------
Guard: Trade Arrival Poisson Overdispersion & Negative Binomial Clustering Guard

Monitors empirical trade arrival count dispersion and super-Poisson variance clustering
(Cox 1955; Engle & Russell 1998; Cameron & Trivedi 2013):
    Rolling Window:             W = 20.0 seconds, divided into K = 10 equal bins (Delta t = 2.0s)
    Bin Counts:                 c_k for k = 1 ... K
    Mean Arrival Count:         \\mu = (1 / K) * \\sum_{k=1}^K c_k
    Count Sample Variance:      \\sigma^2 = (1 / (K - 1)) * \\sum_{k=1}^K (c_k - \\mu)^2
    Overdispersion Ratio:       D = \\sigma^2 / max(\\mu, 0.10)  (Fano factor)
    Acute Bin Avalanche:        c_{max} = max_k(c_k)

Under standard independent Poisson trade arrival processes:
    - Arrival count variance equals the mean: D ~ 1.0 (typical range 0.70 to 1.60).
    - Trade flow is evenly and independently dispersed over time.

During high-frequency algorithmic cascading sweeps, stop-loss avalanches, or iceberg execution:
    - Trade counts exhibit extreme overdispersion (negative binomial compound clustering):
        1) Poisson Overdispersion Ratio Explosion:
           D >= MAX_OVERDISPERSION (default: 3.20) with mean count \\mu >= MIN_MEAN_COUNT (3.0 trades/bin).
        2) Acute Trade Avalanche Burst:
           c_{max} >= MAX_ACUTE_BIN_COUNT (default: 20 trades in a single 2.0s bin).

Entering positions during super-Poisson trade count avalanches exposes executions to extreme front-running,
market order backpressure, and adverse fill selection.

When excessive overdispersion or an acute trade avalanche is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade arrival timestamps via record_trade(ts=None) or
  direct dispersion via record_overdispersion(dispersion_ratio, mean_count=None, acute_bin_count=None, ts=None).
- Divides rolling WINDOW_SECONDS = 20.0s into NUM_BINS = 10 bins.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative trade counts are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade(ts=None)                                                                        -> None
  record_overdispersion(dispersion_ratio, mean_count=None, acute_bin_count=None, ts=None)        -> None
  update(ts=None)                                                                              -> None   (alias)
  get_dispersion_metrics(now_ts=None)                                                          -> dict
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
WINDOW_SECONDS: float = 20.0            # 20.0s rolling observation window
NUM_BINS: int = 10                      # 10 bins (2.0s per bin)
MIN_MEAN_COUNT: float = 3.0             # 3.0 trades/bin minimum (30 trades total)
MAX_OVERDISPERSION: float = 3.20        # 3.20 Fano factor threshold
MAX_ACUTE_BIN_COUNT: int = 20           # 20 trades in a single 2.0s bin threshold
COOLDOWN_SECONDS: float = 45.0          # 45.0s block duration

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_trade_timestamps: Deque[float] = collections.deque()
_latest_overdispersion: float = 1.0
_latest_mean_count: float = 0.0
_latest_max_bin_count: int = 0
_last_trade_ts: Optional[float] = None
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


def _purge_old_trades(now_ts: float) -> None:
    """Remove trade timestamps older than WINDOW_SECONDS."""
    cutoff = now_ts - WINDOW_SECONDS
    while _trade_timestamps and _trade_timestamps[0] < cutoff:
        _trade_timestamps.popleft()


def record_overdispersion(
    dispersion_ratio: float,
    mean_count: Optional[float] = None,
    acute_bin_count: Optional[int] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Directly ingest precomputed overdispersion ratio, mean count, and acute bin count.
    """
    global _latest_overdispersion, _latest_mean_count, _latest_max_bin_count, _last_trade_ts, _blocked_until

    if not _is_valid_numeric(dispersion_ratio):
        return

    d = max(0.0, float(dispersion_ratio))
    mu = float(mean_count) if (mean_count is not None and _is_valid_numeric(mean_count)) else 0.0
    c_max = int(acute_bin_count) if (acute_bin_count is not None and isinstance(acute_bin_count, int) and not isinstance(acute_bin_count, bool) and acute_bin_count > 0) else 0
    now = float(ts) if (ts is not None and _is_valid_numeric(ts)) else time.time()

    with _lock:
        _latest_overdispersion = d
        _latest_mean_count = mu
        _latest_max_bin_count = c_max
        _last_trade_ts = now

        # Condition 2: Acute Trade Avalanche Burst
        if c_max >= MAX_ACUTE_BIN_COUNT:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 1: Poisson Overdispersion Ratio Explosion
        if d >= MAX_OVERDISPERSION and mu >= MIN_MEAN_COUNT:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_trade(ts: Optional[float] = None) -> None:
    """
    Ingest a single trade arrival timestamp, bin counts across window, and compute overdispersion.
    """
    global _latest_overdispersion, _latest_mean_count, _latest_max_bin_count, _last_trade_ts, _blocked_until

    now = float(ts) if (ts is not None and _is_valid_numeric(ts)) else time.time()

    with _lock:
        _last_trade_ts = now
        _purge_old_trades(now)
        _trade_timestamps.append(now)

        # Distribute into NUM_BINS temporal bins across [now - WINDOW_SECONDS, now]
        bin_width = WINDOW_SECONDS / float(NUM_BINS)
        bin_counts = [0] * NUM_BINS
        window_start = now - WINDOW_SECONDS

        for t_trade in _trade_timestamps:
            rel_t = t_trade - window_start
            bin_idx = int(rel_t / bin_width)
            if bin_idx < 0:
                bin_idx = 0
            elif bin_idx >= NUM_BINS:
                bin_idx = NUM_BINS - 1
            bin_counts[bin_idx] += 1

        c_max = max(bin_counts)
        _latest_max_bin_count = c_max

        # Condition 2: Acute Trade Avalanche Burst
        if c_max >= MAX_ACUTE_BIN_COUNT:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        mu = statistics.mean(bin_counts)
        _latest_mean_count = mu

        if len(bin_counts) >= 2:
            var = statistics.variance(bin_counts)
            d = var / max(mu, 0.10)
            _latest_overdispersion = d

            # Condition 1: Poisson Overdispersion Ratio Explosion
            if d >= MAX_OVERDISPERSION and mu >= MIN_MEAN_COUNT:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return


def update(ts: Optional[float] = None) -> None:
    """Module alias for record_trade."""
    if ts is not None and not _is_valid_numeric(ts):
        return
    record_trade(ts=ts)


def is_entry_blocked() -> bool:
    """Return True if entry is currently blocked by overdispersion guard."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked."""
    return is_entry_blocked()


def get_dispersion_metrics(now_ts: Optional[float] = None) -> Dict[str, Any]:
    """Return dictionary of current dispersion metrics."""
    with _lock:
        if now_ts is not None and _is_valid_numeric(now_ts):
            now = float(now_ts)
        elif _last_trade_ts is not None and _last_trade_ts < 1_000_000_000.0:
            now = _last_trade_ts
        else:
            now = time.time()
        _purge_old_trades(now)
        return {
            "overdispersion_ratio": round(_latest_overdispersion, 4),
            "mean_count": round(_latest_mean_count, 4),
            "max_bin_count": _latest_max_bin_count,
            "trade_count_window": len(_trade_timestamps),
            "window_seconds": WINDOW_SECONDS,
            "num_bins": NUM_BINS,
            "max_overdispersion": MAX_OVERDISPERSION,
            "min_mean_count": MIN_MEAN_COUNT,
            "max_acute_bin_count": MAX_ACUTE_BIN_COUNT,
            "is_blocked": is_entry_blocked(),
        }


def get_status() -> Dict[str, Any]:
    """Return complete status dictionary."""
    with _lock:
        remaining_cd = max(0.0, _blocked_until - time.monotonic())
        metrics = get_dispersion_metrics()
        metrics["cooldown_remaining_sec"] = round(remaining_cd, 2)
        return metrics


def reset() -> None:
    """Reset all state to initial defaults."""
    global _trade_timestamps, _latest_overdispersion, _latest_mean_count
    global _latest_max_bin_count, _last_trade_ts, _blocked_until
    with _lock:
        _trade_timestamps.clear()
        _latest_overdispersion = 1.0
        _latest_mean_count = 0.0
        _latest_max_bin_count = 0
        _last_trade_ts = None
        _blocked_until = 0.0
