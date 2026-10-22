"""
wave217_fleeting_liquidity_quote_cancellation_guard.py
-------------------------------------------------------
Guard: Fleeting Liquidity & High-Frequency Quote Cancellation Velocity Guard

Monitors high-frequency "phantom liquidity" and rapid quote flashing/cancellations at the
top-of-book (Hasbrouck & Saar 2009; Cartea & Jaimungal 2014):
    Quote Lifespan:       dt_quote = t_{cancel} - t_{post} <= 150 ms (0.150s)
    Fleeting Ratio:       R_{fleeting} = C_{fleeting} / max(1, Total Quote Updates) in rolling 5.0s
    Fleeting Volume:      V_{fleeting} = sum of cancelled lots with lifespan <= 150 ms

In healthy market making environments:
    - Limit orders rest at top-of-book for seconds or minutes to genuinely provide liquidity.
    - Fleeting cancellation ratio R_{fleeting} < 0.20.

In manipulative, predatory, or toxic regimes:
    - High-frequency spoofing or quote-stuffing bots flash massive quotes and instantly pull them
      within tens of milliseconds to manipulate midquotes or probe queue position without execution risk.
    - Conditions triggering block:
        1) Elevated Fleeting Ratio:
           C_{fleeting} >= MIN_FLEETING_COUNT (default: 6) AND
           R_{fleeting} >= MAX_FLEETING_RATIO (default: 0.50 or 50% of updates) AND
           V_{fleeting} >= MIN_FLEETING_VOLUME (default: 10.0 lots) in rolling 5.0s.
        2) Sudden Burst Spoofing:
           Burst of >= 6 fleeting cancellations within <= 1.0s.

Scalpers attempting to cross the spread or join queues during fleeting liquidity spikes face
immediate phantom liquidity evaporation, adverse execution selection, and high slippage.

When excessive fleeting liquidity is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests quote updates via record_quote(bid_price, bid_depth, ask_price, ask_depth, ts=None)
  or explicit cancellations via record_cancellation(volume, lifespan_sec, ts=None).
- Inferred cancellation: depth drop at touch with dt <= 150ms.
- Tracks rolling events within WINDOW_SECONDS = 5.0s.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, negative depths, or inverted prices are rejected.

Aliases (required):
  is_entry_blocked()                                                 -> bool
  is_blocked()                                                       -> bool   (alias)
  record_quote(bid_price, bid_depth, ask_price, ask_depth, ts=None)  -> None
  record_cancellation(volume, lifespan_sec, ts=None)                -> None
  update(bid_price, bid_depth, ask_price, ask_depth, ts=None)        -> None   (alias)
  get_cancellation_metrics()                                         -> dict
  get_status()                                                       -> dict
  reset()                                                            -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
FLEETING_MAX_LIFESPAN_SEC: float = 0.150  # 150 ms threshold for fleeting liquidity
WINDOW_SECONDS: float = 5.0               # 5.0 seconds evaluation window
BURST_WINDOW_SEC: float = 1.0             # 1.0 second rapid burst window
MIN_FLEETING_COUNT: int = 6               # Minimum fleeting cancellations to trigger ratio check
MAX_FLEETING_RATIO: float = 0.50          # 50% fleeting cancellation ratio
MIN_FLEETING_VOLUME: float = 10.0         # 10.0 lots minimum cumulative fleeting volume
BURST_FLEETING_COUNT: int = 6             # 6 fleeting cancellations in <= 1.0s triggers burst block
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_bid_price: Optional[float] = None
_prev_bid_depth: float = 0.0
_prev_ask_price: Optional[float] = None
_prev_ask_depth: float = 0.0
_prev_quote_ts: Optional[float] = None

# History of (ts, is_fleeting, cancelled_volume)
_events = collections.deque()

_latest_fleeting_count: int = 0
_latest_fleeting_ratio: float = 0.0
_latest_fleeting_vol: float = 0.0
_blocked_until: float = 0.0


def _is_valid_price(val: Any) -> bool:
    """Validate price is a positive finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val > 0.0


