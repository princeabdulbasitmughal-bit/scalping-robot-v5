"""
wave226_tick_flow_acceleration_skew_guard.py
----------------------------------------------
Guard: Tick Flow Asymmetry Acceleration & Directional Volatility Skew Guard

Monitors second-derivative acceleration in directional trade tick flow and higher-moment
flow asymmetry skew (Hasbrouck 1991; Easley, Lopez de Prado & O'Hara 2012):
    Tick Direction:        s_i in {+1 (buy), -1 (sell)}
    Window Net Flow:       Delta_k = sum_{j=1}^W s_{W(k-1) + j} over W = 10 ticks
    Flow Acceleration:     a_{flow} = Delta_k - Delta_{k-1}
    Directional Skewness:  S_{skew} = [ (1/N) * sum((s_i - bar{s})^3) ] / sigma_s^3
                           over rolling N = 20 ticks.

In steady, two-sided market liquidity:
    - Buyers and sellers alternate in balanced proportion: Delta_k ~ 0, a_{flow} ~ 0.
    - Directional flow skewness remains mild: |S_{skew}| < 1.0.

During aggressive momentum sweeps, algorithmic block unwinding, or liquidity cascade triggers:
    - Order flow experiences rapid jerk/acceleration from balanced to violently one-sided:
        1) Flow Asymmetry Jerk / Acceleration:
           |a_{flow}| >= MAX_FLOW_ACCELERATION (default: 12.0 units per 10-tick step).
           (e.g., from -6 net sell flow to +8 net buy flow represents a 14-unit acceleration).
        2) Directional Volatility Skew Explosion:
           |S_{skew}| >= MAX_FLOW_SKEW (default: 2.20) with N >= 20 ticks.

Posting passive liquidity or executing market scalping counter-orders into an accelerating
directional tick cascade results in instantaneous adverse selection and inventory blowout.

When excessive tick flow acceleration or skew explosion is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade direction via record_tick(side_or_direction, ts=None).
  Accepts strings ("buy", "sell", "b", "s", "1", "-1") or numeric (+1, -1).
- Maintains rolling history of tick directions (WINDOW_SIZE = 20).
- Computes 10-tick block imbalances Delta_k, flow acceleration a_{flow}, and directional skewness S_{skew}.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: invalid directions, booleans (other than valid numeric conversion), NaN, Inf are rejected.

Aliases (required):
  is_entry_blocked()                                                   -> bool
  is_blocked()                                                         -> bool   (alias)
  record_tick(direction_or_side, ts=None)                              -> None
  update(direction_or_side, ts=None)                                   -> None   (alias)
  get_flow_metrics()                                                   -> dict
  get_status()                                                         -> dict
  reset()                                                              -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any, Union

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BLOCK_SIZE: int = 10                      # 10 ticks per flow measurement block
WINDOW_SIZE: int = 20                     # 20 ticks for skewness evaluation
MAX_FLOW_ACCELERATION: float = 12.0       # 12.0 units acceleration per 10-tick block
MAX_FLOW_SKEW: float = 2.20               # 2.20 directional skewness threshold
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_ticks = collections.deque(maxlen=WINDOW_SIZE)
_prev_block_flow: Optional[int] = None
_latest_flow_accel: float = 0.0
_latest_flow_skew: float = 0.0
_blocked_until: float = 0.0


def _parse_direction(val: Any) -> Optional[int]:
    """Parse input side into +1 (buy) or -1 (sell). Returns None if invalid."""
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


def record_tick(
    direction_or_side: Union[str, int, float],
    ts: Optional[float] = None,
) -> None:
    """
    Ingest a new tick direction and evaluate flow acceleration and skewness.
    """
    global _prev_block_flow, _latest_flow_accel, _latest_flow_skew, _blocked_until

    sign = _parse_direction(direction_or_side)
    if sign is None:
        return

    with _lock:
        _ticks.append(sign)
        n = len(_ticks)

        # Evaluate 10-tick block acceleration (comparing recent 10 against previous 10)
        if n >= 2 * BLOCK_SIZE:
            prev_10 = list(_ticks)[-2 * BLOCK_SIZE : -BLOCK_SIZE]
            curr_10 = list(_ticks)[-BLOCK_SIZE :]
            accel = float(abs(sum(curr_10) - sum(prev_10)))
            _latest_flow_accel = accel
            if accel >= MAX_FLOW_ACCELERATION:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return

        # Evaluate Directional Skewness over full 20 ticks
        if n >= WINDOW_SIZE:
            mean_s = sum(_ticks) / float(n)
            var_s = sum((s - mean_s) ** 2 for s in _ticks) / float(n)
            std_s = math.sqrt(var_s)

            if std_s >= 0.1:
                skew = sum((s - mean_s) ** 3 for s in _ticks) / (float(n) * (std_s ** 3))
                _latest_flow_skew = skew
                if abs(skew) >= MAX_FLOW_SKEW:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                    return


def update(
    direction_or_side: Union[str, int, float],
    ts: Optional[float] = None,
) -> None:
    """Alias for record_tick()."""
    record_tick(direction_or_side, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to tick flow acceleration/skew."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_flow_metrics() -> Dict[str, float]:
    """Return latest calculated flow acceleration and skewness."""
    with _lock:
        return {
            "flow_acceleration": _latest_flow_accel,
            "flow_skewness": _latest_flow_skew,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the tick flow acceleration guard."""
    with _lock:
        now = time.monotonic()
        return {
            "flow_acceleration": _latest_flow_accel,
            "flow_skewness": _latest_flow_skew,
            "sample_count": len(_ticks),
            "window_size": WINDOW_SIZE,
            "block_size": BLOCK_SIZE,
            "max_flow_acceleration": MAX_FLOW_ACCELERATION,
            "max_flow_skew": MAX_FLOW_SKEW,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset tick deque, block trackers, metrics, and active cooldown blocks."""
    global _prev_block_flow, _latest_flow_accel, _latest_flow_skew, _blocked_until
    with _lock:
        _ticks.clear()
        _prev_block_flow = None
        _latest_flow_accel = 0.0
        _latest_flow_skew = 0.0
        _blocked_until = 0.0
