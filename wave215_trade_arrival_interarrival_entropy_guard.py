"""
wave215_trade_arrival_interarrival_entropy_guard.py
----------------------------------------------------
Guard: Trade Interarrival Duration Shannon Entropy & Algorithmic Pacing Guard

Monitors temporal regularity and discrete Shannon entropy of trade interarrival intervals (dt)
to detect automated clockwork execution algorithms (Engle & Russell 1998; Bowsher 2007):
    Interarrival time:  dt_i = t_i - t_{i-1}
    Discretized bins:   [0-50ms, 50-100ms, 100-250ms, 250-500ms, 500-1000ms, >1000ms]
    Entropy:            H(dt) = -sum_{k=1}^B p_k * log2(p_k)
where N = 20 rolling trade executions.

In natural, multi-participant continuous double-auction trading, trades arrive stochastically
across varied time intervals:
    H(dt) >= 1.20 bits.

When an institutional automated execution desk or TWAP robot activates to unload an inventory block,
trades arrive with rigid, deterministic clockwork pacing (e.g., exactly every 100ms or 200ms):
    1) Entropy collapse:
       H(dt) <= MIN_INTERARRIVAL_ENTROPY (default: 0.50 bits)
    2) Fast algorithmic cadence:
       Mean interarrival duration dt_{mean} <= MAX_PACING_DT (default: 0.30s).

Scalpers attempting to post passive liquidity or trade counter-trend into an automated algorithmic
clockwork flow will suffer persistent queue depletion and severe execution haircut.

When deterministic algorithmic trade pacing is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade executions via record_trade(ts=None).
- Computes interarrival duration dt from previous trade.
- Maintains rolling window of WINDOW_SIZE = 20 trade durations.
- Requires at least MIN_SAMPLES = 12 durations before entropy evaluation.
- Categorizes durations into 6 logarithmic buckets and calculates Shannon entropy H(dt).
- Blocks entries for COOLDOWN_SECONDS (45.0s) if H(dt) <= 0.50 bits with dt_{mean} <= 0.30s.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative timestamps are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_trade(ts=None)                                    -> None
  update(ts=None)                                          -> None   (alias)
  get_entropy_metrics()                                    -> dict
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
WINDOW_SIZE: int = 20
MIN_SAMPLES: int = 12
MIN_INTERARRIVAL_ENTROPY: float = 0.50  # <= 0.50 bits indicates deterministic clockwork execution
MAX_PACING_DT: float = 0.30            # 300ms maximum average interarrival interval
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_ts: Optional[float] = None
_durations = collections.deque(maxlen=WINDOW_SIZE)
_latest_entropy: float = 2.0
_latest_mean_dt: float = 0.50
_blocked_until: float = 0.0


def _get_duration_bin(dt: float) -> int:
    """Classify duration into one of 6 discrete bins."""
    ms = dt * 1000.0
    if ms < 50.0:
        return 0
    elif ms < 100.0:
        return 1
    elif ms < 250.0:
        return 2
    elif ms < 500.0:
        return 3
    elif ms < 1000.0:
        return 4
    else:
        return 5


def record_trade(ts: Optional[float] = None) -> None:
    """
    Ingest a new trade execution timestamp and evaluate interarrival entropy.
    """
    global _prev_ts, _latest_entropy, _latest_mean_dt, _blocked_until

    if ts is not None:
        if isinstance(ts, bool):
            return
        if not isinstance(ts, (int, float)):
            return
        if math.isnan(ts) or math.isinf(ts) or ts <= 0.0:
            return

    with _lock:
        now = time.monotonic() if ts is None else float(ts)

        if _prev_ts is None:
            _prev_ts = now
            return

        dt = max(1e-4, now - _prev_ts)
        _prev_ts = now
        _durations.append(dt)

        n = len(_durations)
        if n < MIN_SAMPLES:
            return

        mean_dt = sum(_durations) / float(n)
        _latest_mean_dt = mean_dt

        # Bin counts
        bin_counts = [0] * 6
        for d in _durations:
            b = _get_duration_bin(d)
            bin_counts[b] += 1

        # Shannon entropy
        entropy = 0.0
        for count in bin_counts:
            if count > 0:
                p = count / float(n)
                entropy -= p * math.log2(p)

        _latest_entropy = entropy

        # Check Condition: Deterministic clockwork pacing with fast cadence
        if entropy <= MIN_INTERARRIVAL_ENTROPY and mean_dt <= MAX_PACING_DT:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(ts: Optional[float] = None) -> None:
    """Alias for record_trade()."""
    record_trade(ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to algorithmic pacing."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_entropy_metrics() -> Dict[str, float]:
    """Return latest calculated interarrival entropy and mean duration."""
    with _lock:
        return {
            "interarrival_entropy": _latest_entropy,
            "mean_duration_sec": _latest_mean_dt,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the interarrival entropy guard."""
    with _lock:
        now = time.monotonic()
        return {
            "interarrival_entropy": _latest_entropy,
            "mean_duration_sec": _latest_mean_dt,
            "sample_count": len(_durations),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "min_entropy_threshold": MIN_INTERARRIVAL_ENTROPY,
            "max_pacing_dt": MAX_PACING_DT,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset duration history, metrics, and active cooldown blocks."""
    global _prev_ts, _latest_entropy, _latest_mean_dt, _blocked_until
    with _lock:
        _prev_ts = None
        _durations.clear()
        _latest_entropy = 2.0
        _latest_mean_dt = 0.50
        _blocked_until = 0.0
