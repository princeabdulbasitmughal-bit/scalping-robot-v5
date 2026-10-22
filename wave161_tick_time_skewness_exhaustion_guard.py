"""
wave161_tick_time_skewness_exhaustion_guard.py
----------------------------------------------
Guard: Tick Inter-Arrival Time Asymmetry & Cluster Skewness Guard

Measures microstructural order arrival temporal clustering via Fisher-Pearson standardized
sample skewness of tick inter-arrival intervals:
    Delta_t_i = t_i - t_{i-1}
    gamma_1 = ( (1/N) * sum (Delta_t_i - mean_dt)^3 ) / (std_dt^3)

Under orderly two-sided market making, trade and quote updates arrive following a stable
temporal cadence. During predatory HFT quote stuffing, toxic cancellations, or liquidity panics,
ticks arrive in hyper-compressed packet bursts (Delta_t -> 0) followed by long voids.
This temporal clustering produces extreme positive skewness (gamma_1 >= MAX_SKEWNESS, default: 4.0)
or mean inter-arrival collapse (mean_dt <= 0.005s).
When detected, trade entries are blocked for COOLDOWN_SECONDS (default: 45.0s) to avoid
entering during high-frequency quote stuffing turbulence.

Logic:
- Records tick timestamps and calculates inter-arrival durations Delta_t.
- Maintains rolling window (WINDOW_SIZE = 25 intervals).
- Requires at least MIN_SAMPLES = 15 observations.
- Computes sample skewness gamma_1.
- If |gamma_1| >= MAX_SKEWNESS (4.0) OR mean_dt <= MIN_MEAN_DT (0.005s):
    blocks entries for COOLDOWN_SECONDS (45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: corrupted, non-monotonic, or non-numeric timestamps are ignored.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_tick(ts=None)                                     -> None
  update(ts=None)                                          -> None   (alias)
  get_arrival_skewness()                                   -> float
  reset()                                                  -> None
"""

import collections
import math
import threading
import time
from typing import Deque, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_SKEWNESS: float = 2.50          # Sample skewness >= 2.50 indicates extreme temporal burst clustering
MIN_MEAN_DT: float = 0.005         # 5ms mean inter-arrival threshold (quote stuffing burst)
WINDOW_SIZE: int = 25              # Rolling window of inter-arrival intervals
MIN_SAMPLES: int = 15              # Minimum intervals required before evaluation
COOLDOWN_SECONDS: float = 45.0     # Block duration in seconds on temporal burst shock


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_ts: Optional[float] = None
_intervals: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_latest_skewness: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_tick(ts=None) -> None:
    """Record an incoming tick timestamp and evaluate inter-arrival time skewness."""
    now = float(ts) if (ts is not None and isinstance(ts, (int, float)) and not isinstance(ts, bool)) else time.monotonic()

    if math.isnan(now) or math.isinf(now):
        return

    global _prev_ts, _latest_skewness, _blocked_until
    with _lock:
        if _prev_ts is None:
            _prev_ts = now
            return

        dt = now - _prev_ts
        if dt <= 0.0:
            # Zero or retrogressive time step: disregard to preserve monotonicity
            return

        _prev_ts = now
        _intervals.append(dt)

        if len(_intervals) < MIN_SAMPLES:
            return

        n = len(_intervals)
        mean_dt = sum(_intervals) / n
        var_dt = sum((x - mean_dt) ** 2 for x in _intervals) / n

        if var_dt <= 1e-12:
            if mean_dt <= MIN_MEAN_DT:
                skewness = 5.0
            else:
                skewness = 0.0
        else:
            std_dt = math.sqrt(var_dt)
            m3 = sum((x - mean_dt) ** 3 for x in _intervals) / n
            skewness = m3 / (std_dt ** 3)

        _latest_skewness = skewness

        if abs(skewness) >= MAX_SKEWNESS or mean_dt <= MIN_MEAN_DT:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(ts=None) -> None:
    """Alias for record_tick()."""
    record_tick(ts=ts)


def is_entry_blocked() -> bool:
    """Return True if temporal skewness or quote stuffing has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_arrival_skewness() -> float:
    """Return the most recently calculated inter-arrival time skewness."""
    with _lock:
        return _latest_skewness


def reset() -> None:
    """Reset timestamp, intervals history, latest skewness, and active cooldown."""
    global _prev_ts, _latest_skewness, _blocked_until
    with _lock:
        _prev_ts = None
        _intervals.clear()
        _latest_skewness = 0.0
        _blocked_until = 0.0
