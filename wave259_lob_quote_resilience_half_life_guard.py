"""
wave259_lob_quote_resilience_half_life_guard.py
------------------------------------------------
Guard: Order Book Quote Depth Resilience Half-Life Guard

Monitors order book liquidity replenishment latency and depth recovery dynamics following aggressive sweeps
(Biais, Hillion & Spatt 1995; Large 2007; Ponzi, Lillo & Mantegna 2009):
    Total Top Depth:            Q_{total} = Q_{bid} + Q_{ask}
    Baseline Depth:             Q_{base} = median(Q_{total}, N=20)
    Depletion Event Trigger:    Q_{total} <= Q_{base} * DEPLETION_RATIO (0.50)
    Recovery Target:            Q_{rec} = Q_{base} * RECOVERY_RATIO (0.75)
    Replenishment Duration:     tau_{rec} = t_{recovery} - t_{depletion} (seconds)
    Mean Recovery Latency:      \\bar{tau} = (1 / K) * \\sum_{k=1}^K tau_{rec, k}

Under healthy, competitive market making conditions:
    - High-frequency market makers rapidly replenish depleted queues via limit orders:
      tau_{rec} is typically sub-second (median tau < 0.50s; \\bar{tau} <= 1.00s).

During predatory inventory runs, toxic quote cancellations, or market maker flight:
    - Depleted book levels remain hollow and unreplenished:
        1) Sluggish Replenishment Persistence:
           \\bar{tau} >= MAX_MEAN_RECOVERY_SEC (default: 2.00s) over K >= MIN_RECOVERY_SAMPLES (5 events).
        2) Acute Unrecovered Liquidity Hole:
           An acute depletion event where Q_{total} <= Q_{base} * 0.40 has persisted for
           Delta t_{hole} >= MAX_UNRECOVERED_SEC (default: 3.00s) without recovery.

Submitting market or limit orders into an unreplenished or slowly recovering order book guarantees
severe execution slippage and predatory adverse fills.

When sluggish replenishment or an acute liquidity hole is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests top-of-book depths via record_depths(bid_depth, ask_depth, ts=None) or
  recovery durations via record_recovery_duration(duration_sec, ts=None).
- Maintains rolling history of baseline depths and completed recovery events.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative depths are rejected.

Aliases (required):
  is_entry_blocked()                                            -> bool
  is_blocked()                                                  -> bool   (alias)
  record_depths(bid_depth, ask_depth, ts=None)                  -> None
  record_recovery_duration(duration_sec, ts=None)               -> None
  update(bid_depth, ask_depth=None, ts=None)                    -> None   (alias)
  get_resilience_metrics()                                      -> dict
  get_status()                                                  -> dict
  reset()                                                       -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Dict, Optional, Any, Deque

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASELINE_WINDOW: int = 20                # 20 depth samples for rolling baseline
DEPLETION_RATIO: float = 0.50            # Depth drops to <= 50% baseline -> depletion event
RECOVERY_RATIO: float = 0.75             # Depth recovers to >= 75% baseline -> recovered
MIN_RECOVERY_SAMPLES: int = 5            # Minimum 5 completed recovery events for average
MAX_MEAN_RECOVERY_SEC: float = 2.00      # 2.00s max acceptable average replenishment latency
MAX_UNRECOVERED_SEC: float = 3.00        # 3.00s maximum duration for acute unrecovered hole
ACUTE_DEPLETION_RATIO: float = 0.40      # 40% of baseline depth for acute hole trigger
COOLDOWN_SECONDS: float = 45.0           # 45.0s block duration

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_depth_history: Deque[float] = collections.deque(maxlen=BASELINE_WINDOW)
_recovery_durations: Deque[float] = collections.deque(maxlen=15)
_active_depletion_start_ts: Optional[float] = None
_active_depletion_base: Optional[float] = None
_latest_total_depth: float = 10.0
_latest_mean_recovery_sec: float = 0.0
_blocked_until: float = 0.0


def _is_valid_non_negative(val: Any) -> bool:
    """Validate value is a non-negative finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val >= 0.0


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


def record_recovery_duration(duration_sec: float, ts: Optional[float] = None) -> None:
    """
    Directly ingest a measured order book replenishment recovery duration in seconds.
    """
    global _latest_mean_recovery_sec, _blocked_until

    if not _is_valid_non_negative(duration_sec):
        return

    dur = float(duration_sec)

    with _lock:
        _recovery_durations.append(dur)
        if len(_recovery_durations) >= MIN_RECOVERY_SAMPLES:
            mean_dur = statistics.mean(_recovery_durations)
            _latest_mean_recovery_sec = mean_dur

            # Condition 1: Sluggish Replenishment Persistence
            if mean_dur >= MAX_MEAN_RECOVERY_SEC:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return


