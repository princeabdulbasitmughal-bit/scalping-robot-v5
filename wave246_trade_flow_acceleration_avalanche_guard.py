"""
wave246_trade_flow_acceleration_avalanche_guard.py
----------------------------------------------------
Guard: Trade Flow Acceleration & Volume Clustered Avalanche Guard

Monitors second-derivative acceleration in trade arrival rate and acute clustered volume avalanches
(Engle & Russell 1998; Hasbrouck 1991; Easley et al. 2012):
    Current Trade Arrival Rate:  \\lambda_{curr} = trade count in [t - 1.0s, t] (trades / sec)
    Previous Trade Arrival Rate: \\lambda_{prev} = trade count in [t - 2.0s, t - 1.0s) (trades / sec)
    Trade Flow Acceleration:     a_{trade} = \\lambda_{curr} - \\lambda_{prev} (trades / sec^2)
    Rolling Cluster Volume:      V_{cluster} = total volume traded in [t - 1.0s, t] (lots)
    Acute Sub-Second Volume:     V_{acute} = total volume traded in [t - 0.3s, t] (lots)

In ordinary diffusive continuous double-auction markets:
    - Trades arrive at orderly frequencies with mild volume dispersion:
      \\lambda_{curr} ~ 2 - 8 trades/sec, a_{trade} < 6.0 trades/sec^2, V_{cluster} < 8.0 lots.

During violent institutional liquidation sweeps, cascading algorithmic stop runs, or momentum bursts:
    - High-frequency algorithms aggressively accelerate trade execution speed and volume concentration:
        1) Trade Flow Acceleration Surge:
           a_{trade} >= MAX_TRADE_ACCELERATION (default: 12.0 trades/sec^2) AND
           \\lambda_{curr} >= MIN_CURRENT_RATE (default: 18.0 trades/sec).
        2) Clustered Volume Avalanche:
           V_{cluster} >= MAX_CLUSTER_VOLUME (default: 20.0 lots in <= 1.0s) OR
           V_{acute} >= MAX_ACUTE_VOLUME (default: 12.0 lots in <= 0.3s).

Taking or posting counter-trend liquidity during volume-clustered avalanches guarantees
immediate queue wipeout, massive adverse fill selection, and severe execution slippage.

When trade flow acceleration surge or clustered volume avalanche is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trades via record_trade(volume_lots=1.0, ts=None) or
  direct rate feeds via record_trade_rate(trades_per_sec, prev_trades_per_sec=None, volume_rate=None, ts=None).
- Maintains sliding trade history window of 5.0 seconds.
- Evaluates a_{trade}, \\lambda_{curr}, V_{cluster}, and V_{acute}.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive volumes/rates are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade(volume_lots=1.0, ts=None)                                                       -> None
  record_trade_rate(trades_per_sec, prev_trades_per_sec=None, volume_rate=None, ts=None)       -> None
  update(volume_lots=1.0, ts=None)                                                             -> None   (alias)
  get_avalanche_metrics()                                                                      -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_TRADE_ACCELERATION: float = 12.0       # 12.0 trades/sec^2 acceleration surge
MIN_CURRENT_RATE: float = 18.0             # 18.0 trades/sec threshold for acceleration
MAX_CLUSTER_VOLUME: float = 20.0           # 20.0 lots in <= 1.0s window
MAX_ACUTE_VOLUME: float = 12.0             # 12.0 lots in <= 0.3s acute burst
COOLDOWN_SECONDS: float = 45.0
HISTORY_WINDOW_SECONDS: float = 5.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_trade_events: collections.deque = collections.deque()  # elements: (timestamp, volume)
_latest_rate_curr: float = 0.0
_latest_rate_prev: float = 0.0
_latest_acceleration: float = 0.0
_latest_cluster_volume: float = 0.0
_latest_acute_volume: float = 0.0
_blocked_until: float = 0.0


def _is_valid_positive(val: Any) -> bool:
    """Validate value is a positive finite numeric float or int."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val > 0.0


