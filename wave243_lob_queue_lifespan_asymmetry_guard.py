"""
wave243_lob_queue_lifespan_asymmetry_guard.py
-----------------------------------------------
Guard: Limit Order Queue Lifespan Asymmetry & Predatory Churn Guard

Monitors asymmetric resting lifespan of canceled limit orders between bid and ask sides
(Cartea & Jaimungal 2014; Lehalle & Mounjid 2017; Moallemi & Saglam 2013):
    Bid Mean Lifespan:       \\bar{\\tau}_{bid} = mean resting lifetime of canceled bid limit orders (ms)
    Ask Mean Lifespan:       \\bar{\\tau}_{ask} = mean resting lifetime of canceled ask limit orders (ms)
    Lifespan Asymmetry:      R_{\\tau} = max(\\bar{\\tau}_{bid}, \\bar{\\tau}_{ask}) / max(10.0, min(\\bar{\\tau}_{bid}, \\bar{\\tau}_{ask}))

In balanced, symmetric continuous double-auction liquidity provision:
    - Limit orders on both sides exhibit comparable resting lifetimes:
      \\bar{\\tau}_{bid} ~ \\bar{\\tau}_{ask} >= 500 ms, with R_{\\tau} < 3.0x.

During aggressive quote stuffing, spoofing, phantom liquidity pulsing, or directional queue harassment:
    - One side of the book suffers hyper-rapid cancellation churn while the other side is passive:
        1) Severe Queue Lifespan Asymmetry:
           R_{\\tau} >= MAX_LIFESPAN_ASYMMETRY (default: 8.0x) AND
           min(\\bar{\\tau}_{bid}, \\bar{\\tau}_{ask}) <= MIN_FLEETING_LIFESPAN_MS (default: 120.0 ms)
           over rolling N >= 10 samples per side.
        2) Bilateral Flash Churn / HFT Quote War:
           Both \\bar{\\tau}_{bid} <= BILATERAL_FLASH_CHURN_MS (default: 60.0 ms) AND
           \\bar{\\tau}_{ask} <= BILATERAL_FLASH_CHURN_MS (60.0 ms) with N >= 10 per side.

Posting limit orders or taking liquidity during severe queue lifespan asymmetry guarantees
immediate phantom fill failure, spoof whipsaw, and predatory front-running.

When queue lifespan asymmetry or bilateral flash churn is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests order lifespans via record_order_cancellation(side, lifespan_ms, ts=None) or
  bilateral means via record_quote_lifespans(bid_lifespan_ms, ask_lifespan_ms, ts=None).
- Maintains rolling history of WINDOW_SIZE = 20 cancellation lifespans per side.
- Evaluates R_{\\tau}, min lifespan, and bilateral flash churn.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive lifespans, or invalid sides are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_order_cancellation(side, lifespan_ms, ts=None)                                       -> None
  record_quote_lifespans(bid_lifespan_ms, ask_lifespan_ms, ts=None)                            -> None
  update(bid_lifespan_ms, ask_lifespan_ms=None, ts=None)                                       -> None   (alias)
  get_lifespan_metrics()                                                                       -> dict
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
WINDOW_SIZE: int = 20
MIN_SAMPLES: int = 10
MAX_LIFESPAN_ASYMMETRY: float = 8.0            # 8.0x lifespan asymmetry ratio
MIN_FLEETING_LIFESPAN_MS: float = 120.0        # 120.0 ms fleeting side ceiling
BILATERAL_FLASH_CHURN_MS: float = 60.0         # 60.0 ms bilateral flash churn
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_bid_lifespans = collections.deque(maxlen=WINDOW_SIZE)
_ask_lifespans = collections.deque(maxlen=WINDOW_SIZE)
_latest_mean_bid_ms: float = 500.0
_latest_mean_ask_ms: float = 500.0
_latest_asymmetry_ratio: float = 1.0
_blocked_until: float = 0.0


def _parse_side(val: Any) -> Optional[int]:
    """Parse side into +1 (bid/buy) or -1 (ask/sell). Returns None if invalid."""
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        if math.isnan(val) or math.isinf(val):
            return None
        if val > 0:
            return 1
        elif val < 0:
            return -1
        return None
    if isinstance(val, str):
        s = val.strip().lower()
        if s in ("bid", "b", "buy", "long", "+1", "1"):
            return 1
        elif s in ("ask", "a", "sell", "short", "-1"):
            return -1
    return None


def _is_valid_positive(val: Any) -> bool:
    """Validate value is a positive finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val > 0.0


