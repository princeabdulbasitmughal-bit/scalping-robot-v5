"""
wave179_order_flow_duration_entropy_guard.py
---------------------------------------------
Guard: Trade Inter-Arrival Duration Entropy Guard

Measures algorithmic machine-slicing determinism via the Shannon entropy of trade inter-arrival
durations (delta_t = t_i - t_{i-1}).

In organic trading environments characterized by diverse human and algorithmic market participants,
trade arrivals follow stochastic point processes (e.g. Poisson or Hawkes processes) with high
duration entropy (H >= 1.20 bits).
Conversely, when automated slicing algorithms (e.g. mechanical TWAP engines, fixed-cadence iceberg
feeders, or aggressive ping loops) execute, inter-arrival times become rigidly quantized or periodic
(e.g. exactly 50ms, 100ms, or fixed-delta pulses).
In this deterministic regime, the inter-arrival duration entropy collapses:
    H <= MIN_DURATION_ENTROPY (default: 0.60 bits)

When duration entropy collapses, it indicates that a single mechanical algo is monopolizing order
execution without two-sided organic liquidity. The scalper risks getting trapped in front of an
unrelenting mechanical steamroller.

When duration entropy falls below MIN_DURATION_ENTROPY, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Records trade arrival timestamps (ts).
- Computes successive inter-arrival durations: dt = ts_curr - ts_prev (dt > 0.0).
- Assigns dt into discrete logarithmic/quantized latency bins (8 bins from <10ms to >=2.5s).
- Maintains a rolling window of WINDOW_SIZE = 30 durations.
- Requires at least MIN_SAMPLES = 15 durations before evaluation.
- Computes empirical Shannon entropy:
    H = - sum_{k} (p_k * log2(p_k))
- If H <= MIN_DURATION_ENTROPY (0.60 bits):
    blocks entries for COOLDOWN_SECONDS (45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative timestamps are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_trade_arrival(ts=None)                            -> None
  update(ts=None)                                          -> None   (alias)
  get_duration_entropy()                                   -> float
  get_status()                                             -> dict
  reset()                                                  -> None
"""

import collections
import math
import threading
import time
from typing import Deque, Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MIN_DURATION_ENTROPY: float = 0.60    # Entropy <= 0.60 bits indicates deterministic machine slicing
WINDOW_SIZE: int = 30                 # Rolling window of trade durations
MIN_SAMPLES: int = 15                 # Minimum durations required before evaluation
COOLDOWN_SECONDS: float = 45.0        # Block duration on duration entropy collapse

# Discrete latency duration bins (in seconds)
BIN_EDGES = [0.010, 0.050, 0.100, 0.250, 0.500, 1.000, 2.500]


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_ts: Optional[float] = None
_durations: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_latest_entropy: float = 3.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _get_bin_index(dt: float) -> int:
    """Classify duration into one of 8 discrete latency bins."""
    for i, edge in enumerate(BIN_EDGES):
        if dt < edge:
            return i
    return len(BIN_EDGES)


def record_trade_arrival(ts=None) -> None:
    """Record an incoming trade arrival timestamp and calculate duration entropy."""
    if ts is not None:
        if isinstance(ts, bool) or not isinstance(ts, (int, float)):
            return
        if math.isnan(ts) or math.isinf(ts) or ts < 0.0:
            return
        current_ts = float(ts)
    else:
        current_ts = time.monotonic()

    global _prev_ts, _latest_entropy, _blocked_until
    with _lock:
        if _prev_ts is None:
            _prev_ts = current_ts
            return

        dt = current_ts - _prev_ts
        _prev_ts = current_ts

        if dt <= 0.0:
            return

        _durations.append(dt)

        if len(_durations) < MIN_SAMPLES:
            return

        # Compute bin frequencies
        bin_counts = [0] * (len(BIN_EDGES) + 1)
        for d in _durations:
            b_idx = _get_bin_index(d)
            bin_counts[b_idx] += 1

        total = float(len(_durations))
        entropy = 0.0
        for count in bin_counts:
            if count > 0:
                p = count / total
                entropy -= p * math.log2(p)

        _latest_entropy = entropy

        if entropy <= MIN_DURATION_ENTROPY:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(ts=None) -> None:
    """Alias for record_trade_arrival()."""
    record_trade_arrival(ts=ts)


def is_entry_blocked() -> bool:
    """Return True if duration entropy collapse has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_duration_entropy() -> float:
    """Return the most recently computed inter-arrival duration entropy in bits."""
    with _lock:
        return _latest_entropy


def get_status() -> Dict[str, Any]:
    """Return a diagnostic snapshot of the duration entropy guard state."""
    with _lock:
        now = time.monotonic()
        return {
            "duration_entropy": _latest_entropy,
            "samples_count": len(_durations),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "min_entropy_threshold": MIN_DURATION_ENTROPY,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset trade arrival timestamps, duration deques, entropy, and active blocks."""
    global _prev_ts, _latest_entropy, _blocked_until
    with _lock:
        _prev_ts = None
        _durations.clear()
        _latest_entropy = 3.0
        _blocked_until = 0.0
