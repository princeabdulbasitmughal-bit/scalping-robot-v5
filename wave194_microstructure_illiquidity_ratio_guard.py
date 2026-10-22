"""
wave194_microstructure_illiquidity_ratio_guard.py
--------------------------------------------------
Guard: Microstructure Amihud Illiquidity Ratio & Return-to-Volume Elasticity Guard

Monitors instantaneous order book price impact and illiquidity elasticity using the Amihud (2002)
microstructure illiquidity formulation:
    ILLIQ_t = |r_t| / V_t
where:
    |r_t| = |P_t - P_{t-1}| / P_{t-1} is the absolute price return of trade t,
    V_t is the traded volume in contracts/lots (V_t > 0).

In deep, resilient, liquid double-auction markets, market depth absorbs moderate order volume with
negligible price dislocation:
    ILLIQ_t is tightly bounded near zero (< 1.0 bps per lot).

When liquidity evaporates—such as during structural book hollowing, sudden market maker quoting halts,
or predatory book-sweeping events—the return-to-volume ratio explodes:
    1) Rolling mean illiquidity:
       ILLIQ_mean >= MAX_ROLLING_ILLIQ (default: 0.0005, or 5.0 bps return per lot)
    2) Relative illiquidity shock:
       ILLIQ_t >= SPIKE_RATIO_THRESHOLD * ILLIQ_baseline (default: 3.5x baseline)
       with absolute illiquidity >= MIN_SPIKE_ILLIQ (default: 0.0002, or 2.0 bps per lot).

In this brittle regime, entering scalping positions exposes the strategy to extreme market impact,
catastrophic spread widening, and predatory slippage.

When an illiquidity condition is detected, entry orders are blocked for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade executions (price > 0.0, volume > 0.0, ts=None).
- Computes single-trade Amihud illiquidity: |P_t - P_{t-1}| / (P_{t-1} * V_t).
- Maintains a rolling window of WINDOW_SIZE = 20 trade illiquidity ratios.
- Requires at least MIN_SAMPLES = 5 trades before trip-wire evaluation.
- Checks:
    a) Rolling mean illiquidity >= MAX_ROLLING_ILLIQ (0.0005)
    b) Instantaneous spike >= SPIKE_RATIO_THRESHOLD (3.5x baseline) and >= MIN_SPIKE_ILLIQ (0.0002)
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS (45.0s).
- Thread-safe: threading.RLock() on all state mutations.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive price/volume inputs are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_trade(price, volume, ts=None)                     -> None
  update(price, volume, ts=None)                           -> None   (alias)
  get_illiq()                                              -> float
  get_rolling_illiq()                                      -> float
  get_status()                                             -> dict
  reset()                                                  -> None
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
MIN_SAMPLES: int = 5
MAX_ROLLING_ILLIQ: float = 0.0005     # 5.0 bps return per lot
SPIKE_RATIO_THRESHOLD: float = 3.5    # 3.5x baseline rolling average
MIN_SPIKE_ILLIQ: float = 0.0002       # 2.0 bps per lot minimum to trigger spike
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_last_price: Optional[float] = None
_illiq_history = collections.deque(maxlen=WINDOW_SIZE)
_latest_illiq: float = 0.0
_latest_rolling_illiq: float = 0.0
_blocked_until: float = 0.0


def _is_valid_positive_number(val: Any) -> bool:
    """Validate that val is a real positive finite numeric value."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val > 0.0


def record_trade(price: float, volume: float, ts: Optional[float] = None) -> None:
    """
    Ingest a new trade execution (price, volume) and evaluate illiquidity metrics.
    """
    global _last_price, _latest_illiq, _latest_rolling_illiq, _blocked_until

    if not _is_valid_positive_number(price) or not _is_valid_positive_number(volume):
        return

    with _lock:
        now = time.monotonic() if ts is None else float(ts)

        if _last_price is None:
            _last_price = float(price)
            return

        prev_price = _last_price
        _last_price = float(price)

        # Amihud return-to-volume ratio
        ret = abs(price - prev_price) / prev_price
        curr_illiq = ret / float(volume)
        _latest_illiq = curr_illiq

        # Calculate baseline from existing history if available
        baseline_illiq = (
            sum(_illiq_history) / len(_illiq_history)
            if len(_illiq_history) >= MIN_SAMPLES
            else None
        )

        _illiq_history.append(curr_illiq)

        if len(_illiq_history) < MIN_SAMPLES:
            return

        rolling_mean = sum(_illiq_history) / len(_illiq_history)
        _latest_rolling_illiq = rolling_mean

        # Condition 1: Absolute rolling mean illiquidity breach
        if rolling_mean >= MAX_ROLLING_ILLIQ:
            _blocked_until = max(_blocked_until, now + COOLDOWN_SECONDS)
            return

        # Condition 2: Sudden illiquidity spike relative to established baseline
        if baseline_illiq is not None and baseline_illiq > 1e-9:
            spike_ratio = curr_illiq / baseline_illiq
            if spike_ratio >= SPIKE_RATIO_THRESHOLD and curr_illiq >= MIN_SPIKE_ILLIQ:
                _blocked_until = max(_blocked_until, now + COOLDOWN_SECONDS)
                return


def update(price: float, volume: float, ts: Optional[float] = None) -> None:
    """Alias for record_trade()."""
    record_trade(price, volume, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to illiquidity risk."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_illiq() -> float:
    """Return the single most recent trade Amihud illiquidity ratio."""
    with _lock:
        return _latest_illiq


def get_rolling_illiq() -> float:
    """Return the latest rolling mean Amihud illiquidity ratio."""
    with _lock:
        return _latest_rolling_illiq


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the illiquidity ratio guard."""
    with _lock:
        now = time.monotonic()
        return {
            "latest_illiq": _latest_illiq,
            "rolling_illiq": _latest_rolling_illiq,
            "sample_count": len(_illiq_history),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "max_rolling_illiq": MAX_ROLLING_ILLIQ,
            "spike_ratio_threshold": SPIKE_RATIO_THRESHOLD,
            "min_spike_illiq": MIN_SPIKE_ILLIQ,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset guard state, trade history, and block timers."""
    global _last_price, _latest_illiq, _latest_rolling_illiq, _blocked_until
    with _lock:
        _last_price = None
        _illiq_history.clear()
        _latest_illiq = 0.0
        _latest_rolling_illiq = 0.0
        _blocked_until = 0.0
