"""
wave237_trade_markov_run_momentum_persistence_guard.py
-------------------------------------------------------
Guard: Trade Flow Markov Run Transition & Momentum Persistence Guard

Monitors second-order conditional Markov trade flow transitions and persistent directional
streaks (Engle & Russell 1998; Rydberg & Shephard 2003):
    Trade Direction:       s_t in {+1 (buy), -1 (sell)}
    Conditional Prob:      P(+ | ++) = N(+, +, +) / max(1, N(+, +))
                           P(- | --) = N(-, -, -) / max(1, N(-, -))
    Directional Streak:    L_{streak} = consecutive trades in identical direction
                           over rolling N = 25 trades.

In balanced, diffusive continuous double-auction markets:
    - Order flow displays mean-reverting or mild Markov transitions:
      P(+ | ++) ~ 0.50 - 0.55, P(- | --) ~ 0.50 - 0.55, with L_{streak} <= 5.

During aggressive predatory sweeps, iceberg execution, or institutional liquidation cascades:
    - Buyers or sellers relentlessly compound flow in the same direction:
        1) Extreme Markov Continuation:
           P(+ | ++) >= MAX_MARKOV_PERSISTENCE (default: 0.85) with N_{++} >= 6 OR
           P(- | --) >= MAX_MARKOV_PERSISTENCE (default: 0.85) with N_{--} >= 6.
        2) Acute Directional Streak:
           L_{streak} >= MAX_STREAK_LENGTH (default: 8 consecutive trades).

Fading or posting passive counter-orders into persistent Markov momentum sweeps guarantees
immediate adverse execution selection and severe negative alpha.

When extreme Markov run persistence or acute streak is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade direction via record_trade(side, ts=None).
- Maintains rolling history of WINDOW_SIZE = 25 trade signs.
- Requires MIN_SAMPLES = 15 trades before evaluating Markov transitions.
- Evaluates P(+|++), P(-|--), and streak length.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: invalid sides, booleans, NaN, Inf are rejected.

Aliases (required):
  is_entry_blocked()                                                   -> bool
  is_blocked()                                                         -> bool   (alias)
  record_trade(side, ts=None)                                          -> None
  update(side, ts=None)                                                -> None   (alias)
  get_markov_metrics()                                                 -> dict
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
WINDOW_SIZE: int = 25
MIN_SAMPLES: int = 15
MIN_PAIR_SAMPLES: int = 6
MAX_MARKOV_PERSISTENCE: float = 0.85      # 85% conditional continuation persistence
MAX_STREAK_LENGTH: int = 8                # 8 consecutive trades in identical direction
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_trades = collections.deque(maxlen=WINDOW_SIZE)
_current_streak_side: Optional[int] = None
_current_streak_length: int = 0
_latest_p_plus: float = 0.50
_latest_p_minus: float = 0.50
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


def record_trade(
    side: Union[str, int, float],
    ts: Optional[float] = None,
) -> None:
    """
    Ingest a trade side and evaluate 2nd-order Markov transitions and streak length.
    """
    global _current_streak_side, _current_streak_length
    global _latest_p_plus, _latest_p_minus, _blocked_until

    s = _parse_side(side)
    if s is None:
        return

    with _lock:
        # Update streak
        if s == _current_streak_side:
            _current_streak_length += 1
        else:
            _current_streak_side = s
            _current_streak_length = 1

        # Check Condition 2: Acute Directional Streak
        if _current_streak_length >= MAX_STREAK_LENGTH:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        _trades.append(s)
        n = len(_trades)
        if n < MIN_SAMPLES:
            return

        # Compute 2nd-order Markov transitions
        n_plus_plus = 0
        n_plus_plus_plus = 0
        n_minus_minus = 0
        n_minus_minus_minus = 0

        for i in range(2, n):
            s_prev2 = _trades[i - 2]
            s_prev1 = _trades[i - 1]
            s_curr = _trades[i]

            if s_prev2 == 1 and s_prev1 == 1:
                n_plus_plus += 1
                if s_curr == 1:
                    n_plus_plus_plus += 1

            if s_prev2 == -1 and s_prev1 == -1:
                n_minus_minus += 1
                if s_curr == -1:
                    n_minus_minus_minus += 1

        p_plus = (n_plus_plus_plus / float(n_plus_plus)) if n_plus_plus > 0 else 0.50
        p_minus = (n_minus_minus_minus / float(n_minus_minus)) if n_minus_minus > 0 else 0.50

        _latest_p_plus = p_plus
        _latest_p_minus = p_minus

        # Check Condition 1: Extreme Markov Continuation Persistence
        if n_plus_plus >= MIN_PAIR_SAMPLES and p_plus >= MAX_MARKOV_PERSISTENCE:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        if n_minus_minus >= MIN_PAIR_SAMPLES and p_minus >= MAX_MARKOV_PERSISTENCE:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(side: Union[str, int, float], ts: Optional[float] = None) -> None:
    """Alias for record_trade()."""
    record_trade(side, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to Markov run persistence."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_markov_metrics() -> Dict[str, float]:
    """Return latest calculated Markov transition probabilities and streak length."""
    with _lock:
        return {
            "p_plus_given_plus_plus": _latest_p_plus,
            "p_minus_given_minus_minus": _latest_p_minus,
            "streak_length": float(_current_streak_length),
            "streak_side": float(_current_streak_side if _current_streak_side is not None else 0),
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the trade Markov transition guard."""
    with _lock:
        now = time.monotonic()
        return {
            "p_plus_given_plus_plus": _latest_p_plus,
            "p_minus_given_minus_minus": _latest_p_minus,
            "streak_length": _current_streak_length,
            "streak_side": _current_streak_side,
            "sample_count": len(_trades),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "max_markov_persistence": MAX_MARKOV_PERSISTENCE,
            "max_streak_length": MAX_STREAK_LENGTH,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset trade history, streak counters, metrics, and active cooldown blocks."""
    global _trades, _current_streak_side, _current_streak_length
    global _latest_p_plus, _latest_p_minus, _blocked_until
    with _lock:
        _trades.clear()
        _current_streak_side = None
        _current_streak_length = 0
        _latest_p_plus = 0.50
        _latest_p_minus = 0.50
        _blocked_until = 0.0
