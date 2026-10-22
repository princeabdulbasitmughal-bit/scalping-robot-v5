"""
wave195_execution_slippage_dispersion_guard.py
-----------------------------------------------
Guard: Execution Slippage Dispersion, Adverse Mean & Heavy-Tail Kurtosis Guard

Monitors realized trade execution quality and market impact by evaluating the statistical
distribution of recent fill slippages:
    For BUY:   s_i = (P_exec,i - P_expected,i) / P_expected,i * 10,000 (bps)
    For SELL:  s_i = (P_expected,i - P_exec,i) / P_expected,i * 10,000 (bps)
where positive s_i represents adverse (unfavorable) slippage and negative s_i represents
price improvement.

In stable execution environments with transparent matching and healthy book depth, fill prices
closely track expected quote prices:
    - Mean adverse slippage: mu_s < 1.0 bps
    - Slippage dispersion (std dev): sigma_s < 1.5 bps
    - Slippage kurtosis: Kurt_s < 4.0

During predatory book conditions—such as toxic quote fading, latency arbitrage, or high-frequency
sweep fills—the distribution of slippage deteriorates sharply:
    1) Severe adverse mean slippage:
       mu_s >= MAX_MEAN_SLIPPAGE_BPS (default: 3.0 bps)
    2) High execution dispersion / volatility:
       sigma_s >= MAX_SLIPPAGE_STD_BPS (default: 2.5 bps)
    3) Leptokurtic heavy-tail execution shocks:
       Kurt_s >= MAX_SLIPPAGE_KURTOSIS (default: 5.0) with at least one severe fill (>= 3.0 bps).

When anomalous execution slippage is detected, the guard blocks new trade entries for
COOLDOWN_SECONDS (default: 45.0s) to safeguard the strategy from ongoing execution bleed.

Logic:
- Ingests executed orders (expected_price > 0.0, exec_price > 0.0, side in ['buy', 'sell'], ts=None).
- Computes signed adverse slippage in basis points.
- Maintains a rolling window of WINDOW_SIZE = 20 execution records.
- Requires at least MIN_SAMPLES = 6 fills before statistical trip-wire evaluation.
- Calculates sample mean (mu_s), sample standard deviation (sigma_s), and standardized 4th moment (kurtosis).
- Blocks entries for COOLDOWN_SECONDS (45.0s) if any threshold is breached.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive prices, or invalid sides are rejected.

Aliases (required):
  is_entry_blocked()                                                 -> bool
  is_blocked()                                                       -> bool   (alias)
  record_execution(expected_price, exec_price, side, ts=None)        -> None
  update(expected_price, exec_price, side, ts=None)                  -> None   (alias)
  get_slippage_stats()                                               -> dict
  get_status()                                                       -> dict
  reset()                                                            -> None
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
MIN_SAMPLES: int = 6
MIN_KURTOSIS_SAMPLES: int = 8
MAX_MEAN_SLIPPAGE_BPS: float = 3.0     # 3.0 bps average adverse fill
MAX_SLIPPAGE_STD_BPS: float = 2.5      # 2.5 bps standard deviation dispersion
MAX_SLIPPAGE_KURTOSIS: float = 5.0     # 5.0 standardized kurtosis (fat tails)
MIN_TAIL_SHOCK_BPS: float = 3.0        # required worst-fill shock for kurtosis trip
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_slippage_history = collections.deque(maxlen=WINDOW_SIZE)
_latest_mean: float = 0.0
_latest_std: float = 0.0
_latest_kurtosis: float = 0.0
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
    expected_price: float,
    exec_price: float,
    side: str,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest a completed execution fill and evaluate slippage dispersion metrics.
    """
    global _latest_mean, _latest_std, _latest_kurtosis, _blocked_until

    if not _is_valid_price(expected_price) or not _is_valid_price(exec_price):
        return
    if not isinstance(side, str):
        return

    side_norm = side.strip().lower()
    if side_norm not in ("buy", "sell"):
        return

    exp_p = float(expected_price)
    exe_p = float(exec_price)

    # Adverse slippage calculation in basis points:
    # BUY: higher fill is adverse (exe_p - exp_p)
    # SELL: lower fill is adverse (exp_p - exe_p)
    if side_norm == "buy":
        adverse_slippage_bps = ((exe_p - exp_p) / exp_p) * 10_000.0
    else:
        adverse_slippage_bps = ((exp_p - exe_p) / exp_p) * 10_000.0

    with _lock:
        now = time.monotonic() if ts is None else float(ts)
        _slippage_history.append(adverse_slippage_bps)

        n = len(_slippage_history)
        if n < MIN_SAMPLES:
            return

        # Sample Mean
        mean_val = sum(_slippage_history) / n
        _latest_mean = mean_val

        # Sample Variance and Standard Deviation
        variance = sum((x - mean_val) ** 2 for x in _slippage_history) / (n - 1)
        std_val = math.sqrt(variance)
        _latest_std = std_val

        # Heavy tail kurtosis evaluation
        if n >= MIN_KURTOSIS_SAMPLES and std_val > 1e-6:
            m4 = sum((x - mean_val) ** 4 for x in _slippage_history) / n
            kurtosis = m4 / (std_val ** 4)
            _latest_kurtosis = kurtosis
        else:
            _latest_kurtosis = 0.0

        # Check Condition 1: Mean adverse slippage breach
        if mean_val >= MAX_MEAN_SLIPPAGE_BPS:
            _blocked_until = max(_blocked_until, now + COOLDOWN_SECONDS)
            return

        # Check Condition 2: Slippage dispersion standard deviation breach
        if std_val >= MAX_SLIPPAGE_STD_BPS:
            _blocked_until = max(_blocked_until, now + COOLDOWN_SECONDS)
            return

        # Check Condition 3: Heavy tail kurtosis breach with adverse tail fill
        if _latest_kurtosis >= MAX_SLIPPAGE_KURTOSIS and max(_slippage_history) >= MIN_TAIL_SHOCK_BPS:
            _blocked_until = max(_blocked_until, now + COOLDOWN_SECONDS)
            return


def update(
    expected_price: float,
    exec_price: float,
    side: str,
    ts: Optional[float] = None,
) -> None:
    """Alias for record_execution()."""
    record_execution(expected_price, exec_price, side, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to slippage risk."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_slippage_stats() -> Dict[str, float]:
    """Return latest calculated slippage distribution statistics."""
    with _lock:
        return {
            "mean_slippage_bps": _latest_mean,
            "std_slippage_bps": _latest_std,
            "kurtosis": _latest_kurtosis,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the slippage dispersion guard state."""
    with _lock:
        now = time.monotonic()
        return {
            "mean_slippage_bps": _latest_mean,
            "std_slippage_bps": _latest_std,
            "kurtosis": _latest_kurtosis,
            "sample_count": len(_slippage_history),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "max_mean_threshold": MAX_MEAN_SLIPPAGE_BPS,
            "max_std_threshold": MAX_SLIPPAGE_STD_BPS,
            "max_kurtosis_threshold": MAX_SLIPPAGE_KURTOSIS,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset execution history, statistical metrics, and active blocks."""
    global _latest_mean, _latest_std, _latest_kurtosis, _blocked_until
    with _lock:
        _slippage_history.clear()
        _latest_mean = 0.0
        _latest_std = 0.0
        _latest_kurtosis = 0.0
        _blocked_until = 0.0