def _is_valid_non_negative(val: Any) -> bool:
    """Validate value is a non-negative finite numeric float or int."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val >= 0.0


def record_trade(
    volume_lots: float = 1.0,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest a trade event with volume at given timestamp (or current time).
    Evaluates rolling rates, acceleration, cluster volume, and acute volume.
    """
    global _latest_rate_curr, _latest_rate_prev, _latest_acceleration
    global _latest_cluster_volume, _latest_acute_volume, _blocked_until

    if not _is_valid_positive(volume_lots):
        return

    vol = float(volume_lots)
    now = float(ts) if ts is not None else time.time()

    with _lock:
        _trade_events.append((now, vol))

        # Prune events older than HISTORY_WINDOW_SECONDS
        cutoff = now - HISTORY_WINDOW_SECONDS
        while _trade_events and _trade_events[0][0] < cutoff:
            _trade_events.popleft()

        rate_curr = 0.0
        rate_prev = 0.0
        cluster_vol = 0.0
        acute_vol = 0.0

        for t_evt, v in _trade_events:
            age = now - t_evt
            if age <= 0.3:
                acute_vol += v
            if age <= 1.0:
                rate_curr += 1.0
                cluster_vol += v
            elif age <= 2.0:
                rate_prev += 1.0

        acceleration = rate_curr - rate_prev

        _latest_rate_curr = rate_curr
        _latest_rate_prev = rate_prev
        _latest_acceleration = acceleration
        _latest_cluster_volume = cluster_vol
        _latest_acute_volume = acute_vol

        # Condition 1: Clustered volume avalanche or acute burst
        if cluster_vol >= MAX_CLUSTER_VOLUME or acute_vol >= MAX_ACUTE_VOLUME:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 2: Trade arrival frequency acceleration surge
        if acceleration >= MAX_TRADE_ACCELERATION and rate_curr >= MIN_CURRENT_RATE:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_trade_rate(
    trades_per_sec: float,
    prev_trades_per_sec: Optional[float] = None,
    volume_rate: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Directly ingest measured trade rates and volume rate.
    """
    global _latest_rate_curr, _latest_rate_prev, _latest_acceleration
    global _latest_cluster_volume, _blocked_until

    if not _is_valid_non_negative(trades_per_sec):
        return

    r_curr = float(trades_per_sec)

    with _lock:
        if prev_trades_per_sec is not None:
            if not _is_valid_non_negative(prev_trades_per_sec):
                return
            r_prev = float(prev_trades_per_sec)
        else:
            r_prev = _latest_rate_curr

        acceleration = r_curr - r_prev
        _latest_rate_curr = r_curr
        _latest_rate_prev = r_prev
        _latest_acceleration = acceleration

        if volume_rate is not None and _is_valid_non_negative(volume_rate):
            _latest_cluster_volume = float(volume_rate)
            if _latest_cluster_volume >= MAX_CLUSTER_VOLUME:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return

        if acceleration >= MAX_TRADE_ACCELERATION and r_curr >= MIN_CURRENT_RATE:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(
    volume_lots: float = 1.0,
    ts: Optional[float] = None,
) -> None:
    """Alias for record_trade()."""
    record_trade(volume_lots, ts)


def is_entry_blocked() -> bool:
    """Check if new entries are blocked by trade flow acceleration or avalanche."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_avalanche_metrics() -> Dict[str, float]:
    """Retrieve current trade flow avalanche metrics."""
    with _lock:
        return {
            "rate_curr": _latest_rate_curr,
            "rate_prev": _latest_rate_prev,
            "trade_acceleration": _latest_acceleration,
            "cluster_volume": _latest_cluster_volume,
            "acute_volume": _latest_acute_volume,
        }


def get_status() -> Dict[str, Any]:
    """Retrieve complete guard status."""
    with _lock:
        now = time.monotonic()
        blocked = now < _blocked_until
        remaining = max(0.0, _blocked_until - now) if blocked else 0.0
        return {
            "guard_name": "wave246_trade_flow_acceleration_avalanche_guard",
            "is_blocked": blocked,
            "blocked_seconds_remaining": remaining,
            "event_count": len(_trade_events),
            "rate_curr": _latest_rate_curr,
            "rate_prev": _latest_rate_prev,
            "trade_acceleration": _latest_acceleration,
            "cluster_volume": _latest_cluster_volume,
            "acute_volume": _latest_acute_volume,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "max_trade_acceleration": MAX_TRADE_ACCELERATION,
            "min_current_rate": MIN_CURRENT_RATE,
            "max_cluster_volume": MAX_CLUSTER_VOLUME,
            "max_acute_volume": MAX_ACUTE_VOLUME,
        }


def reset() -> None:
    """Reset all guard state and clear cooldowns."""
    global _latest_rate_curr, _latest_rate_prev, _latest_acceleration
    global _latest_cluster_volume, _latest_acute_volume, _blocked_until

    with _lock:
        _trade_events.clear()
        _latest_rate_curr = 0.0
        _latest_rate_prev = 0.0
        _latest_acceleration = 0.0
        _latest_cluster_volume = 0.0
        _latest_acute_volume = 0.0
        _blocked_until = 0.0
