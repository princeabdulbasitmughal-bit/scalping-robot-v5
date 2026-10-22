"""
wave242_quote_volatility_shock_guard.py
-----------------------------------------
Guard: Microstructure Quote Volatility Shock & Flash Midpoint Jump Guard

Monitors high-frequency quote-level return volatility and sudden flash midpoint price jumps
(Andersen, Bollerslev & Diebold 2007; Barndorff-Nielsen & Shephard 2004):
    Midpoint Price:           P_{mid, t} = (P_{bid, t} + P_{ask, t}) / 2
    Quote Return (bps):       r_t = ((P_{mid, t} - P_{mid, t-1}) / P_{mid, t-1}) * 10^4
    Quote Volatility (bps):   sigma_r = sqrt( (1 / (N - 1)) * \\sum_{i=1}^N (r_i - \\bar{r})^2 )
    Standardized Shock (z):   z_t = |r_t - \\bar{r}| / max(0.20, sigma_r)

In orderly liquid markets:
    - Quote midpoint returns are tightly bound and diffusive:
      sigma_r <= 1.0 - 1.5 bps across rolling N=30 quotes, with |r_t| < 2.0 bps.

During liquidity shocks, sudden news dislocations, quote stuffing, or flash crashes:
    - Midpoint quote returns exhibit violent non-Gaussian jumps or extreme volatility clusters:
        1) Severe Quote Volatility Explosion:
           sigma_r >= MAX_QUOTE_VOLATILITY (default: 3.50 bps) over rolling N >= 15 quotes.
        2) Acute Midpoint Price Shock / Flash Jump:
           |r_t| >= MAX_ACUTE_JUMP_BPS (default: 6.00 bps) OR
           (z_t >= Z_SCORE_THRESHOLD (default: 4.50) with N >= 15).

Entering market or limit orders during quote volatility shocks guarantees extreme adverse
execution slippage, fill uncertainty, and severe mark-to-market drawdown.

When quote volatility explosion or acute price shock is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests quotes via record_quote(bid_price, ask_price, ts=None) or
  direct return via record_quote_return(return_bps, ts=None).
- Maintains rolling history of WINDOW_SIZE = 30 quote returns.
- Minimum MIN_SAMPLES = 15 quotes required for rolling volatility trip evaluation.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive prices, or crossed quotes (bid >= ask) are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_quote(bid_price, ask_price, ts=None)                                                 -> None
  record_quote_return(return_bps, ts=None)                                                     -> None
  update(bid_price, ask_price=None, ts=None)                                                   -> None   (alias)
  get_volatility_metrics()                                                                     -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 30
MIN_SAMPLES: int = 15
MAX_QUOTE_VOLATILITY: float = 3.50     # 3.50 bps rolling quote return volatility
MAX_ACUTE_JUMP_BPS: float = 6.00       # 6.00 bps single quote return flash jump
Z_SCORE_THRESHOLD: float = 4.50        # 4.50 sigma standardized price shock
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_midpoint: Optional[float] = None
_returns_history = collections.deque(maxlen=WINDOW_SIZE)  # quote returns in bps
_latest_return_bps: float = 0.0
_latest_quote_volatility: float = 0.0
_latest_z_score: float = 0.0
_blocked_until: float = 0.0


def _is_valid_positive(val: Any) -> bool:
    """Validate value is a positive finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val > 0.0


def _is_valid_numeric(val: Any) -> bool:
    """Validate value is a finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return True


def record_quote_return(
    return_bps: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest quote return directly in basis points and evaluate volatility shock.
    """
    global _latest_return_bps, _latest_quote_volatility, _latest_z_score, _blocked_until

    if not _is_valid_numeric(return_bps):
        return

    r = float(return_bps)

    with _lock:
        _latest_return_bps = r
        _returns_history.append(r)

        n = len(_returns_history)

        # Condition 1: Acute absolute flash jump
        if abs(r) >= MAX_ACUTE_JUMP_BPS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        if n >= MIN_SAMPLES:
            mean_r = sum(_returns_history) / n
            var_r = sum((x - mean_r) ** 2 for x in _returns_history) / (n - 1)
            sigma_r = math.sqrt(max(0.0, var_r))
            z_score = abs(r - mean_r) / max(0.20, sigma_r)

            _latest_quote_volatility = sigma_r
            _latest_z_score = z_score

            # Condition 2: Volatility explosion or acute z-score shock
            if sigma_r >= MAX_QUOTE_VOLATILITY or z_score >= Z_SCORE_THRESHOLD:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return
        else:
            _latest_quote_volatility = 0.0
            _latest_z_score = 0.0


def record_quote(
    bid_price: float,
    ask_price: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest bid and ask quotes, compute midpoint, and record quote return.
    """
    global _prev_midpoint

    if not _is_valid_positive(bid_price) or not _is_valid_positive(ask_price):
        return

    bp = float(bid_price)
    ap = float(ask_price)

    # Inverted or crossed quote
    if bp >= ap:
        return

    mid = (bp + ap) / 2.0

    with _lock:
        if _prev_midpoint is not None and _prev_midpoint > 0.0:
            ret_bps = ((mid - _prev_midpoint) / _prev_midpoint) * 10000.0
            _prev_midpoint = mid
            # Drop lock to record return cleanly
        else:
            _prev_midpoint = mid
            return

    record_quote_return(ret_bps, ts)


def update(
    bid_price: float,
    ask_price: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Flexible alias:
    If ask_price is provided, treats inputs as bid and ask.
    If ask_price is None, treats bid_price as return_bps.
    """
    if ask_price is not None:
        record_quote(bid_price, ask_price, ts)
    else:
        record_quote_return(bid_price, ts)


def is_entry_blocked() -> bool:
    """Check if new entries are blocked by quote volatility shock."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_volatility_metrics() -> Dict[str, float]:
    """Retrieve current quote volatility metrics."""
    with _lock:
        return {
            "latest_return_bps": _latest_return_bps,
            "quote_volatility_bps": _latest_quote_volatility,
            "z_score": _latest_z_score,
        }


def get_status() -> Dict[str, Any]:
    """Retrieve complete guard status."""
    with _lock:
        now = time.monotonic()
        blocked = now < _blocked_until
        remaining = max(0.0, _blocked_until - now) if blocked else 0.0
        return {
            "guard_name": "wave242_quote_volatility_shock_guard",
            "is_blocked": blocked,
            "blocked_seconds_remaining": remaining,
            "sample_count": len(_returns_history),
            "latest_return_bps": _latest_return_bps,
            "quote_volatility_bps": _latest_quote_volatility,
            "z_score": _latest_z_score,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "max_quote_volatility": MAX_QUOTE_VOLATILITY,
            "max_acute_jump_bps": MAX_ACUTE_JUMP_BPS,
            "z_score_threshold": Z_SCORE_THRESHOLD,
        }


def reset() -> None:
    """Reset all guard state and clear cooldowns."""
    global _prev_midpoint, _latest_return_bps, _latest_quote_volatility
    global _latest_z_score, _blocked_until

    with _lock:
        _prev_midpoint = None
        _returns_history.clear()
        _latest_return_bps = 0.0
        _latest_quote_volatility = 0.0
        _latest_z_score = 0.0
        _blocked_until = 0.0