def record_order_cancellation(
    side: Union[str, int, float],
    lifespan_ms: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest a single limit order cancellation lifespan for bid or ask.
    """
    global _latest_mean_bid_ms, _latest_mean_ask_ms, _latest_asymmetry_ratio, _blocked_until

    s = _parse_side(side)
    if s is None or not _is_valid_positive(lifespan_ms):
        return

    life = float(lifespan_ms)

    with _lock:
        if s == 1:
            _bid_lifespans.append(life)
        else:
            _ask_lifespans.append(life)

        n_bid = len(_bid_lifespans)
        n_ask = len(_ask_lifespans)

        if n_bid > 0:
            _latest_mean_bid_ms = sum(_bid_lifespans) / n_bid
        if n_ask > 0:
            _latest_mean_ask_ms = sum(_ask_lifespans) / n_ask

        # Evaluate trips when both sides have sufficient samples
        if n_bid >= MIN_SAMPLES and n_ask >= MIN_SAMPLES:
            max_life = max(_latest_mean_bid_ms, _latest_mean_ask_ms)
            min_life = min(_latest_mean_bid_ms, _latest_mean_ask_ms)
            asym = max_life / max(10.0, min_life)
            _latest_asymmetry_ratio = asym

            # Condition 1: Bilateral flash churn
            if (
                _latest_mean_bid_ms <= BILATERAL_FLASH_CHURN_MS
                and _latest_mean_ask_ms <= BILATERAL_FLASH_CHURN_MS
            ):
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return

            # Condition 2: Severe queue lifespan asymmetry
            if asym >= MAX_LIFESPAN_ASYMMETRY and min_life <= MIN_FLEETING_LIFESPAN_MS:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return


def record_quote_lifespans(
    bid_lifespan_ms: float,
    ask_lifespan_ms: float,
    ts: Optional[float] = None,
) -> None:
    """
    Record paired bid and ask limit order resting lifespans.
    """
    if not _is_valid_positive(bid_lifespan_ms) or not _is_valid_positive(ask_lifespan_ms):
        return

    record_order_cancellation(1, bid_lifespan_ms, ts)
    record_order_cancellation(-1, ask_lifespan_ms, ts)


def update(
    bid_lifespan_ms: float,
    ask_lifespan_ms: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Flexible alias:
    If ask_lifespan_ms is provided, records paired quote lifespans.
    If ask_lifespan_ms is None, treats bid_lifespan_ms as bid order cancellation (side=1).
    """
    if ask_lifespan_ms is not None:
        record_quote_lifespans(bid_lifespan_ms, ask_lifespan_ms, ts)
    else:
        record_order_cancellation(1, bid_lifespan_ms, ts)


def is_entry_blocked() -> bool:
    """Check if new entries are blocked by queue lifespan asymmetry."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_lifespan_metrics() -> Dict[str, float]:
    """Retrieve current queue lifespan metrics."""
    with _lock:
        return {
            "mean_bid_lifespan_ms": _latest_mean_bid_ms,
            "mean_ask_lifespan_ms": _latest_mean_ask_ms,
            "asymmetry_ratio": _latest_asymmetry_ratio,
        }


def get_status() -> Dict[str, Any]:
    """Retrieve complete guard status."""
    with _lock:
        now = time.monotonic()
        blocked = now < _blocked_until
        remaining = max(0.0, _blocked_until - now) if blocked else 0.0
        return {
            "guard_name": "wave243_lob_queue_lifespan_asymmetry_guard",
            "is_blocked": blocked,
            "blocked_seconds_remaining": remaining,
            "bid_sample_count": len(_bid_lifespans),
            "ask_sample_count": len(_ask_lifespans),
            "mean_bid_lifespan_ms": _latest_mean_bid_ms,
            "mean_ask_lifespan_ms": _latest_mean_ask_ms,
            "asymmetry_ratio": _latest_asymmetry_ratio,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "max_lifespan_asymmetry": MAX_LIFESPAN_ASYMMETRY,
            "min_fleeting_lifespan_ms": MIN_FLEETING_LIFESPAN_MS,
            "bilateral_flash_churn_ms": BILATERAL_FLASH_CHURN_MS,
        }


def reset() -> None:
    """Reset all guard state and clear cooldowns."""
    global _latest_mean_bid_ms, _latest_mean_ask_ms, _latest_asymmetry_ratio, _blocked_until

    with _lock:
        _bid_lifespans.clear()
        _ask_lifespans.clear()
        _latest_mean_bid_ms = 500.0
        _latest_mean_ask_ms = 500.0
        _latest_asymmetry_ratio = 1.0
        _blocked_until = 0.0
