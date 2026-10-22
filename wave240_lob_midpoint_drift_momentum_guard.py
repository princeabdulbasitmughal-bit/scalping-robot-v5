"""
wave240_lob_midpoint_drift_momentum_guard.py
----------------------------------------------
Guard: Limit Order Book Midpoint Drift & Momentum Slip Guard

Monitors empirical midpoint price drift conditioned on aggressive trade order flow
(Cont, Kukanov & Stoikov 2014; Biais, Hillion & Spatt 1995; Hasbrouck 1991):
    Trade Direction:         s_t in {+1 (buy/lift ask), -1 (sell/hit bid)}
    Initial Midpoint:        P_{mid, 0} = (P_{bid, 0} + P_{ask, 0}) / 2
    Post-Trade Midpoint:     P_{mid, t+k}
    Signed Midpoint Drift:   Delta_{drift} = s_t * ((P_{mid, t+k} - P_{mid, 0}) / P_{mid, 0}) * 10^4 (bps)

In balanced, diffusive continuous double-auction markets with resilient liquidity provision:
    - Order flow impact decays quickly and midpoint returns revert toward zero:
      Mean Delta_{drift} <= 0.50 bps across rolling trade windows.
    - Market makers absorb flow without persistent directional drift.

During aggressive predatory book sweeps, directional iceberg liquidation, or informed order cascades:
    - The midpoint systematically drifts in the direction of the aggressive initiator:
        1) Sustained Adverse Midpoint Drift:
           Mean directional drift over rolling N=15 trades (minimum N >= 10):
           \\bar{Delta}_{drift} >= MAX_MEAN_DRIFT_BPS (default: 1.80 bps).
        2) Acute Midpoint Momentum Jump:
           Single trade post-trade midpoint drift Delta_{drift} >= MAX_ACUTE_DRIFT_BPS (default: 3.50 bps).

Posting passive limit orders or attempting to fade into an escalating midpoint drift
guarantees immediate adverse selection, book clearance, and steep negative post-fill slippage.

When sustained midpoint drift or acute momentum jump is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade drift via record_midpoint_drift(trade_side, initial_mid, post_mid, ts=None) or
  record_drift_bps(trade_side, drift_bps, ts=None).
- Maintains rolling history of WINDOW_SIZE = 15 trade drift observations.
- Minimum MIN_SAMPLES = 10 trades required for rolling window trip evaluation.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive prices, or invalid sides are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_midpoint_drift(trade_side, initial_mid, post_mid, ts=None)                            -> None
  record_drift_bps(trade_side, drift_bps, ts=None)                                             -> None
  update(trade_side, initial_mid, post_mid=None, ts=None)                                      -> None   (alias)
  get_drift_metrics()                                                                          -> dict
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
WINDOW_SIZE: int = 15
MIN_SAMPLES: int = 10
MAX_MEAN_DRIFT_BPS: float = 1.80       # Rolling mean directional drift >= 1.80 bps
MAX_ACUTE_DRIFT_BPS: float = 3.50      # Acute single-trade drift jump >= 3.50 bps
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_drift_history = collections.deque(maxlen=WINDOW_SIZE)  # signed drift in bps
_latest_drift_bps: float = 0.0
_latest_mean_drift_bps: float = 0.0
_blocked_until: float = 0.0


def _parse_side(val: Any) -> Optional[int]:
    """Parse trade side into +1 (buy) or -1 (sell). Returns None if invalid."""
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
        if s in ("buy", "b", "long", "+1", "1"):
            return 1
        elif s in ("sell", "s", "short", "-1"):
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


def _is_valid_numeric(val: Any) -> bool:
    """Validate value is a finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return True


def record_drift_bps(
    trade_side: Union[str, int, float],
    drift_bps: float,
    ts: Optional[float] = None,
) -> None:
    """
    Directly ingest signed midpoint drift in basis points.
    """
    global _latest_drift_bps, _latest_mean_drift_bps, _blocked_until

    side = _parse_side(trade_side)
    if side is None or not _is_valid_numeric(drift_bps):
        return

    # Signed drift: positive means drift aligned with trade direction (adverse to liquidity provider)
    s_drift = float(drift_bps)

    with _lock:
        _latest_drift_bps = s_drift
        _drift_history.append(s_drift)

        n = len(_drift_history)
        mean_drift = sum(_drift_history) / n
        _latest_mean_drift_bps = mean_drift

        # Condition 1: Acute midpoint momentum jump
        if s_drift >= MAX_ACUTE_DRIFT_BPS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 2: Sustained adverse midpoint drift
        if n >= MIN_SAMPLES and mean_drift >= MAX_MEAN_DRIFT_BPS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_midpoint_drift(
    trade_side: Union[str, int, float],
    initial_mid: float,
    post_mid: float,
    ts: Optional[float] = None,
) -> None:
    """
    Compute directional midpoint drift from initial and post-trade midpoints.
    """
    side = _parse_side(trade_side)
    if side is None:
        return
    if not _is_valid_positive(initial_mid) or not _is_valid_positive(post_mid):
        return

    m0 = float(initial_mid)
    m1 = float(post_mid)

    # Directional drift in bps: positive when price moves in direction of trade
    drift_bps = side * ((m1 - m0) / m0) * 10000.0
    record_drift_bps(side, drift_bps, ts)


def update(
    trade_side: Union[str, int, float],
    initial_mid: float,
    post_mid: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Flexible alias:
    If post_mid is provided, calculates drift from initial_mid and post_mid.
    If post_mid is None, treats initial_mid as drift_bps directly.
    """
    if post_mid is not None:
        record_midpoint_drift(trade_side, initial_mid, post_mid, ts)
    else:
        record_drift_bps(trade_side, initial_mid, ts)


def is_entry_blocked() -> bool:
    """Check if new entries are blocked by adverse midpoint drift."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_drift_metrics() -> Dict[str, float]:
    """Retrieve current midpoint drift metrics."""
    with _lock:
        return {
            "latest_drift_bps": _latest_drift_bps,
            "mean_drift_bps": _latest_mean_drift_bps,
        }


def get_status() -> Dict[str, Any]:
    """Retrieve complete guard status."""
    with _lock:
        now = time.monotonic()
        blocked = now < _blocked_until
        remaining = max(0.0, _blocked_until - now) if blocked else 0.0
        return {
            "guard_name": "wave240_lob_midpoint_drift_momentum_guard",
            "is_blocked": blocked,
            "blocked_seconds_remaining": remaining,
            "sample_count": len(_drift_history),
            "latest_drift_bps": _latest_drift_bps,
            "mean_drift_bps": _latest_mean_drift_bps,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "max_mean_drift_bps": MAX_MEAN_DRIFT_BPS,
            "max_acute_drift_bps": MAX_ACUTE_DRIFT_BPS,
        }


def reset() -> None:
    """Reset all guard state and clear cooldowns."""
    global _latest_drift_bps, _latest_mean_drift_bps, _blocked_until

    with _lock:
        _drift_history.clear()
        _latest_drift_bps = 0.0
        _latest_mean_drift_bps = 0.0
        _blocked_until = 0.0
