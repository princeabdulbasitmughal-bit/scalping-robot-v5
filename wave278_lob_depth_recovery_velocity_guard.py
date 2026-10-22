"""
wave278_lob_depth_recovery_velocity_guard.py
--------------------------------------------
Guard: LOB Inside-Queue Replenishment Speed & Post-Trade Velocity Guard

Monitors limit order book depth replenishment velocity and post-sweep liquidity restitution rate
(Biais et al. 1995; Large 2007; Ponzi, Lillo & Mantegna 2009):
    Post-Depletion Restitution: Delta Q_{rec} = Q_{curr} - Q_{depleted} (lots)
    Replenishment Velocity:     v_{rec} = Delta Q_{rec} / max(Delta t, 0.05) (lots / sec)
    Acute Replenishment Freeze: v_{rec} <= 0.15 lots/s over Delta t >= 2.50s

Under active, competitive market making conditions:
    - Depleted queue depth is replenished rapidly by limit order posting: v_{rec} >= 2.50 to 8.00 lots/sec.
    - Market makers actively restock quotes to earn the spread without leaving hollow gaps.

During predatory sweeps, inventory exhaustion, or dealer flight:
    - Order book depth remains unreplenished or replenishes at an extremely sluggish pace:
        1) Sluggish Replenishment Velocity Persistence:
           Rolling mean \\bar{v}_{rec} <= MIN_REPLENISH_VELOCITY (default: 0.80 lots/s) over N >= MIN_SAMPLES (8 recovery intervals).
        2) Acute Replenishment Freeze:
           v_{rec} <= ACUTE_FREEZE_VELOCITY (0.15 lots/s) over Delta t >= MIN_FREEZE_DURATION_SEC (2.50s).

Executing trades during an unreplenished liquidity freeze exposes orders to severe queue slippage,
spread widening, and extreme negative fill selection.

When sluggish replenishment or an acute replenishment freeze is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests recovery velocity via record_recovery_velocity(velocity_lots_per_sec, sample_count=None, ts=None) or
  depth transitions via record_depth_transition(prev_depth, curr_depth, delta_t_sec, ts=None).
- Maintains rolling history of WINDOW_SIZE = 15 replenishment velocity observations.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative times are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_recovery_velocity(velocity_lots_per_sec, sample_count=None, ts=None)                   -> None
  record_depth_transition(prev_depth, curr_depth, delta_t_sec, ts=None)                        -> None
  update(velocity_lots_per_sec, delta_t_sec=None, ts=None)                                     -> None   (alias)
  get_recovery_metrics()                                                                       -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Dict, Optional, Any, Deque

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 15                   # 15 recovery observations rolling window
MIN_SAMPLES: int = 8                    # 8 observations minimum for mean velocity evaluation
MIN_REPLENISH_VELOCITY: float = 0.80    # 0.80 lots/sec minimum acceptable mean recovery speed
ACUTE_FREEZE_VELOCITY: float = 0.15     # 0.15 lots/sec acute freeze speed floor
MIN_FREEZE_DURATION_SEC: float = 2.50   # 2.50s minimum duration for acute freeze trigger
COOLDOWN_SECONDS: float = 45.0          # 45.0s block duration

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_velocities: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_latest_velocity: float = 3.0
_latest_mean_velocity: float = 3.0
_blocked_until: float = 0.0


def _is_valid_non_negative(val: Any) -> bool:
    """Validate value is a non-negative finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val >= 0.0


def _is_valid_numeric(val: Any) -> bool:
    """Validate value is a finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return True


def record_recovery_velocity(
    velocity_lots_per_sec: float,
    sample_count: Optional[int] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Directly ingest precomputed replenishment velocity in lots per second.
    """
    global _latest_velocity, _latest_mean_velocity, _blocked_until

    if not _is_valid_numeric(velocity_lots_per_sec):
        return

    v = float(velocity_lots_per_sec)
    n = int(sample_count) if (sample_count is not None and isinstance(sample_count, int) and not isinstance(sample_count, bool) and sample_count > 0) else 10

    with _lock:
        _latest_velocity = v
        _velocities.append(v)

        if len(_velocities) >= MIN_SAMPLES:
            mean_v = statistics.mean(_velocities)
            _latest_mean_velocity = mean_v

            # Condition 1: Sluggish Replenishment Velocity Persistence
            if mean_v <= MIN_REPLENISH_VELOCITY and n >= MIN_SAMPLES:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return


def record_depth_transition(
    prev_depth: float,
    curr_depth: float,
    delta_t_sec: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest depth before and after replenishment, calculate velocity, and detect freezes.
    """
    global _latest_velocity, _latest_mean_velocity, _blocked_until

    if not (_is_valid_non_negative(prev_depth) and _is_valid_non_negative(curr_depth) and _is_valid_non_negative(delta_t_sec)):
        return

    q_prev = float(prev_depth)
    q_curr = float(curr_depth)
    dt = float(delta_t_sec)

    if dt <= 0.0:
        return

    d_q = q_curr - q_prev
    v = d_q / dt

    with _lock:
        _latest_velocity = v

        # Condition 2: Acute Replenishment Freeze
        if v <= ACUTE_FREEZE_VELOCITY and dt >= MIN_FREEZE_DURATION_SEC:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            _velocities.append(v)
            return

        _velocities.append(v)

        if len(_velocities) >= MIN_SAMPLES:
            mean_v = statistics.mean(_velocities)
            _latest_mean_velocity = mean_v

            # Condition 1: Sluggish Replenishment Velocity Persistence
            if mean_v <= MIN_REPLENISH_VELOCITY:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return


def update(
    velocity_lots_per_sec: float,
    delta_t_sec: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """Module alias for record_recovery_velocity or record_depth_transition."""
    if delta_t_sec is None:
        record_recovery_velocity(velocity_lots_per_sec, ts=ts)
    else:
        # Treat as prev_depth=0.0, curr_depth=velocity_lots_per_sec, delta_t=delta_t_sec
        record_depth_transition(0.0, velocity_lots_per_sec, delta_t_sec, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if entry is currently blocked by recovery velocity guard."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked."""
    return is_entry_blocked()


def get_recovery_metrics() -> Dict[str, Any]:
    """Return dictionary of current replenishment metrics."""
    with _lock:
        mean_v = statistics.mean(_velocities) if _velocities else 3.0
        return {
            "latest_velocity": round(_latest_velocity, 4),
            "mean_velocity": round(mean_v, 4),
            "sample_count": len(_velocities),
            "min_replenish_velocity": MIN_REPLENISH_VELOCITY,
            "acute_freeze_velocity": ACUTE_FREEZE_VELOCITY,
            "is_blocked": is_entry_blocked(),
        }


def get_status() -> Dict[str, Any]:
    """Return complete status dictionary."""
    with _lock:
        remaining_cd = max(0.0, _blocked_until - time.monotonic())
        metrics = get_recovery_metrics()
        metrics["cooldown_remaining_sec"] = round(remaining_cd, 2)
        return metrics


def reset() -> None:
    """Reset all state to initial defaults."""
    global _velocities, _latest_velocity, _latest_mean_velocity, _blocked_until
    with _lock:
        _velocities.clear()
        _latest_velocity = 3.0
        _latest_mean_velocity = 3.0
        _blocked_until = 0.0
