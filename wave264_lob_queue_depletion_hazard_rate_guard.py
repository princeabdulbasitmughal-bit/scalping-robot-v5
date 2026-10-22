"""
wave264_lob_queue_depletion_hazard_rate_guard.py
------------------------------------------------
Guard: LOB Queue Depletion Survival Hazard Rate Guard

Monitors empirical instantaneous hazard rates and rapid survival collapse of limit order book queue depth
(Cho & Nelling 2000; Lo, MacKinlay & Zhang 2002; Hautsch 2012):
    Queue Depth:                Q_{total} = Q_{bid} + Q_{ask}
    Fractional Depletion:       Delta Q_{frac} = (Q_{prev} - Q_{curr}) / max(Q_{prev}, 0.10)
    Depletion Event:            Delta Q_{frac} >= 0.50 (depth drops by >= 50% from previous tick)
    Hazard Rate:                lambda_{deplete}(W) = N_{events}(W) / W  (events / sec over W = 30.0s)
    Acute Vaporization:         Delta Q_{frac} >= 0.80 within Delta t <= 0.20s (200ms)

Under orderly continuous double-auction conditions:
    - Queue depths exhibit high survival persistence; depletion is gradual and offset by queue replenishment.
    - Hazard rates remain subdued: lambda_{deplete} <= 0.10 events/sec.

During predatory front-running, quote cancellation avalanches, or aggressive sweep cascades:
    - Queue depth vaporizes instantaneously without replenishment:
        1) Elevated Queue Depletion Hazard Rate:
           lambda_{deplete} >= MAX_HAZARD_RATE (default: 0.25 events/s) over rolling W = 30.0s with N >= 5 events.
        2) Acute Instantaneous Queue Vaporization:
           Delta Q_{frac} >= ACUTE_DEPLETION_RATIO (0.80) occurring within Delta t <= ACUTE_DEPLETION_TIME_SEC (0.20s).

Placing scalping or limit orders during queue survival collapse exposes executions to zero queue priority,
severe fill slippage, and immediate adverse price movement.

When elevated depletion hazard or acute queue vaporization is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests top-of-book depths via record_depth(bid_depth, ask_depth, ts=None) or
  direct events via record_depletion_event(fraction_depleted, duration_sec=None, ts=None).
- Maintains timestamped deque of depletion events over rolling WINDOW_SECONDS = 30.0s.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative depths are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_depth(bid_depth, ask_depth, ts=None)                                                  -> None
  record_depletion_event(fraction_depleted, duration_sec=None, ts=None)                         -> None
  update(bid_depth, ask_depth=None, ts=None)                                                   -> None   (alias)
  get_hazard_metrics(now_ts=None)                                                              -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any, Deque, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SECONDS: float = 30.0            # 30.0s rolling observation window
MIN_DEPLETION_EVENTS: int = 5           # 5 events minimum for hazard rate evaluation
MAX_HAZARD_RATE: float = 0.25           # 0.25 events/sec maximum acceptable hazard rate (>=8 in 30s)
ACUTE_DEPLETION_RATIO: float = 0.80     # 80% single-step depth collapse threshold
ACUTE_DEPLETION_TIME_SEC: float = 0.20  # 200ms maximum duration for acute vaporization
COOLDOWN_SECONDS: float = 45.0          # 45.0s block duration

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_events: Deque[Tuple[float, float]] = collections.deque()  # (ts, fraction_depleted)
_prev_depth: Optional[float] = None
_prev_depth_ts: Optional[float] = None
_latest_hazard_rate: float = 0.0
_latest_depletion_frac: float = 0.0
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


def _is_valid_numeric(val: Any) -> bool:
    """Validate value is a finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return True


def _purge_old_events(now_ts: float) -> None:
    """Remove events older than WINDOW_SECONDS from the rolling deque."""
    cutoff = now_ts - WINDOW_SECONDS
    while _events and _events[0][0] < cutoff:
        _events.popleft()


