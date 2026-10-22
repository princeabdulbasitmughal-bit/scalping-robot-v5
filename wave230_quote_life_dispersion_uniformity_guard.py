"""
wave230_quote_life_dispersion_uniformity_guard.py
--------------------------------------------------
Guard: Quote Life Dispersion & Transient Cancellation Uniformity Guard

Monitors quote lifespan distribution uniformity and detects automated probing /
pinging algorithms (Hasbrouck & Saar 2009; Biais et al. 2015):
    Mean Quote Lifespan:       tau_{life, bar} = (1/N) * sum_{i=1}^N tau_i (ms)
    Lifespan Standard Dev:     sigma_{tau} = sqrt( (1/N) * sum (tau_i - tau_{bar})^2 )
    Coefficient of Variation:  CV_{tau} = sigma_{tau} / max(1.0, tau_{life, bar})
                               over rolling N = 25 cancellations.

In natural double-auction trading across heterogeneous market participants:
    - Quote lifespans exhibit high dispersion: resting orders live anywhere from tens of
      milliseconds to many seconds or minutes: CV_{tau} >= 0.50, tau_{bar} >= 300 ms.

During algorithmic pinging, latency probing, or predatory order cancellation loops:
    - Quotes are created and cancelled with rigid, deterministic clockwork periodicity:
        1) Rigid Uniformity & Ultra-Short Life:
           tau_{life, bar} <= MAX_MEAN_LIFESPAN_MS (default: 120.0 ms) AND
           CV_{tau} <= MIN_LIFESPAN_CV (default: 0.15, rigid algorithmic pacing).
        2) Sub-30ms Cancellation Blitz:
           Streak of >= 8 consecutive cancellations with lifespan <= 30.0 ms.

Scalpers attempting to post passive orders into a high-frequency probing storm suffer
extreme execution haircut and queue discovery manipulation.

When rigid quote life uniformity or sub-30ms blitz is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests cancellation lifespans via record_quote_lifespan(lifespan_ms, ts=None).
- Maintains rolling window of WINDOW_SIZE = 25 lifespans.
- Requires MIN_SAMPLES = 15 lifespans before evaluating CV_{tau}.
- Tracks consecutive blitz streaks.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative lifespans are rejected.

Aliases (required):
  is_entry_blocked()                                                   -> bool
  is_blocked()                                                         -> bool   (alias)
  record_quote_lifespan(lifespan_ms, ts=None)                          -> None
  update(lifespan_ms, ts=None)                                         -> None   (alias)
  get_dispersion_metrics()                                             -> dict
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
WINDOW_SIZE: int = 25
MIN_SAMPLES: int = 15
MAX_MEAN_LIFESPAN_MS: float = 120.0       # 120 ms maximum mean lifespan for probing algorithms
MIN_LIFESPAN_CV: float = 0.15             # CV <= 0.15 indicates rigid robotic pacing uniformity
BLITZ_LIFESPAN_MS: float = 30.0           # 30 ms threshold for sub-millisecond probing blitz
MIN_BLITZ_STREAK: int = 8                 # 8 consecutive sub-30ms cancellations
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_lifespans = collections.deque(maxlen=WINDOW_SIZE)
_consecutive_blitz: int = 0
_latest_mean_ms: float = 500.0
_latest_std_ms: float = 200.0
_latest_cv: float = 0.40
_blocked_until: float = 0.0


def _is_valid_lifespan(val: Any) -> bool:
    """Validate lifespan is a non-negative finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val >= 0.0


def record_quote_lifespan(
    lifespan_ms: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest a quote cancellation lifespan and evaluate dispersion and blitz streaks.
    """
    global _consecutive_blitz, _latest_mean_ms, _latest_std_ms, _latest_cv, _blocked_until

    if not _is_valid_lifespan(lifespan_ms):
        return

    life = float(lifespan_ms)

    with _lock:
        # Check Condition 2: Sub-30ms blitz streak
        if life <= BLITZ_LIFESPAN_MS:
            _consecutive_blitz += 1
            if _consecutive_blitz >= MIN_BLITZ_STREAK:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return
        else:
            _consecutive_blitz = 0

        _lifespans.append(life)
        n = len(_lifespans)
        if n < MIN_SAMPLES:
            return

        mean_l = sum(_lifespans) / float(n)
        var_l = sum((l - mean_l) ** 2 for l in _lifespans) / float(n)
        std_l = math.sqrt(var_l)
        cv = std_l / max(1.0, mean_l)

        _latest_mean_ms = mean_l
        _latest_std_ms = std_l
        _latest_cv = cv

        # Check Condition 1: Rigid robotic uniformity with ultra-short life
        if mean_l <= MAX_MEAN_LIFESPAN_MS and cv <= MIN_LIFESPAN_CV:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(lifespan_ms: float, ts: Optional[float] = None) -> None:
    """Alias for record_quote_lifespan()."""
    record_quote_lifespan(lifespan_ms, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to quote life uniformity."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_dispersion_metrics() -> Dict[str, float]:
    """Return latest calculated mean lifespan, stddev, and CV."""
    with _lock:
        return {
            "mean_lifespan_ms": _latest_mean_ms,
            "std_lifespan_ms": _latest_std_ms,
            "lifespan_cv": _latest_cv,
            "blitz_streak": float(_consecutive_blitz),
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the quote life dispersion guard."""
    with _lock:
        now = time.monotonic()
        return {
            "mean_lifespan_ms": _latest_mean_ms,
            "std_lifespan_ms": _latest_std_ms,
            "lifespan_cv": _latest_cv,
            "blitz_streak": _consecutive_blitz,
            "sample_count": len(_lifespans),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "max_mean_lifespan_ms": MAX_MEAN_LIFESPAN_MS,
            "min_lifespan_cv": MIN_LIFESPAN_CV,
            "blitz_lifespan_ms": BLITZ_LIFESPAN_MS,
            "min_blitz_streak": MIN_BLITZ_STREAK,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset lifespan history, streak counters, metrics, and active cooldown blocks."""
    global _consecutive_blitz, _latest_mean_ms, _latest_std_ms, _latest_cv, _blocked_until
    with _lock:
        _lifespans.clear()
        _consecutive_blitz = 0
        _latest_mean_ms = 500.0
        _latest_std_ms = 200.0
        _latest_cv = 0.40
        _blocked_until = 0.0
