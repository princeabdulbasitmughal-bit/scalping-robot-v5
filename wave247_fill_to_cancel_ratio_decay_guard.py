"""
wave247_fill_to_cancel_ratio_decay_guard.py
---------------------------------------------
Guard: Limit Order Fill-to-Cancel Ratio Decay & Toxic Fading Guard

Monitors empirical ratio of executed trade fills to order cancellations
(O'Hara 2015; Hasbrouck & Saar 2013):
    Fill-to-Cancel Ratio:    \\theta_{fill/cancel} = N_{fill} / max(1, N_{cancel})
    Acute Toxic Churn:       Cancellations in [t - 2.0s, t] with zero fills

In orderly, sustainable market making environments:
    - Fills arrive in reasonable proportion to quote cancellations:
      \\theta_{fill/cancel} >= 0.15 - 0.35 (1 fill per 3 - 6 cancellations).

During aggressive quote stuffing, spoof teasing, predatory phantom liquidity pulsing, or rapid market maker retreat:
    - Cancellations explode while fill efficiency collapses to near-zero:
        1) Severe Fill-to-Cancel Ratio Collapse:
           \\theta_{fill/cancel} <= MIN_FILL_CANCEL_RATIO (default: 0.025 or 1 fill per 40 cancels) AND
           N_{cancel} >= MIN_CANCELS_THRESHOLD (default: 40 cancellations) over rolling N=60 events.
        2) Acute Toxic Cancellation Explosion:
           Acute cancellations >= ACUTE_CANCEL_EXPLOSION (default: 35 cancels in <= 2.0s) AND
           acute fills == 0.

Attempting to post passive limit orders or trade against decaying fill-to-cancel books guarantees
immediate queue abandonment, phantom liquidity evaporations, and severe adverse selection.

When fill-to-cancel collapse or acute cancel explosion is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests events via record_event(event_type, ts=None) or
  direct counts via record_counts(fills_count, cancels_count, ts=None).
- Maintains rolling history of WINDOW_SIZE = 60 order events.
- Evaluates \\theta_{fill/cancel}, N_{cancel}, and acute 2.0s cancellation bursts.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, negative counts, or invalid event types are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_event(event_type, ts=None)                                                            -> None
  record_counts(fills_count, cancels_count, ts=None)                                           -> None
  update(event_type, ts=None)                                                                  -> None   (alias)
  get_ratio_metrics()                                                                          -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any, Union

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 60
MIN_CANCELS_THRESHOLD: int = 40        # 40 cancellations in window
MIN_FILL_CANCEL_RATIO: float = 0.025   # 0.025 ratio ceiling (1 fill per 40 cancels)
ACUTE_CANCEL_EXPLOSION: int = 35       # 35 cancellations in <= 2.0s with 0 fills
ACUTE_WINDOW_SECONDS: float = 2.0
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_events_history = collections.deque(maxlen=WINDOW_SIZE)  # elements: (timestamp, is_fill: bool)
_latest_fills: int = 0
_latest_cancels: int = 0
_latest_ratio: float = 1.0
_latest_acute_cancels: int = 0
_blocked_until: float = 0.0


def _parse_event_type(val: Any) -> Optional[bool]:
    """Parse event into True (fill/trade) or False (cancel). Returns None if invalid."""
    if isinstance(val, bool):
        return None  # reject raw booleans to prevent accidental typing
    if isinstance(val, (int, float)):
        if math.isnan(val) or math.isinf(val):
            return None
        if val == 1:
            return True
        elif val == 0:
            return False
        return None
    if isinstance(val, str):
        s = val.strip().lower()
        if s in ("fill", "trade", "execution", "f"):
            return True
        elif s in ("cancel", "cancellation", "c"):
            return False
    return None


def _is_valid_non_negative(val: Any) -> bool:
    """Validate value is a non-negative finite numeric float or int."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val >= 0.0