def record_depletion_event(
    fraction_depleted: float,
    duration_sec: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Directly ingest a measured queue depletion event.
    """
    global _latest_hazard_rate, _latest_depletion_frac, _prev_depth_ts, _blocked_until

    if not _is_valid_numeric(fraction_depleted):
        return

    frac = max(0.0, min(1.0, float(fraction_depleted)))
    dt = float(duration_sec) if (duration_sec is not None and _is_valid_numeric(duration_sec)) else 1.0
    now = float(ts) if (ts is not None and _is_valid_numeric(ts)) else time.time()

    with _lock:
        _latest_depletion_frac = frac
        _prev_depth_ts = now

        # Condition 2: Acute Instantaneous Queue Vaporization
        if frac >= ACUTE_DEPLETION_RATIO and dt <= ACUTE_DEPLETION_TIME_SEC:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        if frac >= 0.50:
            _purge_old_events(now)
            _events.append((now, frac))

            if len(_events) >= MIN_DEPLETION_EVENTS:
                rate = len(_events) / WINDOW_SECONDS
                _latest_hazard_rate = rate

                # Condition 1: Elevated Queue Depletion Hazard Rate
                if rate >= MAX_HAZARD_RATE:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                    return


def record_depth(
    bid_depth: float,
    ask_depth: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest bid and ask depths, detect queue depletion events, and calculate hazard rate.
    """
    global _prev_depth, _prev_depth_ts, _latest_hazard_rate, _latest_depletion_frac, _blocked_until

    if not (_is_valid_non_negative(bid_depth) and _is_valid_non_negative(ask_depth)):
        return

    bq = float(bid_depth)
    aq = float(ask_depth)
    curr_depth = bq + aq
    now = float(ts) if (ts is not None and _is_valid_numeric(ts)) else time.time()

    with _lock:
        if _prev_depth is not None and _prev_depth_ts is not None and _prev_depth > 0.0:
            dt = max(0.001, now - _prev_depth_ts)
            if curr_depth < _prev_depth:
                frac = (_prev_depth - curr_depth) / _prev_depth
                _latest_depletion_frac = frac

                # Condition 2: Acute Instantaneous Queue Vaporization
                if frac >= ACUTE_DEPLETION_RATIO and dt <= ACUTE_DEPLETION_TIME_SEC:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                    _prev_depth = curr_depth
                    _prev_depth_ts = now
                    return

                # Record substantial depletion (>= 50%)
                if frac >= 0.50:
                    _purge_old_events(now)
                    _events.append((now, frac))

                    if len(_events) >= MIN_DEPLETION_EVENTS:
                        rate = len(_events) / WINDOW_SECONDS
                        _latest_hazard_rate = rate

                        # Condition 1: Elevated Queue Depletion Hazard Rate
                        if rate >= MAX_HAZARD_RATE:
                            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                            _prev_depth = curr_depth
                            _prev_depth_ts = now
                            return

        _prev_depth = curr_depth
        _prev_depth_ts = now


def update(
    bid_depth: float,
    ask_depth: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """Module alias for record_depth or direct depletion event."""
    if ask_depth is None:
        record_depletion_event(bid_depth, ts=ts)
    else:
        record_depth(bid_depth, ask_depth, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if entry is currently blocked by depletion hazard guard."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked."""
    return is_entry_blocked()


def get_hazard_metrics(now_ts: Optional[float] = None) -> Dict[str, Any]:
    """Return dictionary of current queue depletion hazard metrics."""
    with _lock:
        if now_ts is not None and _is_valid_numeric(now_ts):
            now = float(now_ts)
        elif _prev_depth_ts is not None and _prev_depth_ts < 1_000_000_000.0:
            now = _prev_depth_ts
        else:
            now = time.time()
        _purge_old_events(now)
        rate = len(_events) / WINDOW_SECONDS if WINDOW_SECONDS > 0 else 0.0
        return {
            "depletion_events_count": len(_events),
            "hazard_rate": round(rate, 4),
            "latest_depletion_frac": round(_latest_depletion_frac, 4),
            "window_seconds": WINDOW_SECONDS,
            "min_depletion_events": MIN_DEPLETION_EVENTS,
            "max_hazard_rate": MAX_HAZARD_RATE,
            "acute_depletion_ratio": ACUTE_DEPLETION_RATIO,
            "is_blocked": is_entry_blocked(),
        }


def get_status() -> Dict[str, Any]:
    """Return complete status dictionary."""
    with _lock:
        remaining_cd = max(0.0, _blocked_until - time.monotonic())
        metrics = get_hazard_metrics()
        metrics["cooldown_remaining_sec"] = round(remaining_cd, 2)
        return metrics


def reset() -> None:
    """Reset all state to initial defaults."""
    global _events, _prev_depth, _prev_depth_ts, _latest_hazard_rate, _latest_depletion_frac, _blocked_until
    with _lock:
        _events.clear()
        _prev_depth = None
        _prev_depth_ts = None
        _latest_hazard_rate = 0.0
        _latest_depletion_frac = 0.0
        _blocked_until = 0.0
