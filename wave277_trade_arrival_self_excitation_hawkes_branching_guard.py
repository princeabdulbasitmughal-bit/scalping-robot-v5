"""
wave277_trade_arrival_self_excitation_hawkes_branching_guard.py
---------------------------------------------------------------
Guard: High-Frequency Hawkes Process Branching Ratio & Criticality Guard

Monitors self-exciting point process dynamics, endogenous trade clustering, and Hawkes branching ratio criticality
(Hawkes 1971; Hardiman, Bercot & Bouchaud 2013; Bacry et al. 2015):
    Self-Exciting Intensity:    lambda(t) = mu + sum_{t_i < t} alpha * exp(-beta * (t - t_i))
    Endogenous Branching Ratio: eta = alpha / beta in [0.0, 1.0)
    Empirical Branching Proxy:  \\hat{eta} = N(Delta t <= 50.0 ms) / N_{total} over rolling W = 20.0s
    Supercritical Streak:       L_{cascade} = consecutive trades with Delta t <= 30.0 ms

Under standard subcritical, stationary market conditions:
    - Order flow is primarily exogenous (news/liquidity demand); endogenous feedback is mild: \\hat{eta} <= 0.45.
    - Cascades dissipate quickly without self-sustaining panic feedback loops.

During algorithmic flash cascades, stop-loss avalanches, or supercritical queue sweeps:
    - Endogenous feedback approaches or exceeds criticality (\\hat{eta} -> 1.0):
        1) Supercritical Hawkes Branching Ratio:
           \\hat{eta} >= MAX_BRANCHING_RATIO (default: 0.80) with total trades N_{total} >= MIN_TRADES (25 trades)
           within rolling W = 20.0s window.
        2) Acute Supercritical Cascade Streak:
           L_{cascade} >= MAX_CASCADE_STREAK (default: 12 consecutive trades with Delta t <= 30.0 ms).

Trading into a supercritical self-exciting cascade guarantees queue bypass, extreme slippage,
and catastrophic adverse selection.

When supercritical branching or an acute cascade streak is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade arrival durations via record_duration(duration_ms, ts=None) or
  direct branching ratio via record_branching(branching_ratio, sample_count=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 30 trade durations.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive durations are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_duration(duration_ms, ts=None)                                                        -> None
  record_branching(branching_ratio, sample_count=None, ts=None)                                 -> None
  update(duration_ms, ts=None)                                                                 -> None   (alias)
  get_branching_metrics()                                                                      -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any, Deque

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 30                   # 30 trade durations rolling window
MIN_TRADES: int = 25                    # 25 trades minimum for branching evaluation
MAX_BRANCHING_RATIO: float = 0.80       # 80% endogenous branching ratio threshold
CRITICAL_THRESHOLD_MS: float = 50.0     # 50.0 ms threshold for endogenous daughter event
MAX_CASCADE_STREAK: int = 12            # 12 consecutive trades with Delta t <= 30.0 ms
CASCADE_BURST_MS: float = 30.0          # 30.0 ms acute cascade threshold
COOLDOWN_SECONDS: float = 45.0          # 45.0s block duration

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_durations: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_current_cascade_streak: int = 0
_latest_branching_ratio: float = 0.20
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


def _is_valid_numeric(val: Any) -> bool:
    """Validate value is a finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return True


def record_branching(
    branching_ratio: float,
    sample_count: Optional[int] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Directly ingest precomputed Hawkes branching ratio.
    """
    global _latest_branching_ratio, _blocked_until

    if not _is_valid_numeric(branching_ratio):
        return

    eta = max(0.0, min(1.0, float(branching_ratio)))
    n = int(sample_count) if (sample_count is not None and isinstance(sample_count, int) and not isinstance(sample_count, bool) and sample_count > 0) else 25

    with _lock:
        _latest_branching_ratio = eta

        # Condition 1: Supercritical Hawkes Branching Ratio
        if eta >= MAX_BRANCHING_RATIO and n >= MIN_TRADES:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_duration(duration_ms: float, ts: Optional[float] = None) -> None:
    """
    Ingest a single trade inter-arrival duration in milliseconds.
    """
    global _durations, _current_cascade_streak, _latest_branching_ratio, _blocked_until

    if not _is_valid_positive(duration_ms):
        return

    dur = float(duration_ms)

    with _lock:
        # Update acute cascade streak
        if dur <= CASCADE_BURST_MS:
            _current_cascade_streak += 1
        else:
            _current_cascade_streak = 0

        # Condition 2: Acute Supercritical Cascade Streak
        if _current_cascade_streak >= MAX_CASCADE_STREAK:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            _durations.append(dur)
            return

        _durations.append(dur)

        if len(_durations) >= MIN_TRADES:
            clustered_count = sum(1 for d in _durations if d <= CRITICAL_THRESHOLD_MS)
            eta = clustered_count / float(len(_durations))
            _latest_branching_ratio = eta

            # Condition 1: Supercritical Hawkes Branching Ratio
            if eta >= MAX_BRANCHING_RATIO:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return


def update(duration_ms: float, ts: Optional[float] = None) -> None:
    """Module alias for record_duration."""
    record_duration(duration_ms, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if entry is currently blocked by Hawkes branching guard."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked."""
    return is_entry_blocked()


def get_branching_metrics() -> Dict[str, Any]:
    """Return dictionary of current branching metrics."""
    with _lock:
        return {
            "branching_ratio": round(_latest_branching_ratio, 4),
            "current_streak": _current_cascade_streak,
            "sample_count": len(_durations),
            "max_branching_ratio": MAX_BRANCHING_RATIO,
            "max_cascade_streak": MAX_CASCADE_STREAK,
            "is_blocked": is_entry_blocked(),
        }


def get_status() -> Dict[str, Any]:
    """Return complete status dictionary."""
    with _lock:
        remaining_cd = max(0.0, _blocked_until - time.monotonic())
        metrics = get_branching_metrics()
        metrics["cooldown_remaining_sec"] = round(remaining_cd, 2)
        return metrics


def reset() -> None:
    """Reset all state to initial defaults."""
    global _durations, _current_cascade_streak, _latest_branching_ratio, _blocked_until
    with _lock:
        _durations.clear()
        _current_cascade_streak = 0
        _latest_branching_ratio = 0.20
        _blocked_until = 0.0
