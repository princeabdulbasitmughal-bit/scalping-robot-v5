"""
wave218_quote_run_length_directional_inertia_guard.py
-------------------------------------------------------
Guard: Quote Run Length & Microstructure Directional Inertia Guard

Monitors unidirectional quote streak lengths and price displacement rates (Engle 2000;
Hasbrouck 2018) to protect against momentum sweeps, predatory sweeps, and cascading stop hunts:
    Direction:             s_i = sign(P_{mid, i} - P_{mid, i-1})
    Run Length:            L_{run} = number of consecutive ticks in identical sign direction
    Run Displacement:      D_{run} = |P_{mid, i} - P_{start}| / P_{start} * 10,000 (bps)
    Run Velocity:          v_{run} = D_{run} / max(0.01, t_i - t_{start}) (bps/sec)

In normal two-sided microstructure equilibrium:
    - Quotes bounce stochastically with frequent sign reversals (+1, -1, +1, -1).
    - Streak lengths rarely exceed 4 or 5 consecutive ticks: L_{run} <= 5.

During institutional order shredding, iceberg sweeps, or cascading margin calls:
    - Quote ticks march relentlessly in one direction without pullbacks.
    - Persistent directional runs build dangerous microstructure inertia:
        1) Streak Run Length:
           L_{run} >= MAX_RUN_LENGTH (default: 8 ticks) AND
           D_{run} >= MIN_RUN_DISPLACEMENT_BPS (default: 3.5 bps).
        2) High-Velocity Quote Sweep:
           L_{run} >= 5 ticks AND
           v_{run} >= MAX_RUN_VELOCITY_BPS (default: 10.0 bps/sec).

Scalpers attempting to fade (mean-revert) or post counter-trend limit orders into these persistent
quote runs will be run over and filled at worst-case adverse selection.

When an excessive quote run or sweep velocity is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests midquote via record_midquote(mid_price, ts=None).
- Updates streak sign, run length L_{run}, start timestamp, and displacement D_{run}.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive prices are rejected.

Aliases (required):
  is_entry_blocked()                       -> bool
  is_blocked()                             -> bool   (alias)
  record_midquote(mid_price, ts=None)      -> None
  update(mid_price, ts=None)               -> None   (alias)
  get_run_metrics()                        -> dict
  get_status()                             -> dict
  reset()                                  -> None
"""

import math
import threading
import time
from typing import Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_RUN_LENGTH: int = 8                   # 8 consecutive unidirectional quote ticks
MIN_RUN_DISPLACEMENT_BPS: float = 3.5     # 3.5 bps minimum displacement along run
MIN_VELOCITY_RUN_LENGTH: int = 5          # 5 ticks minimum to evaluate sweep velocity
MAX_RUN_VELOCITY_BPS: float = 10.0        # 10.0 bps/sec displacement velocity
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_price: Optional[float] = None
_current_direction: int = 0               # +1 (up), -1 (down), 0 (none)
_current_run_length: int = 0
_run_start_price: Optional[float] = None
_run_start_ts: Optional[float] = None
_latest_displacement_bps: float = 0.0
_latest_velocity_bps: float = 0.0
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


def record_midquote(mid_price: float, ts: Optional[float] = None) -> None:
    """
    Ingest a new midquote and evaluate unidirectional quote run length and sweep velocity.
    """
    global _prev_price, _current_direction, _current_run_length
    global _run_start_price, _run_start_ts, _latest_displacement_bps, _latest_velocity_bps
    global _blocked_until

    if not _is_valid_price(mid_price):
        return

    p = float(mid_price)

    with _lock:
        now = time.monotonic() if ts is None else float(ts)

        if _prev_price is None:
            _prev_price = p
            _run_start_price = p
            _run_start_ts = now
            _current_direction = 0
            _current_run_length = 0
            return

        diff = p - _prev_price
        _prev_price = p

        # Check direction
        if abs(diff) < 1e-7:
            # Price unchanged; maintain run
            return

        direction = 1 if diff > 0.0 else -1

        if direction == _current_direction:
            # Extend current run
            _current_run_length += 1
        else:
            # Reversal; reset run
            _current_direction = direction
            _current_run_length = 1
            _run_start_price = p - diff  # Start was previous price
            _run_start_ts = now

        start_p = _run_start_price if _run_start_price is not None else p
        displacement_bps = (abs(p - start_p) / start_p) * 10_000.0
        _latest_displacement_bps = displacement_bps

        dt = max(0.01, now - (_run_start_ts if _run_start_ts is not None else now))
        velocity = displacement_bps / dt
        _latest_velocity_bps = velocity

        # Condition 1: Streak Run Length and displacement
        if _current_run_length >= MAX_RUN_LENGTH and displacement_bps >= MIN_RUN_DISPLACEMENT_BPS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 2: High-Velocity Quote Sweep
        if _current_run_length >= MIN_VELOCITY_RUN_LENGTH and velocity >= MAX_RUN_VELOCITY_BPS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(mid_price: float, ts: Optional[float] = None) -> None:
    """Alias for record_midquote()."""
    record_midquote(mid_price, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to unidirectional quote run."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_run_metrics() -> Dict[str, float]:
    """Return latest calculated run length, displacement, and velocity."""
    with _lock:
        return {
            "run_length": float(_current_run_length),
            "run_direction": float(_current_direction),
            "displacement_bps": _latest_displacement_bps,
            "velocity_bps_sec": _latest_velocity_bps,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the quote run length guard."""
    with _lock:
        now = time.monotonic()
        return {
            "run_length": _current_run_length,
            "run_direction": _current_direction,
            "displacement_bps": _latest_displacement_bps,
            "velocity_bps_sec": _latest_velocity_bps,
            "max_run_length": MAX_RUN_LENGTH,
            "min_run_displacement_bps": MIN_RUN_DISPLACEMENT_BPS,
            "max_run_velocity_bps": MAX_RUN_VELOCITY_BPS,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset quote history, run trackers, metrics, and active cooldown blocks."""
    global _prev_price, _current_direction, _current_run_length
    global _run_start_price, _run_start_ts, _latest_displacement_bps, _latest_velocity_bps
    global _blocked_until
    with _lock:
        _prev_price = None
        _current_direction = 0
        _current_run_length = 0
        _run_start_price = None
        _run_start_ts = None
        _latest_displacement_bps = 0.0
        _latest_velocity_bps = 0.0
        _blocked_until = 0.0