def _is_valid_depth(val: Any) -> bool:
    """Validate depth is a non-negative finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val >= 0.0


def _prune_old_events(now: float) -> None:
    """Remove events older than WINDOW_SECONDS."""
    cutoff = now - WINDOW_SECONDS
    while _events and _events[0][0] < cutoff:
        _events.popleft()


def record_cancellation(
    volume: float,
    lifespan_sec: float,
    ts: Optional[float] = None,
) -> None:
    """
    Directly record a limit order cancellation event and evaluate fleeting liquidity metrics.
    """
    global _latest_fleeting_count, _latest_fleeting_ratio, _latest_fleeting_vol, _blocked_until

    if isinstance(volume, bool) or not isinstance(volume, (int, float)):
        return
    if isinstance(lifespan_sec, bool) or not isinstance(lifespan_sec, (int, float)):
        return
    if math.isnan(volume) or math.isinf(volume) or volume <= 0.0:
        return
    if math.isnan(lifespan_sec) or math.isinf(lifespan_sec) or lifespan_sec < 0.0:
        return

    vol = float(volume)
    life = float(lifespan_sec)
    is_fleeting = (life <= FLEETING_MAX_LIFESPAN_SEC)

    with _lock:
        now = time.monotonic() if ts is None else float(ts)
        _events.append((now, is_fleeting, vol if is_fleeting else 0.0))
        _prune_old_events(now)

        total_updates = len(_events)
        fleeting_count = sum(1 for e in _events if e[1])
        fleeting_vol = sum(e[2] for e in _events if e[1])
        ratio = fleeting_count / float(max(1, total_updates))

        _latest_fleeting_count = fleeting_count
        _latest_fleeting_ratio = ratio
        _latest_fleeting_vol = fleeting_vol

        # Check Burst Condition (last 1.0s)
        burst_cutoff = now - BURST_WINDOW_SEC
        burst_count = sum(1 for e in _events if e[0] >= burst_cutoff and e[1])
        if burst_count >= BURST_FLEETING_COUNT:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Check Ratio & Volume Condition (last 5.0s)
        if (
            fleeting_count >= MIN_FLEETING_COUNT
            and ratio >= MAX_FLEETING_RATIO
            and fleeting_vol >= MIN_FLEETING_VOLUME
        ):
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_quote(
    bid_price: float,
    bid_depth: float,
    ask_price: float,
    ask_depth: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest a top-of-book update and infer fleeting cancellations from rapid depth drops.
    """
    global _prev_bid_price, _prev_bid_depth, _prev_ask_price, _prev_ask_depth, _prev_quote_ts

    if not _is_valid_price(bid_price) or not _is_valid_price(ask_price):
        return
    if not _is_valid_depth(bid_depth) or not _is_valid_depth(ask_depth):
        return
    if float(ask_price) <= float(bid_price):
        return

    bp = float(bid_price)
    bq = float(bid_depth)
    ap = float(ask_price)
    aq = float(ask_depth)

    with _lock:
        now = time.monotonic() if ts is None else float(ts)

        if _prev_quote_ts is None:
            _prev_bid_price = bp
            _prev_bid_depth = bq
            _prev_ask_price = ap
            _prev_ask_depth = aq
            _prev_quote_ts = now
            _events.append((now, False, 0.0))
            return

        dt = max(1e-4, now - _prev_quote_ts)
        _prev_quote_ts = now

        # Infer cancellation if depth dropped significantly at identical price within fleeting window
        cancelled_vol = 0.0
        if dt <= FLEETING_MAX_LIFESPAN_SEC:
            if bp == _prev_bid_price and bq < _prev_bid_depth:
                cancelled_vol += (_prev_bid_depth - bq)
            if ap == _prev_ask_price and aq < _prev_ask_depth:
                cancelled_vol += (_prev_ask_depth - aq)

        is_fleeting = (cancelled_vol > 0.1)

        _prev_bid_price = bp
        _prev_bid_depth = bq
        _prev_ask_price = ap
        _prev_ask_depth = aq

        _events.append((now, is_fleeting, cancelled_vol))
        _prune_old_events(now)

        total_updates = len(_events)
        fleeting_count = sum(1 for e in _events if e[1])
        fleeting_vol = sum(e[2] for e in _events if e[1])
        ratio = fleeting_count / float(max(1, total_updates))

        global _latest_fleeting_count, _latest_fleeting_ratio, _latest_fleeting_vol, _blocked_until
        _latest_fleeting_count = fleeting_count
        _latest_fleeting_ratio = ratio
        _latest_fleeting_vol = fleeting_vol

        # Check Burst Condition (last 1.0s)
        burst_cutoff = now - BURST_WINDOW_SEC
        burst_count = sum(1 for e in _events if e[0] >= burst_cutoff and e[1])
        if burst_count >= BURST_FLEETING_COUNT:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Check Ratio & Volume Condition (last 5.0s)
        if (
            fleeting_count >= MIN_FLEETING_COUNT
            and ratio >= MAX_FLEETING_RATIO
            and fleeting_vol >= MIN_FLEETING_VOLUME
        ):
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(
    bid_price: float,
    bid_depth: float,
    ask_price: float,
    ask_depth: float,
    ts: Optional[float] = None,
) -> None:
    """Alias for record_quote()."""
    record_quote(bid_price, bid_depth, ask_price, ask_depth, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to fleeting liquidity."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_cancellation_metrics() -> Dict[str, float]:
    """Return latest calculated fleeting count, ratio, and volume."""
    with _lock:
        return {
            "fleeting_count": float(_latest_fleeting_count),
            "fleeting_ratio": _latest_fleeting_ratio,
            "fleeting_volume": _latest_fleeting_vol,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the fleeting liquidity guard."""
    with _lock:
        now = time.monotonic()
        return {
            "fleeting_count": _latest_fleeting_count,
            "fleeting_ratio": _latest_fleeting_ratio,
            "fleeting_volume": _latest_fleeting_vol,
            "event_count": len(_events),
            "window_seconds": WINDOW_SECONDS,
            "min_fleeting_count": MIN_FLEETING_COUNT,
            "max_fleeting_ratio": MAX_FLEETING_RATIO,
            "min_fleeting_volume": MIN_FLEETING_VOLUME,
            "burst_fleeting_count": BURST_FLEETING_COUNT,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset quote history, event deque, metrics, and active cooldown blocks."""
    global _prev_bid_price, _prev_bid_depth, _prev_ask_price, _prev_ask_depth, _prev_quote_ts
    global _latest_fleeting_count, _latest_fleeting_ratio, _latest_fleeting_vol, _blocked_until
    with _lock:
        _prev_bid_price = None
        _prev_bid_depth = 0.0
        _prev_ask_price = None
        _prev_ask_depth = 0.0
        _prev_quote_ts = None
        _events.clear()
        _latest_fleeting_count = 0
        _latest_fleeting_ratio = 0.0
        _latest_fleeting_vol = 0.0
        _blocked_until = 0.0
