"""
wave234_queue_depth_replenishment_latency_guard.py
---------------------------------------------------
Guard: Top-of-Book Queue Replenishment Latency Blowout & Recovery Deficit Guard

Monitors limit order book touch depth replenishment latency following sweep consumption
(Bouchaud et al. 2004; Farmer, Patelli & Zovko 2005):
    Baseline Depth:        Q_{baseline} = rolling mean touch depth (lots)
    Drain Event:           Q_{touch} drops by >= 50% from baseline
    Replenishment Latency: tau_{replenish} = t_{recover} - t_{drain} (sec) to restore >= 80% baseline
    Void Duration:         dt_{void} = t - t_{drain} (sec) without recovery

In healthy, highly competitive electronic order books:
    - Liquidity providers replenish depth at the touch almost immediately:
      tau_{replenish} < 0.30s, with deep standing queues restored.

During liquidity provider retreat, toxicity alerts, or impending level breaches:
    - Order book depth remains depleted, and replenishment latency explodes:
        1) Replenishment Latency Blowout:
           tau_{replenish} >= MAX_REPLENISH_LATENCY_SEC (default: 1.20s).
        2) Unreplenished Void Timeout:
           dt_{void} >= UNREPLENISHED_TIMEOUT_SEC (default: 2.0s) without restoring 80% baseline,
           on baseline depth >= 10.0 lots.

Trading into an unreplenished, lingering depth vacuum guarantees extreme execution slippage
and adverse level collapse.

When queue replenishment latency blowout or void timeout is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests touch depth via record_touch_depth(depth, ts=None)
  or record_queue_drain(prior_depth, post_depth, ts=None).
- Maintains rolling window of WINDOW_SIZE = 20 depth observations.
- Computes replenishment latency tau_{replenish} and void duration dt_{void}.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative depths are rejected.

Aliases (required):
  is_entry_blocked()                                                   -> bool
  is_blocked()                                                         -> bool   (alias)
  record_touch_depth(depth, ts=None)                                   -> None
  record_queue_drain(prior_depth, post_depth, ts=None)                 -> None
  update(depth, ts=None)                                               -> None   (alias)
  get_latency_metrics()                                                -> dict
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
MIN_SAMPLES: int = 8
MAX_REPLENISH_LATENCY_SEC: float = 1.20   # 1.20 seconds maximum allowable replenishment latency
UNREPLENISHED_TIMEOUT_SEC: float = 2.0    # 2.0 seconds void timeout
MIN_BASELINE_DEPTH: float = 10.0          # 10.0 lots minimum baseline depth
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_depths = collections.deque(maxlen=WINDOW_SIZE)
_drain_start_ts: Optional[float] = None
_drain_prior_depth: float = 0.0
_latest_mean_depth: float = 20.0
_latest_replenish_latency: float = 0.0
_latest_void_duration: float = 0.0
_blocked_until: float = 0.0


def _is_valid_depth(val: Any) -> bool:
    """Validate depth is a non-negative finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val >= 0.0


def record_touch_depth(
    depth: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest touch depth and monitor drain / replenishment timing.
    """
    global _drain_start_ts, _drain_prior_depth
    global _latest_mean_depth, _latest_replenish_latency, _latest_void_duration, _blocked_until

    if not _is_valid_depth(depth):
        return

    q = float(depth)

    with _lock:
        now = time.monotonic() if ts is None else float(ts)

        n = len(_depths)
        mean_q = sum(_depths) / float(n) if n >= MIN_SAMPLES else 20.0
        _latest_mean_depth = mean_q

        # Detect depth drain (drop by >= 50% from baseline)
        if mean_q >= MIN_BASELINE_DEPTH and q <= 0.50 * mean_q:
            if _drain_start_ts is None:
                _drain_start_ts = now
                _drain_prior_depth = mean_q

        # If currently in a drained void state:
        if _drain_start_ts is not None:
            void_dt = max(0.0, now - _drain_start_ts)
            _latest_void_duration = void_dt

            # Check Condition 2: Unreplenished Void Timeout
            if void_dt >= UNREPLENISHED_TIMEOUT_SEC and q <= 0.60 * _drain_prior_depth:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return

            # Check Recovery (restored to >= 80% of prior baseline)
            if q >= 0.80 * _drain_prior_depth:
                latency = now - _drain_start_ts
                _latest_replenish_latency = latency
                _drain_start_ts = None

                # Check Condition 1: Replenishment Latency Blowout
                if latency >= MAX_REPLENISH_LATENCY_SEC:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                    return

        _depths.append(q)


def record_queue_drain(
    prior_depth: float,
    post_depth: float,
    ts: Optional[float] = None,
) -> None:
    """
    Record an explicit queue drain event with prior and post depth.
    """
    if not _is_valid_depth(prior_depth) or not _is_valid_depth(post_depth):
        return
    record_touch_depth(prior_depth, ts)
    record_touch_depth(post_depth, ts)


def update(depth: float, ts: Optional[float] = None) -> None:
    """Alias for record_touch_depth()."""
    record_touch_depth(depth, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to replenishment latency blowout."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_latency_metrics() -> Dict[str, float]:
    """Return latest calculated replenishment latency, void duration, and mean depth."""
    with _lock:
        return {
            "mean_depth": _latest_mean_depth,
            "replenish_latency_sec": _latest_replenish_latency,
            "void_duration_sec": _latest_void_duration,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the replenishment latency guard."""
    with _lock:
        now = time.monotonic()
        return {
            "mean_depth": _latest_mean_depth,
            "replenish_latency_sec": _latest_replenish_latency,
            "void_duration_sec": _latest_void_duration,
            "sample_count": len(_depths),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "max_replenish_latency_sec": MAX_REPLENISH_LATENCY_SEC,
            "unreplenished_timeout_sec": UNREPLENISHED_TIMEOUT_SEC,
            "min_baseline_depth": MIN_BASELINE_DEPTH,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset depth history, drain timers, metrics, and active cooldown blocks."""
    global _drain_start_ts, _drain_prior_depth
    global _latest_mean_depth, _latest_replenish_latency, _latest_void_duration, _blocked_until
    with _lock:
        _depths.clear()
        _drain_start_ts = None
        _drain_prior_depth = 0.0
        _latest_mean_depth = 20.0
        _latest_replenish_latency = 0.0
        _latest_void_duration = 0.0
        _blocked_until = 0.0
