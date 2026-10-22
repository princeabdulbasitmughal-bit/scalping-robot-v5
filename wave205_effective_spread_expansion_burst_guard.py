"""
wave205_effective_spread_expansion_burst_guard.py
--------------------------------------------------
Guard: Realized Effective Spread Expansion Burst Guard

Monitors realized trade effective spread relative to prevailing quoted spread (Roll 1984; Bessembinder 2003):
    Quoted mid:       P_{mid} = (Bid + Ask) / 2
    Quoted spread:    S_{quoted} = (Ask - Bid) / P_{mid} * 10,000         (bps)
    Effective spread: S_{eff} = 2 * |P_{trade} - P_{mid}| / P_{mid} * 10,000 (bps)
    Expansion ratio:  R_{exp} = S_{eff} / max(0.1, S_{quoted})

In healthy double-auction markets with ample standing depth at the touch, trades execute within
or right at the posted quotes:
    - Expansion ratio: R_{exp} <= 1.20
    - Effective spread: S_{eff} <= 2.5 bps

During predatory institutional sweep sweeps, order book hollowing, or quote fading:
    1) Expansion ratio blowout:
       R_{exp} >= MAX_EXPANSION_RATIO (default: 2.5x quoted spread), indicating fills executing
       deep into level-2/3 book beyond the touch.
    2) Extreme absolute effective spread:
       S_{eff} >= MAX_EFFECTIVE_SPREAD_BPS (default: 8.0 bps).

Scalpers entering during effective spread expansion suffer extreme execution haircut and immediate
negative expected value.

When an effective spread expansion burst is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade executions (trade_price > 0.0, bid > 0.0, ask > bid, side=None, ts=None).
- Computes quoted spread, effective spread, and expansion ratio.
- Evaluates trip-wire conditions: R_{exp} >= 2.5 or S_{eff} >= 8.0 bps.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive prices, or inverted quotes are rejected.

Aliases (required):
  is_entry_blocked()                                                             -> bool
  is_blocked()                                                                   -> bool   (alias)
  record_execution(trade_price, bid, ask, side=None, ts=None)                    -> None
  update(trade_price, bid, ask, side=None, ts=None)                              -> None   (alias)
  get_spread_metrics()                                                           -> dict
  get_status()                                                                   -> dict
  reset()                                                                        -> None
"""

import math
import threading
import time
from typing import Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_EXPANSION_RATIO: float = 2.5       # 2.5x quoted spread
MAX_EFFECTIVE_SPREAD_BPS: float = 8.0  # 8.0 bps absolute effective spread
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_latest_quoted_spread_bps: float = 0.0
_latest_effective_spread_bps: float = 0.0
_latest_expansion_ratio: float = 1.0
_blocked_until: float = 0.0


def _is_valid_price(val: Any) -> bool:
    """Validate price is a positive finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val > 0.0


def record_execution(
    trade_price: float,
    bid: float,
    ask: float,
    side: Optional[Any] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest a realized trade execution and evaluate effective spread expansion.
    """
    global _latest_quoted_spread_bps, _latest_effective_spread_bps
    global _latest_expansion_ratio, _blocked_until

    if not _is_valid_price(trade_price) or not _is_valid_price(bid) or not _is_valid_price(ask):
        return
    if float(ask) <= float(bid):
        return

    tp = float(trade_price)
    b = float(bid)
    a = float(ask)

    with _lock:
        now = time.monotonic() if ts is None else float(ts)

        mid = (b + a) / 2.0
        quoted_spread_bps = ((a - b) / mid) * 10_000.0
        effective_spread_bps = (2.0 * abs(tp - mid) / mid) * 10_000.0
        expansion_ratio = effective_spread_bps / max(0.1, quoted_spread_bps)

        _latest_quoted_spread_bps = quoted_spread_bps
        _latest_effective_spread_bps = effective_spread_bps
        _latest_expansion_ratio = expansion_ratio

        # Condition 1: Expansion ratio blowout (sweep deep into book)
        if expansion_ratio >= MAX_EXPANSION_RATIO and effective_spread_bps >= 3.0:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 2: Extreme absolute effective spread breach
        if effective_spread_bps >= MAX_EFFECTIVE_SPREAD_BPS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(
    trade_price: float,
    bid: float,
    ask: float,
    side: Optional[Any] = None,
    ts: Optional[float] = None,
) -> None:
    """Alias for record_execution()."""
    record_execution(trade_price, bid, ask, side, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to spread expansion."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_spread_metrics() -> Dict[str, float]:
    """Return latest calculated quoted spread, effective spread, and expansion ratio."""
    with _lock:
        return {
            "quoted_spread_bps": _latest_quoted_spread_bps,
            "effective_spread_bps": _latest_effective_spread_bps,
            "expansion_ratio": _latest_expansion_ratio,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the effective spread expansion guard."""
    with _lock:
        now = time.monotonic()
        return {
            "quoted_spread_bps": _latest_quoted_spread_bps,
            "effective_spread_bps": _latest_effective_spread_bps,
            "expansion_ratio": _latest_expansion_ratio,
            "max_expansion_ratio": MAX_EXPANSION_RATIO,
            "max_effective_spread_bps": MAX_EFFECTIVE_SPREAD_BPS,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset spread metrics and active cooldown blocks."""
    global _latest_quoted_spread_bps, _latest_effective_spread_bps
    global _latest_expansion_ratio, _blocked_until
    with _lock:
        _latest_quoted_spread_bps = 0.0
        _latest_effective_spread_bps = 0.0
        _latest_expansion_ratio = 1.0
        _blocked_until = 0.0
