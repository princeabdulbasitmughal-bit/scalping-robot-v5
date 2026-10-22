"""
wave181_trade_clustering_dispersion_guard.py
---------------------------------------------
Guard: Trade Arrival Clustering & Fano Factor Dispersion Guard

Measures order flow clustering and non-Poissonian trade arrival bursts via the Fano Factor of
high-frequency trade arrival counts:
    FF = Var(N_trades) / E[N_trades]

In healthy continuous double auction markets, trade arrivals follow standard point processes
(e.g. Poisson or quasi-Poissonian flow) where variance is roughly proportional to the mean:
    FF ~ 0.8 to 2.0

During aggressive liquidation cascades, news releases, or flash crashes, orders arrive in intense,
highly overdispersed bursts (e.g. 0, 0, 0, 25, 30, 0, 0, 35 trades per second) as margin engines
and cascading stop orders trigger simultaneously.
This results in an explosive spike in the Fano Factor:
    FF >= MAX_FANO_FACTOR (default: 4.0)

When high trade clustering is detected, order book depth is subjected to extreme toxic flow and
high adverse selection. The guard suspends new entries for COOLDOWN_SECONDS (default: 60.0s) until
the clustered cascade subsides.

Logic:
- Records trade arrivals into standardized time slices (SLICE_SECONDS = 1.0s).
- Fills empty intermediate slices with zero counts when no trades occur.
- Maintains rolling window of WINDOW_SLICES = 20 slices.
- Requires at least MIN_SLICES = 10 completed slices before evaluation.
- Requires minimum baseline activity (mean >= MIN_MEAN_RATE = 1.0 trade/slice).
- Computes sample mean, variance, and Fano Factor (FF = Var / Mean).
- If FF >= MAX_FANO_FACTOR (4.0):
    blocks entries for COOLDOWN_SECONDS (60.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative timestamps are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_trade(ts=None)                                    -> None
  update(ts=None)                                          -> None   (alias)
  get_fano_factor()                                        -> float
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
MAX_FANO_FACTOR: float = 4.0          # Fano Factor >= 4.0 indicates extreme burst clustering
SLICE_SECONDS: float = 1.0            # Duration of each discrete trade counting slice
WINDOW_SLICES: int = 20               # Rolling window of completed slices
MIN_SLICES: int = 10                  # Minimum slices before evaluating Fano Factor
MIN_MEAN_RATE: float = 1.0            # Minimum mean trade rate per slice to qualify
COOLDOWN_SECONDS: float = 60.0        # Block duration on clustered trade cascade


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_curr_slice_idx: Optional[int] = None
_curr_slice_count: int = 0
_slices: Deque[int] = collections.deque(maxlen=WINDOW_SLICES)
_latest_fano_factor: float = 1.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_trade(ts=None) -> None:
    """Record an incoming trade arrival and evaluate Fano Factor dispersion."""
    if ts is not None:
        if isinstance(ts, bool) or not isinstance(ts, (int, float)):
            return
        if math.isnan(ts) or math.isinf(ts) or ts < 0.0:
            return
        current_ts = float(ts)
    else:
        current_ts = time.monotonic()

    global _curr_slice_idx, _curr_slice_count, _latest_fano_factor, _blocked_until
    with _lock:
        slice_idx = int(math.floor(current_ts / SLICE_SECONDS))

        if _curr_slice_idx is None:
            _curr_slice_idx = slice_idx
            _curr_slice_count = 1
            return

        if slice_idx == _curr_slice_idx:
            _curr_slice_count += 1
        elif slice_idx > _curr_slice_idx:
            # Commit finished slice
            _slices.append(_curr_slice_count)

            # Insert zeros for skipped slices
            missed = slice_idx - _curr_slice_idx - 1
            if missed > 0:
                for _ in range(min(missed, WINDOW_SLICES)):
                    _slices.append(0)

            _curr_slice_idx = slice_idx
            _curr_slice_count = 1
        else:
            # Out-of-order tick arriving slightly late
            _curr_slice_count += 1

        if len(_slices) < MIN_SLICES:
            return

        # Calculate sample mean and variance
        n = len(_slices)
        mean_rate = sum(_slices) / float(n)
        if mean_rate < MIN_MEAN_RATE:
            _latest_fano_factor = 1.0
            return

        variance = sum((x - mean_rate) ** 2 for x in _slices) / float(n)
        fano = variance / mean_rate
        _latest_fano_factor = fano

        if fano >= MAX_FANO_FACTOR:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(ts=None) -> None:
    """Alias for record_trade()."""
    record_trade(ts=ts)


def is_entry_blocked() -> bool:
    """Return True if high trade arrival clustering has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_fano_factor() -> float:
    """Return the most recently computed Fano Factor."""
    with _lock:
        return _latest_fano_factor


def get_status() -> Dict[str, Any]:
    """Return a diagnostic snapshot of the trade clustering guard state."""
    with _lock:
        now = time.monotonic()
        return {
            "fano_factor": _latest_fano_factor,
            "completed_slices": len(_slices),
            "max_slices": WINDOW_SLICES,
            "min_slices": MIN_SLICES,
            "slice_seconds": SLICE_SECONDS,
            "max_fano_threshold": MAX_FANO_FACTOR,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset all slice counts, Fano Factor metrics, and active blocks."""
    global _curr_slice_idx, _curr_slice_count, _latest_fano_factor, _blocked_until
    with _lock:
        _curr_slice_idx = None
        _curr_slice_count = 0
        _slices.clear()
        _latest_fano_factor = 1.0
        _blocked_until = 0.0
