"""
wave253_lob_cancellation_asymmetry_velocity_guard.py
------------------------------------------------------
Guard: Limit Order Queue Cancellation Asymmetry Velocity Guard

Monitors differential limit order cancellation rates between bid and ask sides and
second-derivative cancellation asymmetry acceleration (Cartea, Jaimungal & Ricci 2014; Lehalle 2017):
    Bid Cancellation Rate:     C_{bid} (cancels / sec)
    Ask Cancellation Rate:     C_{ask} (cancels / sec)
    Net Cancellation Rate:     \\Delta C_{net} = C_{bid} - C_{ask}
    Cancellation Ratio:        R_C = max(C_{bid}, C_{ask}) / max(1.0, min(C_{bid}, C_{ask}))
    Asymmetry Velocity Surge:  v_{\\Delta C} = (\\Delta C_{net, t} - \\Delta C_{net, t-1}) / max(0.1, \\Delta t)

In balanced continuous double-auction market conditions:
    - Order cancellations occur symmetrically across both sides of the book:
      |\\Delta C_{net}| <= 5.0 cancels/sec, with R_C < 2.5x.

During predatory spoofing, one-sided quote evaporation, or targeted quote pulling:
    - High-frequency algorithms aggressively cancel liquidity on one side while holding or baiting the other:
        1) Extreme Directional Cancellation Asymmetry:
           |\\Delta C_{net}| >= MAX_NET_CANCEL_RATE (default: 15.0 cancels/sec) AND
           R_C >= MAX_CANCEL_RATIO (default: 6.0x).
        2) Acute Cancellation Asymmetry Acceleration Surge:
           |v_{\\Delta C}| >= MAX_ASYM_ACCELERATION (default: 12.0 cancels/sec^2).

Fading or submitting counter-orders into asymmetric cancellation avalanches results in
immediate quote evaporation, front-running sweeps, and severe execution drag.

When directional cancellation asymmetry or asymmetry velocity surge is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests cancellation rates via record_cancellations(bid_cancels, ask_cancels, ts=None) or
  single events via record_single_cancellation(side, count=1.0, ts=None).
- Evaluates net difference \\Delta C_{net}, ratio R_C, and asymmetry acceleration v_{\\Delta C}.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative rates are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_cancellations(bid_cancels, ask_cancels, ts=None)                                      -> None
  record_single_cancellation(side, count=1.0, ts=None)                                         -> None
  update(bid_cancels, ask_cancels=None, ts=None)                                               -> None   (alias)
  get_cancellation_asymmetry_metrics()                                                         -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import math
import threading
import time
from typing import Dict, Optional, Any, Union

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_NET_CANCEL_RATE: float = 15.0      # 15.0 cancels/sec net cancellation differential
MAX_CANCEL_RATIO: float = 6.0          # 6.0x cancellation ratio
MAX_ASYM_ACCELERATION: float = 12.0    # 12.0 cancels/sec^2 asymmetry velocity surge
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_latest_bid_cancels: float = 5.0
_latest_ask_cancels: float = 5.0
_latest_net_diff: float = 0.0
_latest_ratio: float = 1.0
_latest_velocity: float = 0.0
_prev_net_diff: float = 0.0
_prev_ts: Optional[float] = None
_blocked_until: float = 0.0


def _parse_side(val: Any) -> Optional[int]:
    """Parse side into +1 (bid) or -1 (ask). Returns None if invalid."""
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


def _is_valid_non_negative(val: Any) -> bool:
    """Validate value is a non-negative finite numeric float or int."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val >= 0.0


