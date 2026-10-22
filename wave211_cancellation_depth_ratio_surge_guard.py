"""
wave211_cancellation_depth_ratio_surge_guard.py
------------------------------------------------
Guard: Quote Cancellation-to-Depth Ratio (CDR) & Phantom Liquidity Guard

Monitors rapid top-of-book order cancellations relative to standing queue depth over a rolling
2.0-second window:
    C_{window} = sum_{t_i in [now - 2.0, now]} Cancel_Volume_i
    Q_{depth}  = (Bid_Depth + Ask_Depth) / 2
    CDR        = C_{window} / max(1.0, Q_{depth})

In natural trading environments where market makers actively provide bona fide liquidity:
    CDR <= 1.0 (cancellations do not exceed standing resting depth).

During manipulative algorithmic regimes—such as high-frequency quote stuffing, phantom liquidity
posting, or rapid quote pulling right before an aggressive execution:
    CDR >= MAX_CDR (default: 3.0x standing depth within 2.0s)
    with total cancelled volume C_{window} >= MIN_CANCEL_VOLUME (default: 15.0 lots).

This extreme cancellation flurry indicates illusory "ghost liquidity" that evaporates instantaneously
when aggressive market orders arrive, subjecting scalpers to deep through-the-book slippage.

When CDR breaches the safety threshold, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests cancellations or book depth updates (bid_price, bid_depth, ask_price, ask_depth, ts=None)
  or explicit cancellations via record_cancellation(cancel_volume, standing_depth, ts=None).
- Detects depth drops at identical prices as cancellations.
- Maintains rolling 2.0-second window of cancellation events.
- Evaluates CDR = C_{window} / max(1.0, Q_{depth}).
- Blocks entries for COOLDOWN_SECONDS (45.0s) if CDR >= 3.0 and C_{window} >= 15.0 lots.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative volumes/depths are rejected.

Aliases (required):
  is_entry_blocked()                                                             -> bool
  is_blocked()                                                                   -> bool   (alias)
  record_cancellation(cancel_volume, standing_depth, ts=None)                    -> None
  record_depth(bid_price, bid_depth, ask_price, ask_depth, ts=None)              -> None
  update(cancel_volume, standing_depth, ts=None)                                 -> None   (alias)
  get_cdr_metrics()                                                              -> dict
  get_status()                                                                   -> dict
  reset()                                                                        -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SECONDS: float = 2.0
MAX_CDR: float = 3.0                   # cancellations >= 3.0x standing depth
MIN_CANCEL_VOLUME: float = 15.0        # 15.0 lots minimum cancellation in window
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_bp: Optional[float] = None
_prev_bq: Optional[float] = None
_prev_ap: Optional[float] = None
_prev_aq: Optional[float] = None
_cancellations = collections.deque()  # (timestamp, volume)
_latest_standing_depth: float = 10.0
_latest_cdr: float = 0.0
_latest_window_cancels: float = 0.0
_blocked_until: float = 0.0


def _is_valid_positive_number(val: Any) -> bool:
    """Validate positive finite float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val > 0.0


def _is_valid_non_negative_number(val: Any) -> bool:
    """Validate non-negative finite float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val >= 0.0


def record_cancellation(
    cancel_volume: float,
    standing_depth: float,
    ts: Optional[float] = None,
) -> None:
    """
    Directly ingest a cancellation event with prevailing standing depth.
    """
    global _latest_standing_depth, _latest_cdr, _latest_window_cancels, _blocked_until

    if not _is_valid_positive_number(cancel_volume) or not _is_valid_non_negative_number(standing_depth):
        return

    cv = float(cancel_volume)
    sd = float(standing_depth)

    with _lock:
        now = time.monotonic() if ts is None else float(ts)
        _latest_standing_depth = max(1.0, sd)
        _cancellations.append((now, cv))

        # Evict cancellations older than WINDOW_SECONDS
        cutoff = now - WINDOW_SECONDS
        while _cancellations and _cancellations[0][0] < cutoff:
            _cancellations.popleft()

        total_cancels = sum(vol for _, vol in _cancellations)
        _latest_window_cancels = total_cancels
        cdr = total_cancels / _latest_standing_depth
        _latest_cdr = cdr

        # Check Condition: Extreme Cancellation-to-Depth Ratio Surge
        if cdr >= MAX_CDR and total_cancels >= MIN_CANCEL_VOLUME:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_depth(
    bid_price: float,
    bid_depth: float,
    ask_price: float,
    ask_depth: float,
    ts: Optional[float] = None,
) -> None:
    """
    Infer cancellations from book depth drops at identical prices.
    """
    global _prev_bp, _prev_bq, _prev_ap, _prev_aq

    if not _is_valid_positive_number(bid_price) or not _is_valid_positive_number(ask_price):
        return
    if not _is_valid_non_negative_number(bid_depth) or not _is_valid_non_negative_number(ask_depth):
        return
    if float(ask_price) <= float(bid_price):
        return

    bp = float(bid_price)
    bq = float(bid_depth)
    ap = float(ask_price)
    aq = float(ask_depth)

    with _lock:
        now = time.monotonic() if ts is None else float(ts)

        if _prev_bp is not None and _prev_bq is not None:
            # Check bid cancellation at identical price
            if bp == _prev_bp and bq < _prev_bq:
                cancel = _prev_bq - bq
                standing = (bq + aq) / 2.0
                record_cancellation(cancel, standing, now)

        if _prev_ap is not None and _prev_aq is not None:
            # Check ask cancellation at identical price
            if ap == _prev_ap and aq < _prev_aq:
                cancel = _prev_aq - aq
                standing = (bq + aq) / 2.0
                record_cancellation(cancel, standing, now)

        _prev_bp = bp
        _prev_bq = bq
        _prev_ap = ap
        _prev_aq = aq


def update(
    cancel_volume: float,
    standing_depth: float,
    ts: Optional[float] = None,
) -> None:
    """Alias for record_cancellation()."""
    record_cancellation(cancel_volume, standing_depth, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to cancellation surge."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_cdr_metrics() -> Dict[str, float]:
    """Return latest cancellation metrics."""
    with _lock:
        return {
            "cdr": _latest_cdr,
            "window_cancellations": _latest_window_cancels,
            "standing_depth": _latest_standing_depth,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the cancellation surge guard."""
    with _lock:
        now = time.monotonic()
        return {
            "cdr": _latest_cdr,
            "window_cancellations": _latest_window_cancels,
            "standing_depth": _latest_standing_depth,
            "max_cdr_threshold": MAX_CDR,
            "min_cancel_volume": MIN_CANCEL_VOLUME,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset cancellation history, book trackers, and active cooldown blocks."""
    global _prev_bp, _prev_bq, _prev_ap, _prev_aq
    global _latest_standing_depth, _latest_cdr, _latest_window_cancels, _blocked_until
    with _lock:
        _prev_bp = None
        _prev_bq = None
        _prev_ap = None
        _prev_aq = None
        _cancellations.clear()
        _latest_standing_depth = 10.0
        _latest_cdr = 0.0
        _latest_window_cancels = 0.0
        _blocked_until = 0.0