def record_event(
    event_type: Union[str, int, float],
    ts: Optional[float] = None,
) -> None:
    """
    Ingest a single order lifecycle event: fill (True) or cancellation (False).
    """
    global _latest_fills, _latest_cancels, _latest_ratio, _latest_acute_cancels, _blocked_until

    is_fill = _parse_event_type(event_type)
    if is_fill is None:
        return

    now = float(ts) if ts is not None else time.time()

    with _lock:
        _events_history.append((now, is_fill))

        n_fill = sum(1 for _, f in _events_history if f)
        n_cancel = sum(1 for _, f in _events_history if not f)
        ratio = n_fill / max(1, n_cancel)

        # Acute cancellations over last ACUTE_WINDOW_SECONDS
        acute_cancels = 0
        acute_fills = 0
        for t_evt, f in reversed(_events_history):
            if (now - t_evt) <= ACUTE_WINDOW_SECONDS:
                if f:
                    acute_fills += 1
                else:
                    acute_cancels += 1
            else:
                break

        _latest_fills = n_fill
        _latest_cancels = n_cancel
        _latest_ratio = ratio
        _latest_acute_cancels = acute_cancels

        # Condition 1: Acute toxic cancellation explosion (35 cancels, 0 fills in <= 2.0s)
        if acute_cancels >= ACUTE_CANCEL_EXPLOSION and acute_fills == 0:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 2: Severe fill-to-cancel ratio collapse
        if n_cancel >= MIN_CANCELS_THRESHOLD and ratio <= MIN_FILL_CANCEL_RATIO:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_counts(
    fills_count: int,
    cancels_count: int,
    ts: Optional[float] = None,
) -> None:
    """
    Bulk ingest counts of fills and cancellations.
    """
    global _latest_fills, _latest_cancels, _latest_ratio, _blocked_until

    if not _is_valid_non_negative(fills_count) or not _is_valid_non_negative(cancels_count):
        return

    nf = int(fills_count)
    nc = int(cancels_count)

    with _lock:
        ratio = nf / max(1, nc)
        _latest_fills = nf
        _latest_cancels = nc
        _latest_ratio = ratio

        if nc >= MIN_CANCELS_THRESHOLD and ratio <= MIN_FILL_CANCEL_RATIO:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(
    event_type: Union[str, int, float],
    ts: Optional[float] = None,
) -> None:
    """Alias for record_event()."""
    record_event(event_type, ts)


def is_entry_blocked() -> bool:
    """Check if new entries are blocked by fill-to-cancel decay or cancellation explosion."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_ratio_metrics() -> Dict[str, float]:
    """Retrieve current fill-to-cancel ratio metrics."""
    with _lock:
        return {
            "fills_count": float(_latest_fills),
            "cancels_count": float(_latest_cancels),
            "fill_to_cancel_ratio": _latest_ratio,
            "acute_cancels": float(_latest_acute_cancels),
        }


def get_status() -> Dict[str, Any]:
    """Retrieve complete guard status."""
    with _lock:
        now = time.monotonic()
        blocked = now < _blocked_until
        remaining = max(0.0, _blocked_until - now) if blocked else 0.0
        return {
            "guard_name": "wave247_fill_to_cancel_ratio_decay_guard",
            "is_blocked": blocked,
            "blocked_seconds_remaining": remaining,
            "event_count": len(_events_history),
            "fills_count": _latest_fills,
            "cancels_count": _latest_cancels,
            "fill_to_cancel_ratio": _latest_ratio,
            "acute_cancels": _latest_acute_cancels,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "min_cancels_threshold": MIN_CANCELS_THRESHOLD,
            "min_fill_cancel_ratio": MIN_FILL_CANCEL_RATIO,
            "acute_cancel_explosion": ACUTE_CANCEL_EXPLOSION,
        }


def reset() -> None:
    """Reset all guard state and clear cooldowns."""
    global _latest_fills, _latest_cancels, _latest_ratio, _latest_acute_cancels, _blocked_until

    with _lock:
        _events_history.clear()
        _latest_fills = 0
        _latest_cancels = 0
        _latest_ratio = 1.0
        _latest_acute_cancels = 0
        _blocked_until = 0.0