def record_cancellations(
    bid_cancels: float,
    ask_cancels: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest bid and ask cancellation rates and evaluate asymmetry and velocity surge.
    """
    global _latest_bid_cancels, _latest_ask_cancels, _latest_net_diff
    global _latest_ratio, _latest_velocity, _prev_net_diff, _prev_ts, _blocked_until

    if not _is_valid_non_negative(bid_cancels) or not _is_valid_non_negative(ask_cancels):
        return

    bc = float(bid_cancels)
    ac = float(ask_cancels)
    now = float(ts) if ts is not None else time.time()

    with _lock:
        diff = bc - ac
        ratio = max(bc, ac) / max(1.0, min(bc, ac))

        if _prev_ts is not None:
            dt = max(0.1, now - _prev_ts)
            velocity = (diff - _prev_net_diff) / dt
        else:
            velocity = 0.0

        _latest_bid_cancels = bc
        _latest_ask_cancels = ac
        _latest_net_diff = diff
        _latest_ratio = ratio
        _latest_velocity = velocity
        _prev_net_diff = diff
        _prev_ts = now

        # Condition 1: Acute cancellation asymmetry acceleration surge
        if abs(velocity) >= MAX_ASYM_ACCELERATION:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 2: Extreme directional cancellation asymmetry
        if abs(diff) >= MAX_NET_CANCEL_RATE and ratio >= MAX_CANCEL_RATIO:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_single_cancellation(
    side: Union[str, int, float],
    count: float = 1.0,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest cancellation count for a single side and update rates.
    """
    s = _parse_side(side)
    if s is None or not _is_valid_non_negative(count):
        return

    cnt = float(count)
    with _lock:
        if s == 1:
            record_cancellations(_latest_bid_cancels + cnt, _latest_ask_cancels, ts)
        else:
            record_cancellations(_latest_bid_cancels, _latest_ask_cancels + cnt, ts)


def update(
    bid_cancels: float,
    ask_cancels: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Flexible alias:
    If ask_cancels is provided, records bilateral rates.
    If ask_cancels is None, records bid cancellation (side=1).
    """
    if ask_cancels is not None:
        record_cancellations(bid_cancels, ask_cancels, ts)
    else:
        record_single_cancellation(1, bid_cancels, ts)


def is_entry_blocked() -> bool:
    """Check if new entries are blocked by cancellation asymmetry."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_cancellation_asymmetry_metrics() -> Dict[str, float]:
    """Retrieve current cancellation asymmetry metrics."""
    with _lock:
        return {
            "bid_cancels": _latest_bid_cancels,
            "ask_cancels": _latest_ask_cancels,
            "net_difference": _latest_net_diff,
            "asymmetry_ratio": _latest_ratio,
            "asymmetry_velocity": _latest_velocity,
        }


def get_status() -> Dict[str, Any]:
    """Retrieve complete guard status."""
    with _lock:
        now = time.monotonic()
        blocked = now < _blocked_until
        remaining = max(0.0, _blocked_until - now) if blocked else 0.0
        return {
            "guard_name": "wave253_lob_cancellation_asymmetry_velocity_guard",
            "is_blocked": blocked,
            "blocked_seconds_remaining": remaining,
            "bid_cancels": _latest_bid_cancels,
            "ask_cancels": _latest_ask_cancels,
            "net_difference": _latest_net_diff,
            "asymmetry_ratio": _latest_ratio,
            "asymmetry_velocity": _latest_velocity,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "max_net_cancel_rate": MAX_NET_CANCEL_RATE,
            "max_cancel_ratio": MAX_CANCEL_RATIO,
            "max_asym_acceleration": MAX_ASYM_ACCELERATION,
        }


def reset() -> None:
    """Reset all guard state and clear cooldowns."""
    global _latest_bid_cancels, _latest_ask_cancels, _latest_net_diff
    global _latest_ratio, _latest_velocity, _prev_net_diff, _prev_ts, _blocked_until

    with _lock:
        _latest_bid_cancels = 5.0
        _latest_ask_cancels = 5.0
        _latest_net_diff = 0.0
        _latest_ratio = 1.0
        _latest_velocity = 0.0
        _prev_net_diff = 0.0
        _prev_ts = None
        _blocked_until = 0.0
