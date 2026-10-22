"""
wave208_high_frequency_quote_staleness_jump_guard.py
-----------------------------------------------------
Guard: Feed Staleness Age & Post-Staleness Gap Jump Guard

Monitors silent feed freezing and jump discontinuities upon quote resumption:
    Staleness: dt = t_current - t_previous >= MAX_STALENESS_SEC (default: 2.5s)
    Jump:      Gap_{bps} = |P_{mid, t} - P_{mid, t-1}| / P_{mid, t-1} * 10,000

In active liquid trading sessions, top-of-book quotes arrive continuously:
    dt < 0.50 seconds and quote changes are smooth (< 1.0 bp).

When a market data feed or bridge connection silently freezes for >= 2.5s and then unfreezes
with an abrupt price jump (Gap_{bps} >= MIN_GAP_JUMP_BPS = 3.0 bps):
    1) The price jump reflects latent information that occurred while local clients were blind.
    2) The bridge order queue is congested with delayed execution requests.
    3) Submitting orders immediately after an unfreeze results in severe execution re-quotes
       or fills at stale, adverse off-market levels.

When a post-staleness price jump is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests quotes (bid > 0.0, ask > bid, ts=None).
- Calculates elapsed time dt from previous quote.
- If dt >= MAX_STALENESS_SEC (2.5s), flags a feed staleness condition.
- If staleness occurred and the price jump >= MIN_GAP_JUMP_BPS (3.0 bps), blocks entries for 45s.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive prices, or inverted quotes are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_quote(bid, ask, ts=None)                          -> None
  update(bid, ask, ts=None)                                -> None   (alias)
  get_staleness_metrics()                                  -> dict
  get_status()                                             -> dict
  reset()                                                  -> None
"""

import math
import threading
import time
from typing import Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_STALENESS_SEC: float = 2.5         # 2.5s silent gap indicates frozen feed
MIN_GAP_JUMP_BPS: float = 3.0          # 3.0 bps price jump upon resumption triggers trip
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_mid: Optional[float] = None
_prev_ts: Optional[float] = None
_latest_dt: float = 0.0
_latest_gap_bps: float = 0.0
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


def record_quote(bid: float, ask: float, ts: Optional[float] = None) -> None:
    """
    Ingest a new quote update and detect post-staleness price jumps.
    """
    global _prev_mid, _prev_ts, _latest_dt, _latest_gap_bps, _blocked_until

    if not _is_valid_price(bid) or not _is_valid_price(ask):
        return
    if float(ask) <= float(bid):
        return

    mid = (float(bid) + float(ask)) / 2.0

    with _lock:
        now = time.monotonic() if ts is None else float(ts)

        if _prev_mid is None or _prev_ts is None:
            _prev_mid = mid
            _prev_ts = now
            return

        dt = now - _prev_ts
        gap_bps = (abs(mid - _prev_mid) / _prev_mid) * 10_000.0

        _latest_dt = dt
        _latest_gap_bps = gap_bps

        # Check Condition: Stale feed freeze followed by abrupt price jump
        if dt >= MAX_STALENESS_SEC and gap_bps >= MIN_GAP_JUMP_BPS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            _prev_mid = mid
            _prev_ts = now
            return

        _prev_mid = mid
        _prev_ts = now


def update(bid: float, ask: float, ts: Optional[float] = None) -> None:
    """Alias for record_quote()."""
    record_quote(bid, ask, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to feed staleness jump."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_staleness_metrics() -> Dict[str, float]:
    """Return latest measured update interval and price gap."""
    with _lock:
        return {
            "dt_sec": _latest_dt,
            "gap_bps": _latest_gap_bps,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the feed staleness guard."""
    with _lock:
        now = time.monotonic()
        return {
            "dt_sec": _latest_dt,
            "gap_bps": _latest_gap_bps,
            "max_staleness_sec": MAX_STALENESS_SEC,
            "min_gap_jump_bps": MIN_GAP_JUMP_BPS,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset quote history, staleness metrics, and active cooldown blocks."""
    global _prev_mid, _prev_ts, _latest_dt, _latest_gap_bps, _blocked_until
    with _lock:
        _prev_mid = None
        _prev_ts = None
        _latest_dt = 0.0
        _latest_gap_bps = 0.0
        _blocked_until = 0.0
