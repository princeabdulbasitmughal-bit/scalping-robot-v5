"""
wave154_kyle_lambda_price_impact_guard.py
-----------------------------------------
Guard: Kyle's Lambda Dynamic Price Impact & Market Illiquidity Guard

Measures continuous market illiquidity and adverse selection cost via Kyle's Lambda (Kyle, 1985):
    Delta_P = lambda * Q + epsilon
    lambda = Cov(Delta_P, Q) / Var(Q)
where Delta_P is the tick price change and Q is signed trading volume (+ for buyer-initiated,
- for seller-initiated).

Under deep liquidity, large orders Q produce minimal price movement (lambda near 0.0).
When order book depth vanishes or toxic informed institutional flows enter, lambda surges,
meaning even small retail orders suffer severe adverse price displacement.
When lambda >= MAX_KYLE_LAMBDA (default: 0.0020), entries are blocked for COOLDOWN_SECONDS
(default: 45.0s) to avoid entering illiquid flash states.

Logic:
- Records pairs of (price_delta, signed_volume) over rolling window (WINDOW_SIZE = 20).
- Validates inputs (numeric, non-NaN, non-Inf, non-boolean).
- Computes sample Cov(Delta_P, Q) and Var(Q).
- Evaluates lambda = Cov / Var(Q).
- If lambda >= MAX_KYLE_LAMBDA (0.0020):
    blocks entries for COOLDOWN_SECONDS (45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: corrupted or degenerate inputs are ignored.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_trade_impact(price_delta, signed_volume, ts=None) -> None
  update(price_delta, signed_volume, ts=None)              -> None   (alias)
  get_kyle_lambda()                                        -> float
  reset()                                                  -> None
"""

import collections
import math
import threading
import time
from typing import Deque, Optional, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_KYLE_LAMBDA: float = 0.0020    # 20 bps price impact per signed lot triggers illiquidity guard
WINDOW_SIZE: int = 20              # Number of observations in rolling regression window
MIN_SAMPLES: int = 10              # Minimum observations required to compute regression
COOLDOWN_SECONDS: float = 45.0     # Block duration in seconds on excessive price impact


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_history: Deque[Tuple[float, float]] = collections.deque(maxlen=WINDOW_SIZE)
_latest_lambda: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_trade_impact(price_delta, signed_volume, ts=None) -> None:
    """Record a trade's price displacement and signed volume, evaluating Kyle's Lambda."""
    for val in (price_delta, signed_volume):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return
        if math.isnan(val) or math.isinf(val):
            return

    dp = float(price_delta)
    q = float(signed_volume)

    global _latest_lambda, _blocked_until
    with _lock:
        _history.append((dp, q))
        if len(_history) < MIN_SAMPLES:
            return

        n = len(_history)
        mean_dp = sum(item[0] for item in _history) / n
        mean_q = sum(item[1] for item in _history) / n

        var_q = sum((item[1] - mean_q) ** 2 for item in _history) / n
        if var_q <= 1e-9:
            return

        cov_dp_q = sum((item[0] - mean_dp) * (item[1] - mean_q) for item in _history) / n
        kyle_lambda = cov_dp_q / var_q
        _latest_lambda = kyle_lambda

        if kyle_lambda >= MAX_KYLE_LAMBDA:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(price_delta, signed_volume, ts=None) -> None:
    """Alias for record_trade_impact()."""
    record_trade_impact(price_delta, signed_volume, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if Kyle's Lambda price impact has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_kyle_lambda() -> float:
    """Return the most recently calculated Kyle's Lambda price impact coefficient."""
    with _lock:
        return _latest_lambda


def reset() -> None:
    """Reset observation history, latest lambda, and active cooldown."""
    global _latest_lambda, _blocked_until
    with _lock:
        _history.clear()
        _latest_lambda = 0.0
        _blocked_until = 0.0
