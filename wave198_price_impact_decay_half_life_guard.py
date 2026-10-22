"""
wave198_price_impact_decay_half_life_guard.py
----------------------------------------------
Guard: Price Impact Decay Half-Life & Permanent Retracement Deficit Guard

Monitors post-shock price impact relaxation dynamics based on the Bouchaud-Farmer-Lillo (2009)
and Hasbrouck (1991) transient vs. permanent market impact decay formulations:
    I_0 = |P_shock - P_pre| / P_pre
    I(t) = I_perm + (I_0 - I_perm) * exp(-lambda * t)
where lambda is the decay rate and t_{1/2} = ln(2) / lambda is the impact half-life.

In healthy, elastic double-auction books with deep limit-order replenishing capacity, transient
price dislocation caused by an aggressive order execution decays rapidly back toward equilibrium:
    - Retracement ratio: Retrace = (I_0 - |P_t - P_pre| / P_pre) / I_0 >= 0.35 within 2.0s
    - Impact decay half-life: t_{1/2} < 2.0 seconds

During toxic institutional book sweeping, informed front-running, or permanent structural repricing,
the market exhibits an absorption deficit:
    1) Permanent dislocation with zero relaxation:
       Retrace < MIN_RETRACEMENT_RATIO (default: 0.35, or < 35% retraced after 2.0s)
    2) Divergent decay half-life:
       t_{1/2} >= MAX_HALF_LIFE_SEC (default: 2.5s) following a significant price shock
       (I_0 >= MIN_SHOCK_BPS = 3.0 bps).

Scalpers attempting mean reversion during permanent price dislocations suffer catastrophic adverse
selection as the market trends relentlessly through resting bids/asks.

When a price impact decay deficit is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests price ticks (price > 0.0, ts=None).
- Detects fast price shocks: price move >= MIN_SHOCK_BPS (3.0 bps) in <= 0.5s.
- Sets an observation window (EVAL_WINDOW_SEC = 2.0s).
- Tracks whether price retraces towards pre-shock level or diverges further.
- Computes empirical decay half-life t_{1/2} and post-window retracement ratio.
- Blocks entries for COOLDOWN_SECONDS (45.0s) if the shock fails to relax.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive price inputs are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_price(price, ts=None)                             -> None
  update(price, ts=None)                                   -> None   (alias)
  get_decay_metrics()                                      -> dict
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
MIN_SHOCK_BPS: float = 3.0             # 3.0 bps move initiates tracking
EVAL_WINDOW_SEC: float = 2.0           # 2.0s evaluation window
MIN_RETRACEMENT_RATIO: float = 0.35    # at least 35% of initial impact should relax
MAX_HALF_LIFE_SEC: float = 2.5         # maximum acceptable half-life
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_price: Optional[float] = None
_prev_ts: Optional[float] = None
_active_shock: Optional[Dict[str, Any]] = None
_latest_retracement_ratio: float = 1.0
_latest_half_life: float = 0.0
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


def record_price(price: float, ts: Optional[float] = None) -> None:
    """
    Ingest a new price tick and monitor price impact decay dynamics.
    """
    global _prev_price, _prev_ts, _active_shock
    global _latest_retracement_ratio, _latest_half_life, _blocked_until

    if not _is_valid_price(price):
        return

    p = float(price)
    with _lock:
        now = time.monotonic() if ts is None else float(ts)

        if _prev_price is None or _prev_ts is None:
            _prev_price = p
            _prev_ts = now
            return

        just_resolved = False
        # Check existing active shock
        if _active_shock is not None:
            pre_p = _active_shock["pre_p"]
            shock_p = _active_shock["shock_p"]
            shock_t = _active_shock["shock_t"]
            deadline = _active_shock["deadline"]
            i_0 = abs(shock_p - pre_p)

            # Instantaneous displacement from pre-shock price
            curr_disp = abs(p - pre_p)

            # Retracement: 1.0 if fully back to pre-shock, 0.0 if still at shock price, negative if worse
            if i_0 > 1e-9:
                retrace = (i_0 - curr_disp) / i_0
            else:
                retrace = 1.0

            _latest_retracement_ratio = retrace

            # Calculate empirical decay rate and half-life if some decay has occurred
            elapsed = now - shock_t
            if elapsed > 0.10:
                # If current displacement is smaller than initial, fit exponential decay: curr_disp / i_0 = exp(-lambda * elapsed)
                ratio_remaining = max(1e-4, min(1.0, curr_disp / i_0))
                decay_rate = -math.log(ratio_remaining) / elapsed
                if decay_rate > 1e-4:
                    _latest_half_life = math.log(2.0) / decay_rate
                else:
                    _latest_half_life = 99.0
            else:
                _latest_half_life = 0.0

            # Early recovery check: if retraced >= 70% before deadline, shock resolved cleanly
            if retrace >= 0.70:
                _active_shock = None
                just_resolved = True
            elif now >= deadline:
                # Window expired: evaluate permanent impact deficit
                if retrace < MIN_RETRACEMENT_RATIO or _latest_half_life >= MAX_HALF_LIFE_SEC:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                _active_shock = None
                just_resolved = True

        # Check for new price shock initiation
        dt = now - _prev_ts
        if not just_resolved and _active_shock is None and 0.0 < dt <= 0.50:
            price_move_bps = (abs(p - _prev_price) / _prev_price) * 10_000.0
            if price_move_bps >= MIN_SHOCK_BPS:
                _active_shock = {
                    "pre_p": _prev_price,
                    "shock_p": p,
                    "shock_t": now,
                    "deadline": now + EVAL_WINDOW_SEC,
                    "move_bps": price_move_bps,
                }
                _latest_retracement_ratio = 0.0
                _latest_half_life = 99.0

        _prev_price = p
        _prev_ts = now


def update(price: float, ts: Optional[float] = None) -> None:
    """Alias for record_price()."""
    record_price(price, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to permanent price impact."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_decay_metrics() -> Dict[str, float]:
    """Return latest observed retracement ratio and impact half-life."""
    with _lock:
        return {
            "retracement_ratio": _latest_retracement_ratio,
            "half_life_sec": _latest_half_life,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the price impact decay guard."""
    with _lock:
        now = time.monotonic()
        return {
            "retracement_ratio": _latest_retracement_ratio,
            "half_life_sec": _latest_half_life,
            "has_active_shock": _active_shock is not None,
            "min_retracement_threshold": MIN_RETRACEMENT_RATIO,
            "max_half_life_threshold": MAX_HALF_LIFE_SEC,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset price history, shock trackers, and active cooldown blocks."""
    global _prev_price, _prev_ts, _active_shock
    global _latest_retracement_ratio, _latest_half_life, _blocked_until
    with _lock:
        _prev_price = None
        _prev_ts = None
        _active_shock = None
        _latest_retracement_ratio = 1.0
        _latest_half_life = 0.0
        _blocked_until = 0.0
