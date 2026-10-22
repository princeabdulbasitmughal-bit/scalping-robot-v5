"""
wave176_order_flow_markov_drift_guard.py
-----------------------------------------
Guard: Second-Order Markov Chain Transition Drift & Absorption Guard

Measures directional persistence and non-ergodic trending drift in order flow via 2nd-order Markov
transition probabilities:
    P(+ | ++) = Count(+, +, +) / Count(+, +, *)
    P(- | --) = Count(-, -, -) / Count(-, -, *)

Under normal two-sided microstructure conditions, price tick changes are quasi-diffusive and
mean-reverting around the spread:
    P(+ | ++) ~ 0.35 to 0.55
    P(- | --) ~ 0.35 to 0.55

When aggressive institutional algorithms (e.g. predatory TWAP order shredders, momentum trend runners,
or cascading stop hunts) sweep the book, price changes enter a persistent drift regime where two
consecutive ticks in one direction strongly predict a third consecutive tick in the same direction
(P(+ | ++) or P(- | --) >= MAX_PERSISTENCE, default: 0.85).
In this persistent absorbing regime, scalpers attempting to fade the move or place counter-trend
limit orders face severe adverse selection.

When 2nd-order Markov persistence reaches or exceeds MAX_PERSISTENCE (0.85) with sufficient sample
support (MIN_PAIR_OCCURRENCES = 5), the guard blocks entry orders for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Records price ticks and computes directional signs:
    s_t = +1 if P_t > P_{t-1}
    s_t = -1 if P_t < P_{t-1}
    (flat ticks where P_t == P_{t-1} are ignored to prevent zero-transition distortion).
- Maintains a rolling window of WINDOW_SIZE = 40 directional tick signs.
- Requires at least MIN_SAMPLES = 20 directional signs before evaluation.
- Calculates empirical 2nd-order transition probabilities:
    P(+ | ++) = count(+, +, +) / count(+, +, *)
    P(- | --) = count(-, -, -) / count(-, -, *)
- If count(+, +, *) >= MIN_PAIR_OCCURRENCES and P(+ | ++) >= MAX_PERSISTENCE:
    blocks entries for COOLDOWN_SECONDS (45.0s).
- If count(-, -, *) >= MIN_PAIR_OCCURRENCES and P(- | --) >= MAX_PERSISTENCE:
    blocks entries for COOLDOWN_SECONDS (45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive prices are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_price(price, ts=None)                             -> None
  update(price, ts=None)                                   -> None   (alias)
  get_transition_probabilities()                           -> dict
  get_status()                                             -> dict
  reset()                                                  -> None
"""

import collections
import math
import threading
import time
from typing import Deque, Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_PERSISTENCE: float = 0.85         # Persistence >= 0.85 indicates absorbing trend drift
WINDOW_SIZE: int = 40                 # Rolling window of directional tick signs
MIN_SAMPLES: int = 20                 # Minimum signs required before evaluation
MIN_PAIR_OCCURRENCES: int = 5         # Minimum conditioning pair observations
COOLDOWN_SECONDS: float = 45.0        # Block duration on absorbing transition drift


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_price: Optional[float] = None
_symbols: Deque[int] = collections.deque(maxlen=WINDOW_SIZE)
_p_plus_given_plus_plus: float = 0.50
_p_minus_given_minus_minus: float = 0.50
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_price(price, ts=None) -> None:
    """Record an incoming price tick and evaluate 2nd-order Markov transition probabilities."""
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return

    p = float(price)

    global _prev_price, _p_plus_given_plus_plus, _p_minus_given_minus_minus, _blocked_until
    with _lock:
        if _prev_price is None:
            _prev_price = p
            return

        diff = p - _prev_price
        _prev_price = p

        if abs(diff) < 1e-9:
            return

        sym = 1 if diff > 0.0 else -1
        _symbols.append(sym)

        if len(_symbols) < MIN_SAMPLES:
            return

        syms = list(_symbols)
        n = len(syms)

        # Transition counts for triplets: (s_{t-2}, s_{t-1}, s_t)
        count_ppp = 0
        count_ppm = 0
        count_mmm = 0
        count_mmp = 0

        for t in range(2, n):
            s_prev2 = syms[t - 2]
            s_prev1 = syms[t - 1]
            s_curr = syms[t]

            if s_prev2 == 1 and s_prev1 == 1:
                if s_curr == 1:
                    count_ppp += 1
                else:
                    count_ppm += 1
            elif s_prev2 == -1 and s_prev1 == -1:
                if s_curr == -1:
                    count_mmm += 1
                else:
                    count_mmp += 1

        total_pp = count_ppp + count_ppm
        total_mm = count_mmm + count_mmp

        p_plus_given_pp = (count_ppp / total_pp) if total_pp > 0 else 0.50
        p_minus_given_mm = (count_mmm / total_mm) if total_mm > 0 else 0.50

        _p_plus_given_plus_plus = p_plus_given_pp
        _p_minus_given_minus_minus = p_minus_given_mm

        should_block = False
        if total_pp >= MIN_PAIR_OCCURRENCES and p_plus_given_pp >= MAX_PERSISTENCE:
            should_block = True
        if total_mm >= MIN_PAIR_OCCURRENCES and p_minus_given_mm >= MAX_PERSISTENCE:
            should_block = True

        if should_block:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(price, ts=None) -> None:
    """Alias for record_price()."""
    record_price(price, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if 2nd-order Markov absorbing persistence has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_transition_probabilities() -> Dict[str, float]:
    """Return the most recently computed 2nd-order transition probabilities."""
    with _lock:
        return {
            "p_plus_given_plus_plus": _p_plus_given_plus_plus,
            "p_minus_given_minus_minus": _p_minus_given_minus_minus,
        }


def get_status() -> Dict[str, Any]:
    """Return a diagnostic snapshot of the Markov drift guard state."""
    with _lock:
        now = time.monotonic()
        return {
            "p_plus_given_plus_plus": _p_plus_given_plus_plus,
            "p_minus_given_minus_minus": _p_minus_given_minus_minus,
            "sample_count": len(_symbols),
            "max_samples": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "max_persistence_threshold": MAX_PERSISTENCE,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset price state, symbol history, probabilities, and active blocks."""
    global _prev_price, _p_plus_given_plus_plus, _p_minus_given_minus_minus, _blocked_until
    with _lock:
        _prev_price = None
        _symbols.clear()
        _p_plus_given_plus_plus = 0.50
        _p_minus_given_minus_minus = 0.50
        _blocked_until = 0.0
