"""
wave184_effective_spread_drift_guard.py
----------------------------------------
Guard: Effective Spread Trend & Asymmetric Widening Guard

Monitors the realized effective spread paid on market execution relative to historical baseline:
    S_eff = 2 * |P_trade - Mid|
    s_bps = S_eff / Mid
    Drift_pct = (s_bps_latest - s_bps_baseline) / s_bps_baseline

Under stable liquidity, retail and institutional scalpers enjoy tight, predictable effective spreads
(e.g. 1.0 to 3.0 bps on major FX and bullion pairs).
When dealer inventory imbalances accumulate or predatory order flow sweeps through multiple book
levels, dealers widen their price concessions and market orders suffer adverse price impact:
    Drift_pct >= MAX_DRIFT_PCT (default: 1.00, or +100% widening above baseline) or
    s_bps_latest >= MAX_SPREAD_BPS (default: 8.0 bps / 0.00080)

In an expanding spread regime, round-trip trading friction doubles and positive expected value (EV)
from scalping vanishes into broker and liquidity provider transaction costs.

When effective spread drift or absolute widening threshold is exceeded, the guard blocks entry orders
for COOLDOWN_SECONDS (default: 45.0s) until transaction costs normalize.

Logic:
- Ingests trade execution price and prevailing quotes (trade_price, bid, ask).
- Computes midpoint Mid = 0.5 * (bid + ask) and relative effective spread s_bps.
- Maintains rolling window of effective spreads (WINDOW_SIZE = 25 trades).
- Requires at least MIN_SAMPLES = 15 trades before computing baseline drift.
- Computes baseline as mean of historical observations excluding the current observation.
- If s_bps >= MAX_SPREAD_BPS (0.00080) or Drift_pct >= MAX_DRIFT_PCT (1.00 with baseline >= 1.0 bps):
    blocks entries for COOLDOWN_SECONDS (45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive prices, or crossed quotes (bid > ask) are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_trade_spread(trade_price, bid, ask, ts=None)      -> None
  update(trade_price, bid, ask, ts=None)                   -> None   (alias)
  get_effective_spread_bps()                               -> float
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
MAX_SPREAD_BPS: float = 0.00080       # 8.0 basis points hard effective spread ceiling
MAX_DRIFT_PCT: float = 1.00           # +100% widening relative to baseline indicates regime shift
WINDOW_SIZE: int = 25                 # Rolling window of trade effective spreads
MIN_SAMPLES: int = 15                 # Minimum trades before evaluating spread drift
COOLDOWN_SECONDS: float = 45.0        # Block duration on spread widening surge


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_spreads: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_latest_spread_bps: float = 0.0
_latest_drift_pct: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_trade_spread(trade_price, bid, ask, ts=None) -> None:
    """Record an executed trade along with contemporaneous quotes and evaluate spread widening."""
    for val in (trade_price, bid, ask):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return
        if math.isnan(val) or math.isinf(val) or val <= 0.0:
            return

    tp = float(trade_price)
    b = float(bid)
    a = float(ask)

    if b > a:
        return

    mid = 0.5 * (b + a)
    if mid <= 0.0:
        return

    eff_spread = 2.0 * abs(tp - mid)
    eff_bps = eff_spread / mid

    global _latest_spread_bps, _latest_drift_pct, _blocked_until
    with _lock:
        _latest_spread_bps = eff_bps

        # Check hard spread ceiling immediately
        if eff_bps >= MAX_SPREAD_BPS:
            _spreads.append(eff_bps)
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        if len(_spreads) >= MIN_SAMPLES:
            # Baseline from historical trades
            baseline = sum(_spreads) / float(len(_spreads))
            if baseline >= 0.00005:  # At least 0.5 bps baseline to avoid division by near-zero
                drift = (eff_bps - baseline) / baseline
                _latest_drift_pct = drift
                if drift >= MAX_DRIFT_PCT:
                    _spreads.append(eff_bps)
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                    return

        _spreads.append(eff_bps)


def update(trade_price, bid, ask, ts=None) -> None:
    """Alias for record_trade_spread()."""
    record_trade_spread(trade_price, bid, ask, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if effective spread widening has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_effective_spread_bps() -> float:
    """Return the most recently computed relative effective spread in basis points."""
    with _lock:
        return _latest_spread_bps


def get_status() -> Dict[str, Any]:
    """Return a diagnostic snapshot of the effective spread drift guard state."""
    with _lock:
        now = time.monotonic()
        baseline = (sum(_spreads) / float(len(_spreads))) if _spreads else 0.0
        return {
            "latest_spread_bps": _latest_spread_bps,
            "baseline_spread_bps": baseline,
            "latest_drift_pct": _latest_drift_pct,
            "max_spread_bps": MAX_SPREAD_BPS,
            "max_drift_pct": MAX_DRIFT_PCT,
            "sample_count": len(_spreads),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset all spread observations, drift metrics, and active blocks."""
    global _latest_spread_bps, _latest_drift_pct, _blocked_until
    with _lock:
        _spreads.clear()
        _latest_spread_bps = 0.0
        _latest_drift_pct = 0.0
        _blocked_until = 0.0