def record_depths(bid_depth: float, ask_depth: float, ts: Optional[float] = None) -> None:
    """
    Ingest bid and ask top-of-book depths and track depletion/replenishment dynamics.
    """
    global _latest_total_depth, _active_depletion_start_ts, _active_depletion_base
    global _latest_mean_recovery_sec, _blocked_until

    if not (_is_valid_non_negative(bid_depth) and _is_valid_non_negative(ask_depth)):
        return

    bq = float(bid_depth)
    aq = float(ask_depth)
    total_depth = bq + aq
    now = float(ts) if (ts is not None and _is_valid_numeric(ts)) else time.time()

    with _lock:
        _latest_total_depth = total_depth

        # Calculate current baseline depth
        base_depth = statistics.median(_depth_history) if len(_depth_history) >= 5 else 10.0

        # Check if we are currently in an active depletion tracking cycle
        if _active_depletion_start_ts is not None and _active_depletion_base is not None:
            # Check for recovery completion
            recovery_target = _active_depletion_base * RECOVERY_RATIO
            if total_depth >= recovery_target:
                recovery_time = max(0.0, now - _active_depletion_start_ts)
                _active_depletion_start_ts = None
                _active_depletion_base = None

                _recovery_durations.append(recovery_time)
                if len(_recovery_durations) >= MIN_RECOVERY_SAMPLES:
                    mean_dur = statistics.mean(_recovery_durations)
                    _latest_mean_recovery_sec = mean_dur
                    if mean_dur >= MAX_MEAN_RECOVERY_SEC:
                        _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                        return
            else:
                # Still unrecovered: check Condition 2 (Acute Unrecovered Liquidity Hole)
                unrecovered_duration = now - _active_depletion_start_ts
                if (
                    total_depth <= _active_depletion_base * ACUTE_DEPLETION_RATIO
                    and unrecovered_duration >= MAX_UNRECOVERED_SEC
                ):
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                    return
        else:
            # Check for new depletion event trigger
            depletion_threshold = base_depth * DEPLETION_RATIO
            if total_depth <= depletion_threshold and base_depth > 0.0:
                _active_depletion_start_ts = now
                _active_depletion_base = base_depth

        # Update baseline history only if depth is not severely depleted
        if base_depth > 0.0 and total_depth > base_depth * DEPLETION_RATIO:
            _depth_history.append(total_depth)
        elif len(_depth_history) < 5:
            _depth_history.append(total_depth)


def update(bid_depth: float, ask_depth: Optional[float] = None, ts: Optional[float] = None) -> None:
    """Module alias for record_depths or single combined depth."""
    if ask_depth is None:
        # Treat bid_depth as recovery duration if single float provided
        record_recovery_duration(bid_depth, ts=ts)
    else:
        record_depths(bid_depth, ask_depth, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if entry is currently blocked by resilience guard."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked."""
    return is_entry_blocked()


def get_resilience_metrics() -> Dict[str, Any]:
    """Return dictionary of current resilience metrics."""
    with _lock:
        mean_dur = statistics.mean(_recovery_durations) if _recovery_durations else 0.0
        base_depth = statistics.median(_depth_history) if _depth_history else 10.0
        return {
            "latest_total_depth": round(_latest_total_depth, 4),
            "baseline_depth": round(base_depth, 4),
            "recovery_events_count": len(_recovery_durations),
            "mean_recovery_sec": round(mean_dur, 4),
            "is_in_depletion": _active_depletion_start_ts is not None,
            "max_mean_recovery_sec": MAX_MEAN_RECOVERY_SEC,
            "max_unrecovered_sec": MAX_UNRECOVERED_SEC,
            "is_blocked": is_entry_blocked(),
        }


def get_status() -> Dict[str, Any]:
    """Return complete status dictionary."""
    with _lock:
        remaining_cd = max(0.0, _blocked_until - time.monotonic())
        metrics = get_resilience_metrics()
        metrics["cooldown_remaining_sec"] = round(remaining_cd, 2)
        return metrics


def reset() -> None:
    """Reset all state to initial defaults."""
    global _depth_history, _recovery_durations, _active_depletion_start_ts
    global _active_depletion_base, _latest_total_depth, _latest_mean_recovery_sec, _blocked_until
    with _lock:
        _depth_history.clear()
        _recovery_durations.clear()
        _active_depletion_start_ts = None
        _active_depletion_base = None
        _latest_total_depth = 10.0
        _latest_mean_recovery_sec = 0.0
        _blocked_until = 0.0
