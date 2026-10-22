"""
wave213_trade_sign_markov_drift_acceleration_guard.py
------------------------------------------------------
Guard: Second-Order Trade Direction Markov Transition & Drift Acceleration Guard

Monitors higher-order conditional directional persistence and momentum acceleration in executed trades
using second-order discrete Markov transition probabilities:
    State:          (s_{t-2}, s_{t-1}) in {(+, +), (+, -), (-, +), (-, -)}
    P(+ | ++) =     N(+, +, +) / max(1, N(+, +, +) + N(+, +, -))
    P(- | --) =     N(-, -, -) / max(1, N(-, -, -) + N(-, -, +))

In balanced, stochastically diffusive order flow:
    P(+ | ++) approx 0.50 and P(- | --) approx 0.50 (0.35 <= P <= 0.65).

During predatory institutional book sweeping, momentum chasing cascades, or aggressive iceberg
unloading, directional order flow accelerates non-linearly:
    P(+ | ++) >= MAX_MARKOV_DRIFT (default: 0.85) or P(- | --) >= MAX_MARKOV_DRIFT (0.85)
    with minimum state sample observations (N_{pair} >= MIN_STATE_COUNT = 6).

In these runaway Markov drift regimes, counter-trend scalping positions are swept away by
continuous unilateral market orders.

When second-order Markov drift acceleration breaches the safety limit, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trades via record_trade(price=None, side=None, ts=None).
- Determines trade direction (+1 for buy, -1 for sell).
- Maintains a rolling window of WINDOW_SIZE = 25 signed trades.
- Requires at least MIN_SAMPLES = 15 trades before Markov transition evaluation.
- Computes empirical transition probabilities P(+ | ++) and P(- | --).
- Blocks entries for COOLDOWN_SECONDS (45.0s) if either conditional probability >= 0.85.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: invalid, non-numeric, or ambiguous inputs are safely handled/rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_trade(price=None, side=None, ts=None)             -> None
  update(price=None, side=None, ts=None)                   -> None   (alias)
  get_markov_metrics()                                     -> dict
  get_status()                                             -> dict
  reset()                                                  -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 25
MIN_SAMPLES: int = 15
MIN_STATE_COUNT: int = 6               # minimum occurrences of (++, *) or (--, *)
MAX_MARKOV_DRIFT: float = 0.85         # 85% conditional follow-through probability
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_signs = collections.deque(maxlen=WINDOW_SIZE)
_last_price: Optional[float] = None
_last_sign: Optional[int] = None
_latest_p_plus: float = 0.50
_latest_p_minus: float = 0.50
_blocked_until: float = 0.0


def _parse_sign(price: Any, side: Any) -> Optional[int]:
    """Parse trade direction to +1 (buy) or -1 (sell)."""
    global _last_price, _last_sign

    if side is not None:
        if isinstance(side, bool):
            return None
        if isinstance(side, (int, float)):
            if side > 0:
                return 1
            elif side < 0:
                return -1
            return None
        if isinstance(side, str):
            s = side.strip().lower()
            if s in ("buy", "b", "1", "+1", "long"):
                return 1
            if s in ("sell", "s", "-1", "short"):
                return -1
        return None

    if price is not None:
        if isinstance(price, bool):
            return None
        if not isinstance(price, (int, float)):
            return None
        if math.isnan(price) or math.isinf(price) or price <= 0.0:
            return None

        p = float(price)
        if _last_price is None:
            _last_price = p
            return None

        diff = p - _last_price
        _last_price = p

        if diff > 1e-9:
            return 1
        elif diff < -1e-9:
            return -1
        else:
            return _last_sign

    return None


def record_trade(
    price: Optional[float] = None,
    side: Optional[Any] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest a new trade execution, update signed history, and evaluate Markov drift.
    """
    global _last_sign, _latest_p_plus, _latest_p_minus, _blocked_until

    sign = _parse_sign(price, side)
    if sign is None:
        return

    with _lock:
        now = time.monotonic() if ts is None else float(ts)
        _last_sign = sign
        _signs.append(sign)

        n = len(_signs)
        if n < MIN_SAMPLES:
            return

        # Count 2nd-order transitions
        plus_follow = 0
        plus_total = 0
        minus_follow = 0
        minus_total = 0

        for i in range(2, n):
            s_prev2 = _signs[i - 2]
            s_prev1 = _signs[i - 1]
            s_curr = _signs[i]

            if s_prev2 == 1 and s_prev1 == 1:
                plus_total += 1
                if s_curr == 1:
                    plus_follow += 1

            elif s_prev2 == -1 and s_prev1 == -1:
                minus_total += 1
                if s_curr == -1:
                    minus_follow += 1

        p_plus = (plus_follow / float(plus_total)) if plus_total > 0 else 0.50
        p_minus = (minus_follow / float(minus_total)) if minus_total > 0 else 0.50

        _latest_p_plus = p_plus
        _latest_p_minus = p_minus

        # Condition 1: Upward Markov drift acceleration
        if plus_total >= MIN_STATE_COUNT and p_plus >= MAX_MARKOV_DRIFT:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 2: Downward Markov drift acceleration
        if minus_total >= MIN_STATE_COUNT and p_minus >= MAX_MARKOV_DRIFT:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(
    price: Optional[float] = None,
    side: Optional[Any] = None,
    ts: Optional[float] = None,
) -> None:
    """Alias for record_trade()."""
    record_trade(price, side, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to Markov drift acceleration."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_markov_metrics() -> Dict[str, float]:
    """Return latest calculated conditional Markov probabilities."""
    with _lock:
        return {
            "p_plus_given_plus_plus": _latest_p_plus,
            "p_minus_given_minus_minus": _latest_p_minus,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the Markov drift guard."""
    with _lock:
        now = time.monotonic()
        return {
            "p_plus_given_plus_plus": _latest_p_plus,
            "p_minus_given_minus_minus": _latest_p_minus,
            "sample_count": len(_signs),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "min_state_count": MIN_STATE_COUNT,
            "max_markov_drift_threshold": MAX_MARKOV_DRIFT,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset signed trade history, Markov metrics, and active cooldown blocks."""
    global _last_price, _last_sign, _latest_p_plus, _latest_p_minus, _blocked_until
    with _lock:
        _signs.clear()
        _last_price = None
        _last_sign = None
        _latest_p_plus = 0.50
        _latest_p_minus = 0.50
        _blocked_until = 0.0
