"""
wave254_lob_spread_dynamic_jitter_guard.py
--------------------------------------------
Guard: Order Book Bid-Ask Spread Dynamic Jitter & Bounce Guard

Monitors high-frequency spread oscillations, jump volatility, and tick jitter
(Amihud & Mendelson 1986; Huang & Stoll 1997):
    Spread in bps:           S_t = ((P_{ask, t} - P_{bid, t}) / P_{mid, t}) * 10^4
    Spread Step Delta:       \\Delta S_t = S_t - S_{t-1} (bps)
    Spread Jitter Volatility:\\sigma(\\Delta S) = sqrt( (1 / (N - 1)) * \\sum_{i=1}^N (\\Delta S_i - \\bar{\\Delta S})^2 )

Under stable continuous double-auction market conditions:
    - Quoted spreads adjust smoothly and symmetrically:
      S_t ~ 1.5 - 3.0 bps, with low dynamic jitter \\sigma(\\Delta S) <= 1.0 bps.

During predatory quote flashing, aggressive market maker flickering, or algorithmic quote battles:
    - The spread oscillates and jumps violently between tight and blown-out levels:
        1) Severe Spread Jitter Explosion:
           \\sigma(\\Delta S) >= MAX_SPREAD_JITTER (default: 2.50 bps) over rolling N >= 15 quote transitions.
        2) Acute Spread Flapping Jump:
           |\\Delta S_t| >= MAX_ACUTE_SPREAD_JUMP (default: 5.00 bps).

Attempting to enter trades during severe spread jitter guarantees toxic execution timing,
crossing wide air-pocket spreads, and immediate negative edge.

When spread jitter explosion or acute spread flapping is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests quotes via record_quote(bid_price, ask_price, ts=None) or
  direct spread via record_spread(spread_bps, ts=None).
- Maintains rolling history of WINDOW_SIZE = 25 spread step deltas.
- Minimum MIN_SAMPLES = 15 transitions required for rolling jitter evaluation.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive prices, or crossed quotes (bid >= ask) are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_quote(bid_price, ask_price, ts=None)                                                  -> None
  record_spread(spread_bps, ts=None)                                                           -> None
  update(bid_or_spread, ask_price=None, ts=None)                                                -> None   (alias)
  get_jitter_metrics()                                                                         -> dict
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
WINDOW_SIZE: int = 25
MIN_SAMPLES: int = 15
MAX_SPREAD_JITTER: float = 2.50        # 2.50 bps spread delta standard deviation
MAX_ACUTE_SPREAD_JUMP: float = 5.00    # 5.00 bps single-step spread jump
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_spread_bps: Optional[float] = None
_deltas_history = collections.deque(maxlen=WINDOW_SIZE)  # spread deltas in bps
_latest_spread_bps: float = 2.0
_latest_spread_delta: float = 0.0
_latest_jitter_volatility: float = 0.0
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


def _is_valid_non_negative(val: Any) -> bool:
    """Validate value is a non-negative finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val >= 0.0


def record_spread(
    spread_bps: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest spread in basis points directly, compute delta, and evaluate jitter.
    """
    global _prev_spread_bps, _latest_spread_bps, _latest_spread_delta
    global _latest_jitter_volatility, _blocked_until

    if not _is_valid_non_negative(spread_bps):
        return

    s = float(spread_bps)

    with _lock:
        _latest_spread_bps = s

        if _prev_spread_bps is not None:
            delta = s - _prev_spread_bps
            _prev_spread_bps = s
            _latest_spread_delta = delta
            _deltas_history.append(delta)

            # Condition 1: Acute spread flapping jump
            if abs(delta) >= MAX_ACUTE_SPREAD_JUMP:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return

            n = len(_deltas_history)
            if n >= MIN_SAMPLES:
                mu = sum(_deltas_history) / n
                var = sum((x - mu) ** 2 for x in _deltas_history) / (n - 1)
                sigma = math.sqrt(max(0.0, var))
                _latest_jitter_volatility = sigma

                # Condition 2: Severe spread jitter explosion
                if sigma >= MAX_SPREAD_JITTER:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                    return
            else:
                _latest_jitter_volatility = 0.0
        else:
            _prev_spread_bps = s
            _latest_spread_delta = 0.0
            _latest_jitter_volatility = 0.0


def record_quote(
    bid_price: float,
    ask_price: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest bid and ask quotes, compute spread in basis points, and record.
    """
    if not _is_valid_positive(bid_price) or not _is_valid_positive(ask_price):
        return

    bp = float(bid_price)
    ap = float(ask_price)

    # Inverted or crossed quote
    if bp >= ap:
        return

    mid = (bp + ap) / 2.0
    if mid <= 0.0:
        return

    spread_bps = ((ap - bp) / mid) * 10000.0
    record_spread(spread_bps, ts)


def update(
    bid_or_spread: float,
    ask_price: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Flexible alias:
    If ask_price is provided, treats inputs as bid and ask.
    If ask_price is None, treats bid_or_spread as spread_bps directly.
    """
    if ask_price is not None:
        record_quote(bid_or_spread, ask_price, ts)
    else:
        record_spread(bid_or_spread, ts)


def is_entry_blocked() -> bool:
    """Check if new entries are blocked by spread dynamic jitter."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_jitter_metrics() -> Dict[str, float]:
    """Retrieve current spread jitter metrics."""
    with _lock:
        return {
            "latest_spread_bps": _latest_spread_bps,
            "latest_spread_delta": _latest_spread_delta,
            "jitter_volatility_bps": _latest_jitter_volatility,
        }


def get_status() -> Dict[str, Any]:
    """Retrieve complete guard status."""
    with _lock:
        now = time.monotonic()
        blocked = now < _blocked_until
        remaining = max(0.0, _blocked_until - now) if blocked else 0.0
        return {
            "guard_name": "wave254_lob_spread_dynamic_jitter_guard",
            "is_blocked": blocked,
            "blocked_seconds_remaining": remaining,
            "sample_count": len(_deltas_history),
            "latest_spread_bps": _latest_spread_bps,
            "latest_spread_delta": _latest_spread_delta,
            "jitter_volatility_bps": _latest_jitter_volatility,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "max_spread_jitter": MAX_SPREAD_JITTER,
            "max_acute_spread_jump": MAX_ACUTE_SPREAD_JUMP,
        }


def reset() -> None:
    """Reset all guard state and clear cooldowns."""
    global _prev_spread_bps, _latest_spread_bps, _latest_spread_delta
    global _latest_jitter_volatility, _blocked_until

    with _lock:
        _prev_spread_bps = None
        _deltas_history.clear()
        _latest_spread_bps = 2.0
        _latest_spread_delta = 0.0
        _latest_jitter_volatility = 0.0
        _blocked_until = 0.0
