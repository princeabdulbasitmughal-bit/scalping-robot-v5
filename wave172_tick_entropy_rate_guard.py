"""
wave172_tick_entropy_rate_guard.py
----------------------------------
Guard: First-Order Conditional Tick Entropy Rate Guard

Measures algorithmic predictability and market structure determinism via the first-order
conditional Shannon entropy rate of directional tick transitions:
    s_t = sign(P_t - P_{t-1}) in {+1, -1}
    h = P(+) * H(S_t | S_{t-1} = +) + P(-) * H(S_t | S_{t-1} = -)  [in bits per tick]

Under healthy, stochastic two-sided market liquidity, tick direction transitions are
diffusive and unpredictable (entropy rate h ~ 1.0 bit).
When predatory institutional algorithms (e.g. TWAP/POV order slicers) dominate the order flow
or latency arbitrage engines steamroll the book, price changes become rigidly deterministic
(e.g. strictly monotonic streaks or rigid ping-pong cycles).
In this deterministic regime, the conditional entropy rate collapses (h <= MIN_ENTROPY_RATE,
default: 0.40 bits).
When entropy rate collapses, scalping spread-capture edge evaporates, triggering an entry
block for COOLDOWN_SECONDS (default: 45.0s) until stochastic market behavior returns.

Logic:
- Records price ticks and computes directional signs (+1, -1; ignores 0/flat ticks).
- Maintains rolling window (WINDOW_SIZE = 30 symbols).
- Requires at least MIN_SAMPLES = 15 symbols before evaluation.
- Calculates empirical transition probabilities P(j|i) and conditional entropy rate h.
- If h <= MIN_ENTROPY_RATE (0.40 bits):
    blocks entries for COOLDOWN_SECONDS (45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive prices are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_price(price, ts=None)                             -> None
  update(price, ts=None)                                   -> None   (alias)
  get_entropy_rate()                                       -> float
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
MIN_ENTROPY_RATE: float = 0.40     # Entropy rate <= 0.40 bits indicates deterministic algo steamrolling
WINDOW_SIZE: int = 30              # Rolling window of directional tick symbols
MIN_SAMPLES: int = 15              # Minimum symbols required before evaluation
COOLDOWN_SECONDS: float = 45.0     # Block duration in seconds on entropy collapse


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_price: Optional[float] = None
_symbols: Deque[int] = collections.deque(maxlen=WINDOW_SIZE)
_latest_entropy_rate: float = 1.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_price(price, ts=None) -> None:
    """Record an incoming price tick and calculate first-order conditional entropy rate."""
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return

    p = float(price)

    global _prev_price, _latest_entropy_rate, _blocked_until
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

        # Transition counts
        syms = list(_symbols)
        n = len(syms)

        n_pp = sum(1 for t in range(1, n) if syms[t - 1] == 1 and syms[t] == 1)
        n_pm = sum(1 for t in range(1, n) if syms[t - 1] == 1 and syms[t] == -1)
        n_mp = sum(1 for t in range(1, n) if syms[t - 1] == -1 and syms[t] == 1)
        n_mm = sum(1 for t in range(1, n) if syms[t - 1] == -1 and syms[t] == -1)

        n_plus = n_pp + n_pm
        n_minus = n_mp + n_mm
        total_transitions = n - 1

        if total_transitions <= 0:
            return

        h = 0.0

        # Conditional entropy from state '+'
        if n_plus > 0:
            p_plus = n_plus / total_transitions
            p_pp = n_pp / n_plus
            p_pm = n_pm / n_plus
            h_plus = 0.0
            if p_pp > 1e-9:
                h_plus -= p_pp * math.log2(p_pp)
            if p_pm > 1e-9:
                h_plus -= p_pm * math.log2(p_pm)
            h += p_plus * h_plus

        # Conditional entropy from state '-'
        if n_minus > 0:
            p_minus = n_minus / total_transitions
            p_mp = n_mp / n_minus
            p_mm = n_mm / n_minus
            h_minus = 0.0
            if p_mp > 1e-9:
                h_minus -= p_mp * math.log2(p_mp)
            if p_mm > 1e-9:
                h_minus -= p_mm * math.log2(p_mm)
            h += p_minus * h_minus

        _latest_entropy_rate = h

        if h <= MIN_ENTROPY_RATE:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(price, ts=None) -> None:
    """Alias for record_price()."""
    record_price(price, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if entropy rate collapse has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_entropy_rate() -> float:
    """Return the most recently calculated first-order conditional entropy rate (bits)."""
    with _lock:
        return _latest_entropy_rate


def reset() -> None:
    """Reset price state, symbol deque, latest entropy, and active cooldown."""
    global _prev_price, _latest_entropy_rate, _blocked_until
    with _lock:
        _prev_price = None
        _symbols.clear()
        _latest_entropy_rate = 1.0
        _blocked_until = 0.0
