"""
wave159_trade_sign_autocorrelation_guard.py
-------------------------------------------
Guard: Long-Memory Order Flow Trade Sign Autocorrelation Guard

Measures order flow persistence via lag-1 sample autocorrelation of trade signs (Bouchaud et al., 2004):
    epsilon_t in {+1 (buyer-initiated), -1 (seller-initiated)}
    C(1) = sum_{t=2}^N (epsilon_t - mean_eps) * (epsilon_{t-1} - mean_eps) / Var(epsilon)

Under balanced retail trading conditions, trade signs exhibit low or alternating autocorrelation
(C(1) near 0.0 or negative from bid-ask bouncing).
When institutional parent metaorders (TWAP, VWAP, POV execution algorithms) slice large inventory
into long streaks of unidirectional fills, trade signs develop high positive autocorrelation.
Scalpers taking the opposing side face catastrophic inventory accumulation and toxic adverse fills.
If C(1) >= MAX_SIGN_AUTOCORR (default: 0.45), an entry block is engaged for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Records trade signs (+1 for buy, -1 for sell).
- Normalizes incoming sign: > 0 -> +1.0, < 0 -> -1.0; ignores 0.0.
- Maintains rolling window (WINDOW_SIZE = 25 trade signs).
- Requires at least MIN_SAMPLES = 15 observations.
- Computes sample lag-1 autocorrelation C(1).
- If trade sign variance is degenerate (all identical signs in window):
    sets C(1) = 1.0 (pure unidirectional institutional flow).
- If C(1) >= MAX_SIGN_AUTOCORR (0.45):
    blocks entries for COOLDOWN_SECONDS (45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: invalid or corrupted trade signs are ignored.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_trade_sign(sign, ts=None)                         -> None
  update(sign, ts=None)                                    -> None   (alias)
  get_sign_autocorrelation()                               -> float
  reset()                                                  -> None
"""

import collections
import math
import threading
import time
from typing import Deque, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_SIGN_AUTOCORR: float = 0.45    # Lag-1 trade sign autocorrelation >= 0.45 triggers institutional flow guard
WINDOW_SIZE: int = 25              # Lookback window of trade signs
MIN_SAMPLES: int = 15              # Minimum samples required before evaluation
COOLDOWN_SECONDS: float = 45.0     # Block duration in seconds on order flow persistence


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_signs: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_latest_corr: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_trade_sign(sign, ts=None) -> None:
    """Record an incoming trade sign (+1 buy, -1 sell) and update sign autocorrelation."""
    if isinstance(sign, bool) or not isinstance(sign, (int, float)):
        return
    if math.isnan(sign) or math.isinf(sign):
        return

    raw = float(sign)
    if raw > 0.0:
        val = 1.0
    elif raw < 0.0:
        val = -1.0
    else:
        return

    global _latest_corr, _blocked_until
    with _lock:
        _signs.append(val)
        if len(_signs) < MIN_SAMPLES:
            return

        n = len(_signs)
        mean_eps = sum(_signs) / n
        denom = sum((eps - mean_eps) ** 2 for eps in _signs)

        if denom <= 1e-9:
            # All signs in the window are identical (+1 or -1) -> maximum persistence
            corr = 1.0
        else:
            numer = sum((_signs[t] - mean_eps) * (_signs[t - 1] - mean_eps) for t in range(1, n))
            corr = numer / denom

        # Bound corr to [-1.0, 1.0]
        corr = max(-1.0, min(1.0, corr))
        _latest_corr = corr

        if corr >= MAX_SIGN_AUTOCORR:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(sign, ts=None) -> None:
    """Alias for record_trade_sign()."""
    record_trade_sign(sign, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if institutional trade sign autocorrelation has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_sign_autocorrelation() -> float:
    """Return the most recently calculated trade sign autocorrelation."""
    with _lock:
        return _latest_corr


def reset() -> None:
    """Reset trade sign history, latest autocorrelation, and active cooldown."""
    global _latest_corr, _blocked_until
    with _lock:
        _signs.clear()
        _latest_corr = 0.0
        _blocked_until = 0.0
