"""
wave235_trade_volume_volatility_clustering_guard.py
---------------------------------------------------
Guard: Multi-Scale Trade Volume Volatility Shock & Volume Clustering Guard

Monitors extreme variance spikes in trade execution volume and detects institutional
block order dumps and volume volatility shocks (Clark 1973; Lamoureux & Lastrapes 1990):
    Mean Trade Volume:     bar{V} = (1/N) * sum_{i=1}^N V_i (lots)
    Volume Std Dev:        sigma_V = sqrt( (1/N) * sum (V_i - bar{V})^2 )
    Volume CV:             CV_V = sigma_V / max(0.1, bar{V})
    Max Burst Ratio:       R_{burst} = max(V_{1..N}) / max(0.1, bar{V})
                           over rolling N = 25 trade executions.

In normal retail and market-making double-auction trading:
    - Trade sizes are relatively uniform and predictable: CV_V < 1.50, R_{burst} < 3.0x.

During predatory block trade routing, institutional iceberg unloading, or flash cascades:
    - Trade volume variance explodes as anomalous monster orders hit the tape:
        1) Volume Volatility Shock:
           CV_V >= MAX_VOLUME_CV (default: 2.50) AND
           R_{burst} >= MAX_BURST_RATIO (default: 4.0x) AND
           bar{V} >= MIN_MEAN_VOLUME (default: 1.0 lot).
        2) Massive Block Order Execution:
           Single execution volume V_{trade} >= BLOCK_TRADE_THRESHOLD (default: 25.0 lots).

Executing scalping trades immediately following an anomalous volume volatility shock
exposes market makers to massive directional momentum and adverse clearing price impact.

When a volume volatility shock or massive block trade is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade volumes via record_trade_volume(volume, ts=None).
- Maintains rolling window of WINDOW_SIZE = 25 trade volumes.
- Requires MIN_SAMPLES = 15 volumes before evaluating CV_V.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive volumes are rejected.

Aliases (required):
  is_entry_blocked()                                                   -> bool
  is_blocked()                                                         -> bool   (alias)
  record_trade_volume(volume, ts=None)                                 -> None
  update(volume, ts=None)                                              -> None   (alias)
  get_volume_metrics()                                                 -> dict
  get_status()                                                         -> dict
  reset()                                                              -> None
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
MAX_VOLUME_CV: float = 1.80               # Volume CV >= 1.80 indicates extreme variance shock
MAX_BURST_RATIO: float = 4.0              # Max trade >= 4.0x mean volume
MIN_MEAN_VOLUME: float = 1.0              # 1.0 lot minimum mean volume floor
BLOCK_TRADE_THRESHOLD: float = 25.0       # 25.0 lots single block trade threshold
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_volumes = collections.deque(maxlen=WINDOW_SIZE)
_latest_mean_vol: float = 1.0
_latest_sigma_vol: float = 0.5
_latest_cv_vol: float = 0.5
_latest_burst_ratio: float = 1.0
_blocked_until: float = 0.0


def _is_valid_volume(val: Any) -> bool:
    """Validate volume is a positive finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val > 0.0


def record_trade_volume(
    volume: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest a trade execution volume and evaluate volume volatility shocks.
    """
    global _latest_mean_vol, _latest_sigma_vol, _latest_cv_vol, _latest_burst_ratio, _blocked_until

    if not _is_valid_volume(volume):
        return

    vol = float(volume)

    with _lock:
        # Check Condition 2: Massive Block Order Execution
        if vol >= BLOCK_TRADE_THRESHOLD:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        _volumes.append(vol)
        n = len(_volumes)
        if n < MIN_SAMPLES:
            return

        mean_v = sum(_volumes) / float(n)
        var_v = sum((v - mean_v) ** 2 for v in _volumes) / float(n)
        sigma_v = math.sqrt(var_v)
        cv_v = sigma_v / max(0.1, mean_v)
        burst_ratio = max(_volumes) / max(0.1, mean_v)

        _latest_mean_vol = mean_v
        _latest_sigma_vol = sigma_v
        _latest_cv_vol = cv_v
        _latest_burst_ratio = burst_ratio

        # Check Condition 1: Volume Volatility Shock
        if (
            cv_v >= MAX_VOLUME_CV
            and burst_ratio >= MAX_BURST_RATIO
            and mean_v >= MIN_MEAN_VOLUME
        ):
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(volume: float, ts: Optional[float] = None) -> None:
    """Alias for record_trade_volume()."""
    record_trade_volume(volume, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to volume volatility shock."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_volume_metrics() -> Dict[str, float]:
    """Return latest calculated mean volume, sigma, CV, and burst ratio."""
    with _lock:
        return {
            "mean_volume": _latest_mean_vol,
            "sigma_volume": _latest_sigma_vol,
            "volume_cv": _latest_cv_vol,
            "burst_ratio": _latest_burst_ratio,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the volume volatility guard."""
    with _lock:
        now = time.monotonic()
        return {
            "mean_volume": _latest_mean_vol,
            "sigma_volume": _latest_sigma_vol,
            "volume_cv": _latest_cv_vol,
            "burst_ratio": _latest_burst_ratio,
            "sample_count": len(_volumes),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "max_volume_cv": MAX_VOLUME_CV,
            "max_burst_ratio": MAX_BURST_RATIO,
            "block_trade_threshold": BLOCK_TRADE_THRESHOLD,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset volume history, metrics, and active cooldown blocks."""
    global _latest_mean_vol, _latest_sigma_vol, _latest_cv_vol, _latest_burst_ratio, _blocked_until
    with _lock:
        _volumes.clear()
        _latest_mean_vol = 1.0
        _latest_sigma_vol = 0.5
        _latest_cv_vol = 0.5
        _latest_burst_ratio = 1.0
        _blocked_until = 0.0
