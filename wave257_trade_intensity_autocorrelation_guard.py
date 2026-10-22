"""
wave257_trade_intensity_autocorrelation_guard.py
--------------------------------------------------
Guard: Trade Intensity Autocorrelation & Clustering Memory Guard

Monitors autoregressive conditional duration (ACD) memory and high-frequency trade arrival clustering
(Engle & Russell 1998; Bauwens & Giot 2000; Pacurar 2008):
    Trade Interarrival Duration: \\Delta t_i = t_i - t_{i-1} (ms)
    Mean Duration:               \\mu = (1 / N) * \\sum_{i=1}^N \\Delta t_i
    1st-Lag Autocorrelation:     \\rho_1(\\Delta t) = \\sum_{i=2}^N (\\Delta t_i - \\mu)(\\Delta t_{i-1} - \\mu) / \\sum_{i=1}^N (\\Delta t_i - \\mu)^2
    Rapid Interarrival Streak:   L_{rapid} = consecutive trades with \\Delta t_i <= RAPID_THRESHOLD_MS (100.0 ms)

Under standard independent Poisson trade arrival processes:
    - Trade durations are memoryless and serially uncorrelated:
      \\rho_1(\\Delta t) ~ 0.0 (-0.20 to +0.25 across rolling N=25 trades).

During algorithmic liquidity sweeping, iceberg clearing cascades, or predatory queue sniping:
    - High-frequency algorithms execute trades in intensely correlated, clustered bursts:
        1) Extreme Duration Clustering Persistence:
           \\rho_1(\\Delta t) >= MAX_DURATION_AUTOCORRELATION (default: 0.70) AND
           \\mu <= MAX_MEAN_DURATION_MS (default: 250.0 ms) over rolling N >= 20 trades.
        2) Rapid Interarrival Burst Streak:
           L_{rapid} >= MAX_RAPID_STREAK (default: 8 consecutive trades with \\Delta t <= 100 ms).

Trading or placing limit orders during autocorrelated trade arrival cascades guarantees
immediate front-running, queue bypass, and severe negative execution selection.

When trade intensity autocorrelation or rapid arrival streak is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade durations via record_duration(duration_ms, ts=None) or
  arrival timestamps via record_trade_arrival(ts=None).
- Maintains rolling history of WINDOW_SIZE = 25 trade durations.
- Minimum MIN_SAMPLES = 20 trades required for rolling autocorrelation evaluation.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive durations are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_duration(duration_ms, ts=None)                                                        -> None
  record_trade_arrival(ts=None)                                                                -> None
  update(duration_ms, ts=None)                                                                 -> None   (alias)
  get_intensity_metrics()                                                                      -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 25
MIN_SAMPLES: int = 20
MAX_DURATION_AUTOCORRELATION: float = 0.70  # 70% 1st-lag duration autocorrelation
MAX_MEAN_DURATION_MS: float = 250.0         # 250.0 ms maximum mean duration threshold
RAPID_THRESHOLD_MS: float = 100.0           # 100.0 ms rapid trade threshold
MAX_RAPID_STREAK: int = 8                   # 8 consecutive rapid trades
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_arrival_ts: Optional[float] = None
_durations_history = collections.deque(maxlen=WINDOW_SIZE)  # durations in ms
_current_rapid_streak: int = 0
_latest_duration_ms: float = 500.0
_latest_mean_duration_ms: float = 500.0
_latest_autocorrelation: float = 0.0
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


def record_duration(
    duration_ms: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest a trade interarrival duration in milliseconds directly and evaluate autocorrelation.
    """
    global _latest_duration_ms, _latest_mean_duration_ms, _latest_autocorrelation
    global _current_rapid_streak, _blocked_until

    if not _is_valid_positive(duration_ms):
        return

    dur = float(duration_ms)

    with _lock:
        _latest_duration_ms = dur

        # Track rapid trade streak
        if dur <= RAPID_THRESHOLD_MS:
            _current_rapid_streak += 1
        else:
            _current_rapid_streak = 0

        _durations_history.append(dur)

        # Condition 1: Rapid interarrival burst streak
        if _current_rapid_streak >= MAX_RAPID_STREAK:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        n = len(_durations_history)
        if n >= MIN_SAMPLES:
            mu = sum(_durations_history) / n
            var = sum((x - mu) ** 2 for x in _durations_history)

            if var > 1e-4:
                cov1 = sum(
                    (_durations_history[i] - mu) * (_durations_history[i - 1] - mu)
                    for i in range(1, n)
                )
                rho1 = cov1 / var
            else:
                rho1 = 0.0

            _latest_mean_duration_ms = mu
            _latest_autocorrelation = rho1

            # Condition 2: Extreme duration clustering persistence
            if rho1 >= MAX_DURATION_AUTOCORRELATION and mu <= MAX_MEAN_DURATION_MS:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return
        else:
            _latest_mean_duration_ms = sum(_durations_history) / n
            _latest_autocorrelation = 0.0


def record_trade_arrival(
    ts: Optional[float] = None,
) -> None:
    """
    Ingest trade arrival timestamp, compute delta in ms from previous arrival, and record.
    """
    global _prev_arrival_ts

    now = float(ts) if ts is not None else time.time()

    with _lock:
        if _prev_arrival_ts is not None and now > _prev_arrival_ts:
            duration_ms = (now - _prev_arrival_ts) * 1000.0
            _prev_arrival_ts = now
        else:
            _prev_arrival_ts = now
            return

    record_duration(duration_ms, ts)


def update(
    duration_ms: float,
    ts: Optional[float] = None,
) -> None:
    """Alias for record_duration()."""
    record_duration(duration_ms, ts)


def is_entry_blocked() -> bool:
    """Check if new entries are blocked by trade intensity autocorrelation."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_intensity_metrics() -> Dict[str, float]:
    """Retrieve current trade intensity metrics."""
    with _lock:
        return {
            "latest_duration_ms": _latest_duration_ms,
            "mean_duration_ms": _latest_mean_duration_ms,
            "autocorrelation": _latest_autocorrelation,
            "rapid_streak": float(_current_rapid_streak),
        }


def get_status() -> Dict[str, Any]:
    """Retrieve complete guard status."""
    with _lock:
        now = time.monotonic()
        blocked = now < _blocked_until
        remaining = max(0.0, _blocked_until - now) if blocked else 0.0
        return {
            "guard_name": "wave257_trade_intensity_autocorrelation_guard",
            "is_blocked": blocked,
            "blocked_seconds_remaining": remaining,
            "sample_count": len(_durations_history),
            "latest_duration_ms": _latest_duration_ms,
            "mean_duration_ms": _latest_mean_duration_ms,
            "autocorrelation": _latest_autocorrelation,
            "rapid_streak": _current_rapid_streak,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "max_duration_autocorrelation": MAX_DURATION_AUTOCORRELATION,
            "max_mean_duration_ms": MAX_MEAN_DURATION_MS,
            "max_rapid_streak": MAX_RAPID_STREAK,
        }


def reset() -> None:
    """Reset all guard state and clear cooldowns."""
    global _prev_arrival_ts, _latest_duration_ms, _latest_mean_duration_ms
    global _latest_autocorrelation, _current_rapid_streak, _blocked_until

    with _lock:
        _prev_arrival_ts = None
        _durations_history.clear()
        _current_rapid_streak = 0
        _latest_duration_ms = 500.0
        _latest_mean_duration_ms = 500.0
        _latest_autocorrelation = 0.0
        _blocked_until = 0.0
