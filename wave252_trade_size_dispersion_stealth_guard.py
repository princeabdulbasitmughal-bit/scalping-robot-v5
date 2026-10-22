"""
wave252_trade_size_dispersion_stealth_guard.py
------------------------------------------------
Guard: Microstructure Trade Size Relative Variance & Stealth Size Guard

Monitors empirical trade lot size relative dispersion and institutional stealth block trading
(Barclay & Warner 1993; Chakravarty 2001):
    Trade Volumes:            V_i in rolling window of N = 20 trades
    Mean Size:                \\mu_V = (1 / N) * \\sum_{i=1}^N V_i
    Size Volatility:          \\sigma_V = sqrt( (1 / (N - 1)) * \\sum_{i=1}^N (V_i - \\mu_V)^2 )
    Coefficient of Variation: CV_V = \\sigma_V / max(0.01, \\mu_V)
    Spike Ratio:              R_{spike} = max(V_i) / max(0.01, median(V_i))

Under normal, retail or homogeneous liquidity conditions:
    - Trade parcel sizes follow compact distributions:
      CV_V <= 1.20, with max-to-median spike ratio R_{spike} < 4.0x.

During predatory institutional iceberg execution, stealth order splitting, or sudden whale block sweeps:
    - High-frequency variance in individual trade volumes explodes non-linearly:
        1) Severe Trade Size Variance Explosion:
           CV_V >= MAX_SIZE_CV (default: 2.00) AND
           R_{spike} >= MAX_SPIKE_RATIO (default: 8.0x) over rolling N >= 15 trades.
        2) Single Massive Whale Block Sweep:
           Single trade volume V_i >= MAX_WHALE_SIZE (default: 25.0 lots).

Trading counter to massive stealth block insertions or extreme size variance guarantees
immediate adverse price impact, depth clearance, and acute slippage.

When size dispersion explosion or whale block is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade volumes via record_trade_size(volume_lots, ts=None).
- Maintains rolling history of WINDOW_SIZE = 20 trade volumes.
- Minimum MIN_SAMPLES = 15 trades required for rolling dispersion evaluation.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive volumes are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade_size(volume_lots, ts=None)                                                      -> None
  update(volume_lots, ts=None)                                                                 -> None   (alias)
  get_size_dispersion_metrics()                                                                -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 20
MIN_SAMPLES: int = 15
MAX_SIZE_CV: float = 2.00              # 2.00 coefficient of variation
MAX_SPIKE_RATIO: float = 8.0           # 8.0x max-to-median size ratio
MAX_WHALE_SIZE: float = 25.0           # 25.0 lots single trade whale threshold
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_volumes_history = collections.deque(maxlen=WINDOW_SIZE)  # trade sizes in lots
_latest_volume: float = 1.0
_latest_mean_size: float = 1.0
_latest_size_cv: float = 0.0
_latest_spike_ratio: float = 1.0
_blocked_until: float = 0.0


def _is_valid_positive(val: Any) -> bool:
    """Validate value is a positive finite numeric float or int."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val > 0.0


def record_trade_size(
    volume_lots: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest individual trade volume and evaluate size dispersion and whale spikes.
    """
    global _latest_volume, _latest_mean_size, _latest_size_cv, _latest_spike_ratio, _blocked_until

    if not _is_valid_positive(volume_lots):
        return

    vol = float(volume_lots)

    with _lock:
        _latest_volume = vol
        _volumes_history.append(vol)

        # Condition 1: Single massive whale block sweep
        if vol >= MAX_WHALE_SIZE:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        n = len(_volumes_history)
        if n >= MIN_SAMPLES:
            mu = sum(_volumes_history) / n
            var = sum((x - mu) ** 2 for x in _volumes_history) / (n - 1)
            sigma = math.sqrt(max(0.0, var))
            cv = sigma / max(0.01, mu)

            med = statistics.median(_volumes_history)
            max_v = max(_volumes_history)
            spike_ratio = max_v / max(0.01, med)

            _latest_mean_size = mu
            _latest_size_cv = cv
            _latest_spike_ratio = spike_ratio

            # Condition 2: Severe trade size variance explosion
            if cv >= MAX_SIZE_CV and spike_ratio >= MAX_SPIKE_RATIO:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return
        else:
            _latest_mean_size = sum(_volumes_history) / n
            _latest_size_cv = 0.0
            _latest_spike_ratio = 1.0


def update(
    volume_lots: float,
    ts: Optional[float] = None,
) -> None:
    """Alias for record_trade_size()."""
    record_trade_size(volume_lots, ts)


def is_entry_blocked() -> bool:
    """Check if new entries are blocked by trade size dispersion or whale block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_size_dispersion_metrics() -> Dict[str, float]:
    """Retrieve current trade size dispersion metrics."""
    with _lock:
        return {
            "latest_volume": _latest_volume,
            "mean_size": _latest_mean_size,
            "size_cv": _latest_size_cv,
            "spike_ratio": _latest_spike_ratio,
        }


def get_status() -> Dict[str, Any]:
    """Retrieve complete guard status."""
    with _lock:
        now = time.monotonic()
        blocked = now < _blocked_until
        remaining = max(0.0, _blocked_until - now) if blocked else 0.0
        return {
            "guard_name": "wave252_trade_size_dispersion_stealth_guard",
            "is_blocked": blocked,
            "blocked_seconds_remaining": remaining,
            "sample_count": len(_volumes_history),
            "latest_volume": _latest_volume,
            "mean_size": _latest_mean_size,
            "size_cv": _latest_size_cv,
            "spike_ratio": _latest_spike_ratio,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "max_size_cv": MAX_SIZE_CV,
            "max_spike_ratio": MAX_SPIKE_RATIO,
            "max_whale_size": MAX_WHALE_SIZE,
        }


def reset() -> None:
    """Reset all guard state and clear cooldowns."""
    global _latest_volume, _latest_mean_size, _latest_size_cv, _latest_spike_ratio, _blocked_until

    with _lock:
        _volumes_history.clear()
        _latest_volume = 1.0
        _latest_mean_size = 1.0
        _latest_size_cv = 0.0
        _latest_spike_ratio = 1.0
        _blocked_until = 0.0
