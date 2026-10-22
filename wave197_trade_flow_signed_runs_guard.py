"""
wave197_trade_flow_signed_runs_guard.py
----------------------------------------
Guard: Trade Flow Directional Runs Persistence (Wald-Wolfowitz) Guard

Monitors directional order flow clustering and institutional book sweeps using the non-parametric
Wald-Wolfowitz (1940) Runs Test on signed trade executions:
    s_i in {-1, +1}   (+1 = buy-initiated, -1 = sell-initiated)

Let N = N_+ + N_- be the number of observed trades in rolling window (WINDOW_SIZE = 25).
A "run" R is defined as a maximal non-empty contiguous subsequence of identical signs.
Under the null hypothesis of uncoordinated, independent two-sided random order flow:
    E[R] = 1 + (2 * N_+ * N_-) / N
    Var(R) = [2 * N_+ * N_- * (2 * N_+ * N_- - N)] / [N^2 * (N - 1)]
    Z = (R - E[R]) / sqrt(Var(R))

In healthy balanced trading, trades alternate frequently between buyer and seller initiation:
    - Runs Z-score is near zero: -1.50 < Z < +1.50
    - Consecutive one-sided streaks are short (<= 4 trades)

During predatory institutional execution—such as aggressive TWAP/VWAP sweeps, hidden iceberg
absorption, or unilateral market clearing—directional persistence becomes extreme:
    1) Strongly negative Wald-Wolfowitz Z-score:
       Z <= MIN_RUNS_ZSCORE (default: -2.33, p < 0.01 persistence)
    2) Extended contiguous directional run:
       Consecutive identical trade streak >= MAX_CONSECUTIVE_RUN (default: 8 trades).

Entering counter-trend scalping positions during these prolonged non-random sweeps leads to
immediate adverse selection and severe stop-out cascades.

When directional persistence breaches safety limits, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trades via record_trade(price=None, side=None, ts=None).
- Determines trade direction (+1 for buy, -1 for sell).
- Maintains a rolling window of WINDOW_SIZE = 25 signed trades.
- Tracks consecutive identical trade streak length.
- Requires at least MIN_SAMPLES = 12 trades before runs Z-score evaluation.
- Evaluates Z-score and consecutive streak length.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: invalid, non-numeric, or ambiguous inputs are safely handled/rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_trade(price=None, side=None, ts=None)             -> None
  update(price=None, side=None, ts=None)                   -> None   (alias)
  get_runs_zscore()                                        -> float
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
WINDOW_SIZE: int = 25
MIN_SAMPLES: int = 12
MIN_RUNS_ZSCORE: float = -2.33        # p < 0.01 persistence threshold
MAX_CONSECUTIVE_RUN: int = 8          # 8 trades in a row in same direction
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_signs = collections.deque(maxlen=WINDOW_SIZE)
_last_price: Optional[float] = None
_last_sign: Optional[int] = None
_consecutive_run: int = 0
_latest_zscore: float = 0.0
_latest_runs_count: int = 0
_blocked_until: float = 0.0


def _parse_sign(price: Any, side: Any) -> Optional[int]:
    """Parse trade direction to +1 (buy) or -1 (sell)."""
    global _last_price, _last_sign

    # Check side parameter first
    if side is not None:
        if isinstance(side, bool):
            return None
        if isinstance(side, (int, float)):
            if side > 0:
                return 1
            elif side < 0:
                return -1
            return None
        if isinstance(side, str):
            s = side.strip().lower()
            if s in ("buy", "b", "1", "+1", "long"):
                return 1
            if s in ("sell", "s", "-1", "short"):
                return -1
        return None

    # Fallback to tick rule on price
    if price is not None:
        if isinstance(price, bool):
            return None
        if not isinstance(price, (int, float)):
            return None
        if math.isnan(price) or math.isinf(price) or price <= 0.0:
            return None

        p = float(price)
        if _last_price is None:
            _last_price = p
            return None

        diff = p - _last_price
        _last_price = p

        if diff > 1e-9:
            return 1
        elif diff < -1e-9:
            return -1
        else:
            # Tick rule: identical price inherits previous tick sign
            return _last_sign

    return None


def record_trade(
    price: Optional[float] = None,
    side: Optional[Any] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest a new trade execution, update signed runs history, and test persistence.
    """
    global _last_sign, _consecutive_run, _latest_zscore, _latest_runs_count, _blocked_until

    sign = _parse_sign(price, side)
    if sign is None:
        return

    with _lock:
        now = time.monotonic() if ts is None else float(ts)
        _last_sign = sign
        _signs.append(sign)

        # Update contiguous run length
        if len(_signs) >= 2 and _signs[-1] == _signs[-2]:
            _consecutive_run += 1
        else:
            _consecutive_run = 1

        # Check Condition 1: Consecutive streak threshold
        if _consecutive_run >= MAX_CONSECUTIVE_RUN:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        n = len(_signs)
        if n < MIN_SAMPLES:
            return

        # Calculate Wald-Wolfowitz runs statistics
        n_pos = sum(1 for s in _signs if s > 0)
        n_neg = n - n_pos

        # If completely one-sided over N >= MIN_SAMPLES, block immediately
        if n_pos == 0 or n_neg == 0:
            _latest_zscore = -9.99
            _latest_runs_count = 1
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Count total runs in current window
        runs = 1
        for i in range(1, n):
            if _signs[i] != _signs[i - 1]:
                runs += 1

        _latest_runs_count = runs

        expected_runs = 1.0 + (2.0 * n_pos * n_neg) / float(n)
        var_numerator = 2.0 * n_pos * n_neg * (2.0 * n_pos * n_neg - n)
        var_denominator = float(n * n * (n - 1))
        var_runs = var_numerator / var_denominator

        if var_runs > 1e-9:
            z_score = (float(runs) - expected_runs) / math.sqrt(var_runs)
        else:
            z_score = 0.0

        _latest_zscore = z_score

        # Check Condition 2: Highly significant negative runs Z-score (clustering)
        if z_score <= MIN_RUNS_ZSCORE:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(
    price: Optional[float] = None,
    side: Optional[Any] = None,
    ts: Optional[float] = None,
) -> None:
    """Alias for record_trade()."""
    record_trade(price, side, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to trade runs persistence."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_runs_zscore() -> float:
    """Return the most recently computed Wald-Wolfowitz runs Z-score."""
    with _lock:
        return _latest_zscore


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the trade flow runs persistence guard."""
    with _lock:
        now = time.monotonic()
        return {
            "z_score": _latest_zscore,
            "runs_count": _latest_runs_count,
            "consecutive_run": _consecutive_run,
            "sample_count": len(_signs),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "min_zscore_threshold": MIN_RUNS_ZSCORE,
            "max_consecutive_run": MAX_CONSECUTIVE_RUN,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset signed trade history, runs metrics, and active blocks."""
    global _last_price, _last_sign, _consecutive_run, _latest_zscore, _latest_runs_count, _blocked_until
    with _lock:
        _signs.clear()
        _last_price = None
        _last_sign = None
        _consecutive_run = 0
        _latest_zscore = 0.0
        _latest_runs_count = 0
        _blocked_until = 0.0
