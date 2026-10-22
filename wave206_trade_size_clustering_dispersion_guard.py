"""
wave206_trade_size_clustering_dispersion_guard.py
--------------------------------------------------
Guard: Trade Size Uniformity & Iceberg Chunking Dispersion Guard

Monitors the dispersion and uniformity of executed trade volumes to detect automated parent-order
slicing and institutional iceberg execution algorithms (Easley, O'Hara et al. 2012):
    Mean size:      mu_V = (1 / N) * sum_{i=1}^N V_i
    Variance:       sigma_V^2 = (1 / (N - 1)) * sum_{i=1}^N (V_i - mu_V)^2
    Coeff of Var:   CV_V = sigma_V / max(1e-6, mu_V)

In natural decentralized multi-participant trading, retail and commercial order sizes are heterogeneous
and dispersed:
    CV_V >= 0.40.

When institutional trading desks deploy automated slicing algorithms (TWAP, VWAP, or hidden icebergs)
to dump or accumulate inventory, trade sizes collapse into unnaturally uniform chunks
(e.g., repeating 5.0 lots, 5.0 lots, 5.0 lots):
    1) Uniformity collapse:
       CV_V <= MAX_UNIFORMITY_CV (default: 0.08, or < 8% variation) with non-trivial size
       (mu_V >= MIN_CHUNK_SIZE = 2.0 lots).
    2) Identical chunk streak:
       Consecutive identical trade sizes >= MAX_IDENTICAL_STREAK (default: 8 trades) of non-trivial size.

Trading counter-trend or posting passive limit orders into an algorithmic iceberg leads to persistent
inventory depletion and catastrophic adverse selection.

When algorithmic trade size uniformity is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade volumes (volume > 0.0, ts=None).
- Tracks consecutive identical trade size streak.
- Maintains rolling window of WINDOW_SIZE = 15 trade volumes.
- Requires at least MIN_SAMPLES = 8 trades before CV evaluation.
- Calculates sample mean mu_V, sample standard deviation sigma_V, and CV_V.
- Blocks entries for COOLDOWN_SECONDS (45.0s) if CV_V <= 0.08 or identical streak >= 8.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive volumes are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_trade(volume, ts=None)                            -> None
  update(volume, ts=None)                                  -> None   (alias)
  get_dispersion_metrics()                                 -> dict
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
WINDOW_SIZE: int = 15
MIN_SAMPLES: int = 8
MIN_CHUNK_SIZE: float = 2.0            # 2.0 lots minimum size to avoid retail round-lot micro noise
MAX_UNIFORMITY_CV: float = 0.08        # <= 8% variation indicates algorithmic iceberg chunking
MAX_IDENTICAL_STREAK: int = 8          # 8 identical trades in a row
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_volumes = collections.deque(maxlen=WINDOW_SIZE)
_last_volume: Optional[float] = None
_identical_streak: int = 0
_latest_cv: float = 1.0
_latest_mean: float = 0.0
_blocked_until: float = 0.0


def _is_valid_volume(val: Any) -> bool:
    """Validate volume is a positive finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val > 0.0


def record_trade(volume: float, ts: Optional[float] = None) -> None:
    """
    Ingest a new trade volume, update dispersion statistics, and detect iceberg chunking.
    """
    global _last_volume, _identical_streak, _latest_cv, _latest_mean, _blocked_until

    if not _is_valid_volume(volume):
        return

    v = float(volume)

    with _lock:
        now = time.monotonic() if ts is None else float(ts)

        # Update identical volume streak
        if _last_volume is not None and abs(v - _last_volume) < 1e-6:
            _identical_streak += 1
        else:
            _identical_streak = 1
        _last_volume = v

        # Check Condition 1: Identical chunk streak of significant size
        if _identical_streak >= MAX_IDENTICAL_STREAK and v >= MIN_CHUNK_SIZE:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            _volumes.append(v)
            return

        _volumes.append(v)
        n = len(_volumes)
        if n < MIN_SAMPLES:
            return

        mean_val = sum(_volumes) / float(n)
        _latest_mean = mean_val

        variance = sum((x - mean_val) ** 2 for x in _volumes) / float(n - 1)
        std_val = math.sqrt(variance)
        cv = std_val / max(1e-6, mean_val)
        _latest_cv = cv

        # Check Condition 2: Algorithmic chunking uniformity collapse
        if cv <= MAX_UNIFORMITY_CV and mean_val >= MIN_CHUNK_SIZE:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(volume: float, ts: Optional[float] = None) -> None:
    """Alias for record_trade()."""
    record_trade(volume, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to iceberg chunking."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_dispersion_metrics() -> Dict[str, float]:
    """Return latest calculated volume mean, CV, and identical streak."""
    with _lock:
        return {
            "mean_volume": _latest_mean,
            "volume_cv": _latest_cv,
            "identical_streak": float(_identical_streak),
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the trade size clustering guard."""
    with _lock:
        now = time.monotonic()
        return {
            "mean_volume": _latest_mean,
            "volume_cv": _latest_cv,
            "identical_streak": _identical_streak,
            "sample_count": len(_volumes),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "min_chunk_size": MIN_CHUNK_SIZE,
            "max_uniformity_cv": MAX_UNIFORMITY_CV,
            "max_identical_streak": MAX_IDENTICAL_STREAK,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset volume history, streak counters, and active cooldown blocks."""
    global _last_volume, _identical_streak, _latest_cv, _latest_mean, _blocked_until
    with _lock:
        _volumes.clear()
        _last_volume = None
        _identical_streak = 0
        _latest_cv = 1.0
        _latest_mean = 0.0
        _blocked_until = 0.0
