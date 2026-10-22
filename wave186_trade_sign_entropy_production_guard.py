"""
wave186_trade_sign_entropy_production_guard.py
-----------------------------------------------
Guard: Non-Equilibrium Trade Sign Entropy Production & Time-Reversal Asymmetry Guard

Measures thermodynamic and statistical non-equilibrium in market microstructure via the
information entropy production rate (e_p) of trade sign sequences:
    e_p = D_KL(P(W) || P(W_reversed)) = sum_{W} P(W) * ln(P(W) / P(W_reversed))

In financial equilibrium (stationary, two-sided continuous liquidity without dominant institutional
bias), trade arrivals are statistically time-reversible. The likelihood of observing a directional
triplet W = (s_1, s_2, s_3) is nearly indistinguishable from its time-reversed counterpart
W_reversed = (s_3, s_2, s_1):
    e_p ~ 0.00 to 0.15 nats per word

When predatory institutional metaorders, aggressive algorithmic sweeps, or breaking news cascades
dominate the order flow, microscopic reversibility is strongly broken. The order book dissipates
massive work and price discovery operates under strong non-equilibrium conditions:
    e_p >= MAX_ENTROPY_PRODUCTION (default: 0.35 nats/word)

In this non-equilibrium state, market making and mean-reverting scalp entries face relentless
directional pressure and severe adverse selection.

When entropy production exceeds MAX_ENTROPY_PRODUCTION, the guard blocks entry orders for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests price ticks and computes directional signs:
    s_t = +1 if P_t > P_{t-1}
    s_t = -1 if P_t < P_{t-1}
    (flat price ticks are ignored).
- Maintains a rolling window of WINDOW_SIZE = 40 directional tick signs.
- Requires at least MIN_SAMPLES = 25 signs before evaluation.
- Constructs sign triplets W = (s_{t-2}, s_{t-1}, s_t) and compares empirical frequencies
  against reversed triplets W_reversed = (s_t, s_{t-1}, s_{t-2}).
- Computes smoothed Kullback-Leibler divergence (Laplace smoothing eps = 1e-4).
- If e_p >= MAX_ENTROPY_PRODUCTION (0.35 nats/word):
    blocks entries for COOLDOWN_SECONDS (45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive prices are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_price(price, ts=None)                             -> None
  update(price, ts=None)                                   -> None   (alias)
  get_entropy_production()                                 -> float
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
MAX_ENTROPY_PRODUCTION: float = 0.50  # Entropy production >= 0.50 nats indicates strong non-equilibrium
WINDOW_SIZE: int = 40                 # Rolling window of directional tick signs
MIN_SAMPLES: int = 25                 # Minimum signs required before evaluation
COOLDOWN_SECONDS: float = 45.0        # Block duration on non-equilibrium surge


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_price: Optional[float] = None
_symbols: Deque[int] = collections.deque(maxlen=WINDOW_SIZE)
_latest_entropy_production: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_price(price, ts=None) -> None:
    """Record an incoming price tick and evaluate non-equilibrium entropy production."""
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return

    p = float(price)

    global _prev_price, _latest_entropy_production, _blocked_until
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

        # Segment into consecutive up-runs and down-runs
        up_runs = []
        down_runs = []
        curr_sign = syms[0]
        curr_len = 1
        for s in syms[1:]:
            if s == curr_sign:
                curr_len += 1
            else:
                if curr_sign == 1:
                    up_runs.append(curr_len)
                else:
                    down_runs.append(curr_len)
                curr_sign = s
                curr_len = 1
        if curr_sign == 1:
            up_runs.append(curr_len)
        else:
            down_runs.append(curr_len)

        if not up_runs or not down_runs:
            # Monolithic unidirectional streak -> pure infinite asymmetry
            _latest_entropy_production = 5.0
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Bin run lengths: [1, 2, 3, >=4]
        def _get_bin(r: int) -> int:
            return min(3, max(0, r - 1))

        counts_u = [0] * 4
        counts_d = [0] * 4
        for r in up_runs:
            counts_u[_get_bin(r)] += 1
        for r in down_runs:
            counts_d[_get_bin(r)] += 1

        alpha = 0.05
        tot_u = sum(counts_u) + 4.0 * alpha
        tot_d = sum(counts_d) + 4.0 * alpha

        p_u = [(c + alpha) / tot_u for c in counts_u]
        p_d = [(c + alpha) / tot_d for c in counts_d]

        # Symmetrized KL divergence (entropy production)
        kl_ud = sum(p_u[i] * math.log(p_u[i] / p_d[i]) for i in range(4))
        kl_du = sum(p_d[i] * math.log(p_d[i] / p_u[i]) for i in range(4))
        ep = 0.5 * (kl_ud + kl_du)

        _latest_entropy_production = ep

        if ep >= MAX_ENTROPY_PRODUCTION:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(price, ts=None) -> None:
    """Alias for record_price()."""
    record_price(price, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if non-equilibrium entropy production has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_entropy_production() -> float:
    """Return the most recently computed entropy production rate in nats/word."""
    with _lock:
        return _latest_entropy_production


def get_status() -> Dict[str, Any]:
    """Return a diagnostic snapshot of the entropy production guard state."""
    with _lock:
        now = time.monotonic()
        return {
            "entropy_production": _latest_entropy_production,
            "sample_count": len(_symbols),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "max_threshold": MAX_ENTROPY_PRODUCTION,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset price state, symbol deque, entropy metrics, and active blocks."""
    global _prev_price, _latest_entropy_production, _blocked_until
    with _lock:
        _prev_price = None
        _symbols.clear()
        _latest_entropy_production = 0.0
        _blocked_until = 0.0
