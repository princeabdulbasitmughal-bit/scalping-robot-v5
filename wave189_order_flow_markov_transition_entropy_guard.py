"""
wave189_order_flow_markov_transition_entropy_guard.py
------------------------------------------------------
Guard: Directional Markov Transition Matrix Stationary Shannon Entropy Guard

Measures algorithmic determinism and transition predictability across directional price changes via
the stationary conditional Shannon entropy rate of the first-order Markov transition matrix:
    P = [ [p_{++}, p_{+-}], [p_{-+}, p_{--}] ]
    H(S) = pi_+ * H(+ -> .) + pi_- * H(- -> .)  [in bits per transition]
where pi = (pi_+, pi_-) is the ergodic stationary distribution satisfying pi * P = pi.

In healthy two-sided markets with random order arrivals:
    p_{++} ~ 0.50,  p_{--} ~ 0.50,  pi_+ ~ pi_- ~ 0.50
    H(S) ~ 0.90 to 1.00 bit per transition.

When algorithmic execution metaorders (e.g. aggressive TWAP sweeps or predatory ping-pong spoofing)
dominate the book, transition pathways become rigidly deterministic:
1. Directional absorbing sweeps: p_{++} -> 1.0 or p_{--} -> 1.0
2. Rigid alternating spoofing cycles: p_{+-} -> 1.0 and p_{-+} -> 1.0
In both deterministic regimes, the conditional Markov transition entropy collapses:
    H(S) <= MIN_MARKOV_ENTROPY (default: 0.45 bits)

When Markov transition entropy collapses, scalping spread-capture edge evaporates because the
order flow is under total programmatic control.

When H(S) drops below MIN_MARKOV_ENTROPY, the guard blocks entry orders for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests price ticks and computes directional signs (+1, -1; ignores zero-difference flat ticks).
- Maintains a rolling window of WINDOW_SIZE = 35 directional signs.
- Requires at least MIN_SAMPLES = 20 directional signs before evaluation.
- Calculates empirical transition counts: n_{++}, n_{+-}, n_{-+}, n_{--}.
- Derives transition probabilities with Laplace smoothing (alpha = 0.05).
- Solves for stationary distribution pi = (p_{-+} / (p_{+-} + p_{-+}), p_{+-} / (p_{+-} + p_{-+})).
- Computes weighted conditional Shannon entropy rate H(S).
- If H(S) <= MIN_MARKOV_ENTROPY (0.45 bits):
    blocks entries for COOLDOWN_SECONDS (45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive prices are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_price(price, ts=None)                             -> None
  update(price, ts=None)                                   -> None   (alias)
  get_markov_entropy()                                     -> float
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
MIN_MARKOV_ENTROPY: float = 0.45      # Entropy <= 0.45 bits indicates rigid algorithmic transitions
WINDOW_SIZE: int = 35                 # Rolling window of directional tick signs
MIN_SAMPLES: int = 20                 # Minimum signs required before evaluation
COOLDOWN_SECONDS: float = 45.0        # Block duration on Markov entropy collapse


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_price: Optional[float] = None
_symbols: Deque[int] = collections.deque(maxlen=WINDOW_SIZE)
_latest_entropy: float = 1.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_price(price, ts=None) -> None:
    """Record an incoming price tick and evaluate Markov transition matrix entropy."""
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return

    p = float(price)

    global _prev_price, _latest_entropy, _blocked_until
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

        # Transition counts
        n_pp = sum(1 for t in range(1, n) if syms[t - 1] == 1 and syms[t] == 1)
        n_pm = sum(1 for t in range(1, n) if syms[t - 1] == 1 and syms[t] == -1)
        n_mp = sum(1 for t in range(1, n) if syms[t - 1] == -1 and syms[t] == 1)
        n_mm = sum(1 for t in range(1, n) if syms[t - 1] == -1 and syms[t] == -1)

        # Laplace smoothing
        alpha = 0.05
        p_pp = (n_pp + alpha) / (n_pp + n_pm + 2.0 * alpha)
        p_pm = 1.0 - p_pp

        p_mp = (n_mp + alpha) / (n_mp + n_mm + 2.0 * alpha)
        p_mm = 1.0 - p_mp

        # Stationary distribution
        denom = p_pm + p_mp
        if denom > 1e-6:
            pi_plus = p_mp / denom
            pi_minus = p_pm / denom
        else:
            pi_plus = 0.5
            pi_minus = 0.5

        # Row Shannon entropies
        h_plus = 0.0
        if p_pp > 1e-6:
            h_plus -= p_pp * math.log2(p_pp)
        if p_pm > 1e-6:
            h_plus -= p_pm * math.log2(p_pm)

        h_minus = 0.0
        if p_mp > 1e-6:
            h_minus -= p_mp * math.log2(p_mp)
        if p_mm > 1e-6:
            h_minus -= p_mm * math.log2(p_mm)

        markov_entropy = pi_plus * h_plus + pi_minus * h_minus
        _latest_entropy = markov_entropy

        if markov_entropy <= MIN_MARKOV_ENTROPY:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(price, ts=None) -> None:
    """Alias for record_price()."""
    record_price(price, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if Markov transition entropy collapse has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_markov_entropy() -> float:
    """Return the most recently computed Markov transition entropy rate in bits."""
    with _lock:
        return _latest_entropy


def get_status() -> Dict[str, Any]:
    """Return a diagnostic snapshot of the Markov transition entropy guard state."""
    with _lock:
        now = time.monotonic()
        return {
            "markov_entropy": _latest_entropy,
            "sample_count": len(_symbols),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "min_entropy_threshold": MIN_MARKOV_ENTROPY,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset price state, symbol history, entropy metrics, and active blocks."""
    global _prev_price, _latest_entropy, _blocked_until
    with _lock:
        _prev_price = None
        _symbols.clear()
        _latest_entropy = 1.0
        _blocked_until = 0.0
