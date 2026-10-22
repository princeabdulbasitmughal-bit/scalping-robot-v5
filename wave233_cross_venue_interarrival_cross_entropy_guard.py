"""
wave233_cross_venue_interarrival_cross_entropy_guard.py
---------------------------------------------------------
Guard: Multi-Venue Order Flow Inter-Arrival Cross-Entropy Guard

Monitors cross-venue order flow routing synchronization and Kullback-Leibler divergence
between arrival time distributions on primary and secondary venues (O'Hara 2015; Brogaard et al. 2014):
    Discretized Bins:      [<50ms, 50-150ms, 150-300ms, 300-600ms, >600ms]
    Venue A Dist:          P = (p_0, p_1, p_2, p_3, p_4) over rolling 20 trades
    Venue B Dist:          Q = (q_0, q_1, q_2, q_3, q_4) over rolling 20 trades
    Cross-Entropy / KL:    D_{KL}(P || Q) = sum_{k=0}^4 p_k * log2( p_k / max(1e-4, q_k) )
    Mean Lag:              Delta t_{lag} = |bar{dt}_A - bar{dt}_B| (ms)

In synchronized, efficient multi-venue consolidated order book environments:
    - Smart order routers (SORs) distribute child orders proportionally across venues:
      P ~ Q, with D_{KL}(P || Q) < 0.60 bits, and Delta t_{lag} < 100 ms.

During fragmented liquidity regimes, dark pool latency arbitrage, or venue queue disconnects:
    - Order flow on one venue desynchronizes radically from the primary venue:
        1) Cross-Entropy Dislocation:
           D_{KL}(P || Q) >= MAX_CROSS_ENTROPY (default: 1.20 bits).
        2) Cross-Venue Arrival Lag:
           Delta t_{lag} >= MAX_LAG_MS (default: 300.0 ms).

Trading into desynchronized multi-venue flow results in immediate dark-pool front-running,
stale quote pick-off, and adverse multi-venue queue degradation.

When multi-venue cross-entropy divergence is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade executions via record_venue_trade(venue_id, ts=None).
- Maintains separate rolling duration deques for venue A and venue B (WINDOW_SIZE = 20).
- Requires MIN_SAMPLES = 10 durations per venue before KL evaluation.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative timestamps are rejected.

Aliases (required):
  is_entry_blocked()                                                   -> bool
  is_blocked()                                                         -> bool   (alias)
  record_venue_trade(venue_id, ts=None)                                -> None
  update(venue_id, ts=None)                                            -> None   (alias)
  get_cross_entropy_metrics()                                          -> dict
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
MIN_SAMPLES: int = 10
MAX_CROSS_ENTROPY: float = 1.20           # 1.20 bits maximum allowable KL divergence
MAX_LAG_MS: float = 300.0                 # 300 ms maximum average interarrival lag
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_ts = {"A": None, "B": None}
_durations = {"A": collections.deque(maxlen=WINDOW_SIZE), "B": collections.deque(maxlen=WINDOW_SIZE)}
_latest_kl: float = 0.0
_latest_lag_ms: float = 0.0
_latest_mean_a_ms: float = 100.0
_latest_mean_b_ms: float = 100.0
_blocked_until: float = 0.0


def _get_bin(dt_sec: float) -> int:
    """Classify duration into 5 discrete bins."""
    ms = dt_sec * 1000.0
    if ms < 50.0:
        return 0
    elif ms < 150.0:
        return 1
    elif ms < 300.0:
        return 2
    elif ms < 600.0:
        return 3
    else:
        return 4


def _normalize_venue(venue_id: Any) -> Optional[str]:
    """Map venue identifier to standard 'A' or 'B'."""
    if not isinstance(venue_id, (str, int)):
        return None
    s = str(venue_id).strip().upper()
    if s in ("A", "1", "PRIMARY", "VENUE_A"):
        return "A"
    elif s in ("B", "2", "SECONDARY", "VENUE_B"):
        return "B"
    return "A" if "A" in s else "B"


def record_venue_trade(
    venue_id: str,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest a trade timestamp on specified venue and evaluate interarrival cross-entropy.
    """
    global _latest_kl, _latest_lag_ms, _latest_mean_a_ms, _latest_mean_b_ms, _blocked_until

    v = _normalize_venue(venue_id)
    if v is None:
        return

    if ts is not None:
        if isinstance(ts, bool):
            return
        if not isinstance(ts, (int, float)):
            return
        if math.isnan(ts) or math.isinf(ts) or ts <= 0.0:
            return

    with _lock:
        now = time.monotonic() if ts is None else float(ts)

        prev = _prev_ts[v]
        _prev_ts[v] = now
        if prev is None:
            return

        dt = max(1e-4, now - prev)
        _durations[v].append(dt)

        # Check sample sufficiency on both venues
        n_a = len(_durations["A"])
        n_b = len(_durations["B"])
        if n_a < MIN_SAMPLES or n_b < MIN_SAMPLES:
            return

        mean_a = sum(_durations["A"]) / float(n_a)
        mean_b = sum(_durations["B"]) / float(n_b)
        lag_ms = abs(mean_a - mean_b) * 1000.0

        _latest_mean_a_ms = mean_a * 1000.0
        _latest_mean_b_ms = mean_b * 1000.0
        _latest_lag_ms = lag_ms

        # Compute empirical probability distributions P (Venue A) and Q (Venue B)
        counts_a = [0] * 5
        counts_b = [0] * 5
        for d in _durations["A"]:
            counts_a[_get_bin(d)] += 1
        for d in _durations["B"]:
            counts_b[_get_bin(d)] += 1

        p = [c / float(n_a) for c in counts_a]
        q = [c / float(n_b) for c in counts_b]

        # Kullback-Leibler Divergence D_KL(P || Q)
        kl = 0.0
        for k in range(5):
            if p[k] > 0.0:
                q_val = max(1e-4, q[k])
                kl += p[k] * math.log2(p[k] / q_val)

        _latest_kl = max(0.0, kl)

        # Condition 1: High Cross-Entropy Divergence
        if _latest_kl >= MAX_CROSS_ENTROPY:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 2: High Desynchronization Lag
        if lag_ms >= MAX_LAG_MS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(venue_id: str, ts: Optional[float] = None) -> None:
    """Alias for record_venue_trade()."""
    record_venue_trade(venue_id, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to cross-venue divergence."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_cross_entropy_metrics() -> Dict[str, float]:
    """Return latest calculated KL divergence, lag, and venue means."""
    with _lock:
        return {
            "kl_divergence_bits": _latest_kl,
            "desynchronization_lag_ms": _latest_lag_ms,
            "venue_a_mean_ms": _latest_mean_a_ms,
            "venue_b_mean_ms": _latest_mean_b_ms,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the cross-venue cross-entropy guard."""
    with _lock:
        now = time.monotonic()
        return {
            "kl_divergence_bits": _latest_kl,
            "desynchronization_lag_ms": _latest_lag_ms,
            "venue_a_mean_ms": _latest_mean_a_ms,
            "venue_b_mean_ms": _latest_mean_b_ms,
            "samples_venue_a": len(_durations["A"]),
            "samples_venue_b": len(_durations["B"]),
            "min_samples": MIN_SAMPLES,
            "max_cross_entropy": MAX_CROSS_ENTROPY,
            "max_lag_ms": MAX_LAG_MS,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset venue duration histories, metrics, and active cooldown blocks."""
    global _prev_ts, _latest_kl, _latest_lag_ms, _latest_mean_a_ms, _latest_mean_b_ms, _blocked_until
    with _lock:
        _prev_ts = {"A": None, "B": None}
        _durations["A"].clear()
        _durations["B"].clear()
        _latest_kl = 0.0
        _latest_lag_ms = 0.0
        _latest_mean_a_ms = 100.0
        _latest_mean_b_ms = 100.0
        _blocked_until = 0.0
