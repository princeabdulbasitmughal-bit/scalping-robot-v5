"""
wave241_order_fill_imbalance_velocity_guard.py
------------------------------------------------
Guard: Order Fill Imbalance & Adverse Selection Velocity Guard

Monitors signed trade execution volume imbalance and acute fill velocity
(Easley, LÃ³pez de Prado & O'Hara 2012 - VPIN; Kyle 1985; Glosten & Milgrom 1985):
    Signed Volume:           V_{signed, i} = s_i * V_i,  s_i in {+1 (buy), -1 (sell)}
    Net Traded Volume:       V_{net} = \\sum_{i=1}^N V_{signed, i}
    Total Traded Volume:     V_{total} = \\sum_{i=1}^N V_i
    Volume Imbalance Ratio:  R_{vimb} = |V_{net}| / V_{total}
    Acute Fill Velocity:     v_{fill} = |V_{net, acute}| / max(0.1, \\Delta t_{acute}) (lots / sec)

In balanced, diffusive continuous double-auction markets:
    - Buy and sell fills arrive symmetrically over rolling trade windows:
      R_{vimb} <= 0.40, with gentle fill rate v_{fill} < 3.0 lots/sec.

During informed toxic cascades, one-sided stop-loss sweeps, or programmatic block liquidations:
    - Order flow aggressively concentrates in one direction, absorbing standing quotes:
        1) Extreme Directional Volume Imbalance:
           R_{vimb} >= MAX_VOLUME_IMBALANCE (default: 0.80 or 80%) AND
           V_{total} >= MIN_TOTAL_VOLUME (default: 15.0 lots) over rolling N >= 10 trades.
        2) Acute Fill Velocity Avalanche:
           v_{fill} >= MAX_FILL_VELOCITY (default: 8.0 lots/sec) over acute window <= 2.0s.

Providing passive liquidity or submitting counter-trend limit orders during one-sided volume avalanches
results in severe adverse selection, toxic fill toxicity, and immediate drawdown.

When extreme volume imbalance or acute fill velocity avalanche is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade executions via record_fill(side, volume, ts=None).
- Maintains rolling history of WINDOW_SIZE = 20 trade fills.
- Evaluates R_{vimb}, total volume, and acute fill velocity v_{fill}.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive volumes, or invalid sides are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_fill(side, volume, ts=None)                                                           -> None
  update(side, volume, ts=None)                                                                -> None   (alias)
  get_imbalance_metrics()                                                                      -> dict
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
MAX_VOLUME_IMBALANCE: float = 0.80     # 80% net volume imbalance ratio
MIN_TOTAL_VOLUME: float = 15.0         # 15.0 lots minimum total volume for ratio block
MAX_FILL_VELOCITY: float = 8.0         # 8.0 lots/sec acute fill velocity avalanche
ACUTE_WINDOW_SECONDS: float = 2.0      # 2.0s acute window
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_fills_history = collections.deque(maxlen=WINDOW_SIZE)  # elements: (timestamp, signed_volume, volume)
_latest_net_volume: float = 0.0
_latest_total_volume: float = 0.0
_latest_volume_imbalance: float = 0.0
_latest_fill_velocity: float = 0.0
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


def record_fill(
    side: Union[str, int, float],
    volume: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest a trade fill side, volume, and optional timestamp.
    Evaluates rolling volume imbalance ratio and acute fill velocity.
    """
    global _latest_net_volume, _latest_total_volume, _latest_volume_imbalance
    global _latest_fill_velocity, _blocked_until

    s = _parse_side(side)
    if s is None or not _is_valid_positive(volume):
        return

    vol = float(volume)
    signed_vol = s * vol
    now = float(ts) if ts is not None else time.time()

    with _lock:
        _fills_history.append((now, signed_vol, vol))

        n = len(_fills_history)
        net_vol = sum(f[1] for f in _fills_history)
        total_vol = sum(f[2] for f in _fills_history)
        imbalance = abs(net_vol) / max(0.001, total_vol)

        # Acute fill velocity over last ACUTE_WINDOW_SECONDS
        acute_signed_vol = 0.0
        acute_count = 0
        oldest_acute_ts = now
        for t_evt, s_vol, v in reversed(_fills_history):
            if (now - t_evt) <= ACUTE_WINDOW_SECONDS:
                acute_signed_vol += s_vol
                acute_count += 1
                oldest_acute_ts = min(oldest_acute_ts, t_evt)
            else:
                break

        # Require at least 2 fills or substantial acute volume before assessing acute velocity
        dt_acute = max(1.0, now - oldest_acute_ts)
        fill_velocity = abs(acute_signed_vol) / dt_acute if acute_count >= 2 else 0.0

        _latest_net_volume = net_vol
        _latest_total_volume = total_vol
        _latest_volume_imbalance = imbalance
        _latest_fill_velocity = fill_velocity

        # Condition 1: Acute fill velocity avalanche
        if fill_velocity >= MAX_FILL_VELOCITY:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 2: Extreme directional volume imbalance
        if (
            n >= MIN_SAMPLES
            and total_vol >= MIN_TOTAL_VOLUME
            and imbalance >= MAX_VOLUME_IMBALANCE
        ):
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(
    side: Union[str, int, float],
    volume: float,
    ts: Optional[float] = None,
) -> None:
    """Alias for record_fill()."""
    record_fill(side, volume, ts)


def is_entry_blocked() -> bool:
    """Check if new entries are blocked by order fill imbalance or velocity."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_imbalance_metrics() -> Dict[str, float]:
    """Retrieve current fill imbalance and velocity metrics."""
    with _lock:
        return {
            "net_volume": _latest_net_volume,
            "total_volume": _latest_total_volume,
            "volume_imbalance": _latest_volume_imbalance,
            "fill_velocity": _latest_fill_velocity,
        }


def get_status() -> Dict[str, Any]:
    """Retrieve complete guard status."""
    with _lock:
        now = time.monotonic()
        blocked = now < _blocked_until
        remaining = max(0.0, _blocked_until - now) if blocked else 0.0
        return {
            "guard_name": "wave241_order_fill_imbalance_velocity_guard",
            "is_blocked": blocked,
            "blocked_seconds_remaining": remaining,
            "sample_count": len(_fills_history),
            "net_volume": _latest_net_volume,
            "total_volume": _latest_total_volume,
            "volume_imbalance": _latest_volume_imbalance,
            "fill_velocity": _latest_fill_velocity,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "max_volume_imbalance": MAX_VOLUME_IMBALANCE,
            "min_total_volume": MIN_TOTAL_VOLUME,
            "max_fill_velocity": MAX_FILL_VELOCITY,
            "acute_window_seconds": ACUTE_WINDOW_SECONDS,
        }


def reset() -> None:
    """Reset all guard state and clear cooldowns."""
    global _latest_net_volume, _latest_total_volume, _latest_volume_imbalance
    global _latest_fill_velocity, _blocked_until

    with _lock:
        _fills_history.clear()
        _latest_net_volume = 0.0
        _latest_total_volume = 0.0
        _latest_volume_imbalance = 0.0
        _latest_fill_velocity = 0.0
        _blocked_until = 0.0
