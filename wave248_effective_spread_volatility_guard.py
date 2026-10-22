"""
wave248_effective_spread_volatility_guard.py
----------------------------------------------
Guard: Microstructure Effective Spread Volatility & Liquidity Friction Guard

Monitors empirical effective spread dispersion and liquidity friction volatility
(Roll 1984; Corwin & Schultz 2012; Hasbrouck 2007):
    Midpoint Price:           P_{mid} = (P_{bid} + P_{ask}) / 2
    Effective Spread (bps):   S_{eff, i} = (2 * |P_{trade, i} - P_{mid}| / P_{mid}) * 10^4
    Mean Spread:              \\bar{S}_{eff} = (1 / N) * \\sum_{i=1}^N S_{eff, i}
    Spread Volatility (bps):  \\sigma(S_{eff}) = sqrt( (1 / (N - 1)) * \\sum_{i=1}^N (S_{eff, i} - \\bar{S}_{eff})^2 )

Under stable continuous double-auction liquidity provision:
    - Effective spreads cluster tightly around the quoted spread:
      \\bar{S}_{eff} ~ 1.5 - 2.5 bps, with low dispersion \\sigma(S_{eff}) <= 1.0 bps.

During liquidity fragmentation, predatory sweep execution, or market maker inventory stress:
    - Fills occur at erratic, wildly dispersing price distances from midpoint:
        1) Severe Effective Spread Volatility:
           \\sigma(S_{eff}) >= MAX_SPREAD_VOLATILITY (default: 2.50 bps) over rolling N >= 12 trades.
        2) Acute Liquidity Friction Spurt:
           Single trade effective spread S_{eff} >= MAX_SINGLE_SPREAD (default: 6.00 bps).

Executing orders during high spread volatility guarantees unpredictable execution cost,
severe slippage tail risk, and aggressive negative selection.

When spread volatility explosion or acute friction spurt is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trades via record_trade(trade_price, bid_price, ask_price, ts=None) or
  direct spread via record_effective_spread(spread_bps, ts=None).
- Maintains rolling history of WINDOW_SIZE = 20 trade effective spreads.
- Minimum MIN_SAMPLES = 12 trades required for rolling volatility trip evaluation.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive prices, or crossed quotes (bid >= ask) are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade(trade_price, bid_price, ask_price, ts=None)                                     -> None
  record_effective_spread(spread_bps, ts=None)                                                 -> None
  update(trade_price_or_spread, bid_price=None, ask_price=None, ts=None)                       -> None   (alias)
  get_spread_volatility_metrics()                                                              -> dict
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
WINDOW_SIZE: int = 20
MIN_SAMPLES: int = 12
MAX_SPREAD_VOLATILITY: float = 2.50    # 2.50 bps effective spread standard deviation
MAX_SINGLE_SPREAD: float = 6.00        # 6.00 bps single trade effective spread ceiling
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_spreads_history = collections.deque(maxlen=WINDOW_SIZE)  # effective spreads in bps
_latest_spread_bps: float = 0.0
_latest_mean_spread_bps: float = 0.0
_latest_spread_volatility: float = 0.0
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


def record_effective_spread(
    spread_bps: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest effective spread in basis points directly.
    """
    global _latest_spread_bps, _latest_mean_spread_bps, _latest_spread_volatility, _blocked_until

    if not _is_valid_non_negative(spread_bps):
        return

    s = float(spread_bps)

    with _lock:
        _latest_spread_bps = s
        _spreads_history.append(s)

        # Condition 1: Acute single trade liquidity friction spurt
        if s >= MAX_SINGLE_SPREAD:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        n = len(_spreads_history)
        if n >= MIN_SAMPLES:
            mean_s = sum(_spreads_history) / n
            var_s = sum((x - mean_s) ** 2 for x in _spreads_history) / (n - 1)
            sigma_s = math.sqrt(max(0.0, var_s))

            _latest_mean_spread_bps = mean_s
            _latest_spread_volatility = sigma_s

            # Condition 2: Severe effective spread volatility
            if sigma_s >= MAX_SPREAD_VOLATILITY:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return
        else:
            _latest_mean_spread_bps = sum(_spreads_history) / n if n > 0 else 0.0
            _latest_spread_volatility = 0.0


def record_trade(
    trade_price: float,
    bid_price: float,
    ask_price: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest trade price and prevailing bid/ask, compute effective spread, and record.
    """
    if not (
        _is_valid_positive(trade_price)
        and _is_valid_positive(bid_price)
        and _is_valid_positive(ask_price)
    ):
        return

    tp = float(trade_price)
    bp = float(bid_price)
    ap = float(ask_price)

    # Inverted or crossed market guard
    if bp >= ap:
        return

    mid = (bp + ap) / 2.0
    if mid <= 0.0:
        return

    s_eff_bps = (2.0 * abs(tp - mid) / mid) * 10000.0
    record_effective_spread(s_eff_bps, ts)


def update(
    trade_price_or_spread: float,
    bid_price: Optional[float] = None,
    ask_price: Optional[float] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Flexible alias:
    If bid_price and ask_price are provided, computes effective spread from trade and quote.
    If only trade_price_or_spread is provided, treats it as spread_bps directly.
    """
    if bid_price is not None and ask_price is not None:
        record_trade(trade_price_or_spread, bid_price, ask_price, ts)
    else:
        record_effective_spread(trade_price_or_spread, ts)


def is_entry_blocked() -> bool:
    """Check if new entries are blocked by effective spread volatility."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_spread_volatility_metrics() -> Dict[str, float]:
    """Retrieve current spread volatility metrics."""
    with _lock:
        return {
            "latest_spread_bps": _latest_spread_bps,
            "mean_spread_bps": _latest_mean_spread_bps,
            "spread_volatility_bps": _latest_spread_volatility,
        }


def get_status() -> Dict[str, Any]:
    """Retrieve complete guard status."""
    with _lock:
        now = time.monotonic()
        blocked = now < _blocked_until
        remaining = max(0.0, _blocked_until - now) if blocked else 0.0
        return {
            "guard_name": "wave248_effective_spread_volatility_guard",
            "is_blocked": blocked,
            "blocked_seconds_remaining": remaining,
            "sample_count": len(_spreads_history),
            "latest_spread_bps": _latest_spread_bps,
            "mean_spread_bps": _latest_mean_spread_bps,
            "spread_volatility_bps": _latest_spread_volatility,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "max_spread_volatility": MAX_SPREAD_VOLATILITY,
            "max_single_spread": MAX_SINGLE_SPREAD,
        }


def reset() -> None:
    """Reset all guard state and clear cooldowns."""
    global _latest_spread_bps, _latest_mean_spread_bps, _latest_spread_volatility, _blocked_until

    with _lock:
        _spreads_history.clear()
        _latest_spread_bps = 0.0
        _latest_mean_spread_bps = 0.0
        _latest_spread_volatility = 0.0
        _blocked_until = 0.0
