"""
wave212_microstructure_noise_snr_decay_guard.py
------------------------------------------------
Guard: Microstructure Noise-to-Signal Ratio (NSR) & High-Frequency Frictional Trap Guard

Monitors the proportion of realized price variance attributable to artificial microstructure noise,
bid-ask bounce, and quoting friction versus true fundamental price discovery
(Zhang, Mykland, Aït-Sahalia 2005; Hansen & Lunde 2006):
    Raw RV:         RV_{raw} = sum_{i=1}^N r_{1, i}^2
    Subsampled RV:  RV_{sparse} = sum_{j=1}^{N/K} r_{K, j}^2
    Noise Ratio:    NSR = max(0.0, RV_{raw} - RV_{sparse}) / max(1e-8, RV_{sparse})
where K = 5 subsampling step and N = 30 rolling tick prices.

In healthy, liquid continuous markets with low frictional friction:
    NSR <= 1.50 (realized variance is dominated by persistent directional price discovery).

During toxic microstructure friction traps—such as high-frequency bid-ask bouncing, quote flickering,
or predatory latency pinging—raw sub-second variance explodes relative to sparse variance:
    NSR >= MAX_NOISE_RATIO (default: 3.50, meaning >= 75% of observed price variance is noise).

In this regime, attempting to scalp signals is mathematically futile: strategies are whipsawed by
bid-ask bounce friction and suffer severe execution haircut.

When the Noise-to-Signal Ratio breaches the safety threshold, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests tick prices (price > 0.0, ts=None).
- Maintains a rolling window of WINDOW_SIZE = 30 tick prices.
- Computes single-step returns and K=5 subsampled sparse returns.
- Calculates RV_{raw}, RV_{sparse}, and Noise-to-Signal Ratio NSR.
- Blocks entries for COOLDOWN_SECONDS (45.0s) if NSR >= 3.50 with active raw variance.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive price inputs are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_price(price, ts=None)                             -> None
  update(price, ts=None)                                   -> None   (alias)
  get_noise_metrics()                                      -> dict
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
WINDOW_SIZE: int = 30
SUBSAMPLE_STEP: int = 5
MIN_SAMPLES: int = 25
MAX_NOISE_RATIO: float = 3.50          # 3.5x noise-to-signal ratio indicates frictional trap
MIN_RAW_VARIANCE: float = 1e-8         # minimum variance to prevent division by near-zero
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prices = collections.deque(maxlen=WINDOW_SIZE)
_latest_nsr: float = 0.0
_latest_rv_raw: float = 0.0
_latest_rv_sparse: float = 0.0
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


def record_price(price: float, ts: Optional[float] = None) -> None:
    """
    Ingest a new tick price, update price history, and compute NSR.
    """
    global _latest_nsr, _latest_rv_raw, _latest_rv_sparse, _blocked_until

    if not _is_valid_price(price):
        return

    p = float(price)

    with _lock:
        now = time.monotonic() if ts is None else float(ts)
        _prices.append(p)

        n = len(_prices)
        if n < MIN_SAMPLES:
            return

        # 1-step returns
        rv_raw = 0.0
        for i in range(1, n):
            ret = (_prices[i] - _prices[i - 1]) / _prices[i - 1]
            rv_raw += ret * ret

        # K-step sparse returns
        rv_sparse = 0.0
        for i in range(SUBSAMPLE_STEP, n, SUBSAMPLE_STEP):
            ret_sparse = (_prices[i] - _prices[i - SUBSAMPLE_STEP]) / _prices[i - SUBSAMPLE_STEP]
            rv_sparse += ret_sparse * ret_sparse

        _latest_rv_raw = rv_raw
        _latest_rv_sparse = rv_sparse

        if rv_sparse < 1e-9:
            nsr = 0.0
        else:
            nsr = max(0.0, rv_raw - rv_sparse) / rv_sparse

        _latest_nsr = nsr

        # Check Condition: Noise-to-Signal Ratio breach with active volatility
        if nsr >= MAX_NOISE_RATIO and rv_raw >= MIN_RAW_VARIANCE:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(price: float, ts: Optional[float] = None) -> None:
    """Alias for record_price()."""
    record_price(price, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to microstructure noise."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_noise_metrics() -> Dict[str, float]:
    """Return latest calculated RV raw, RV sparse, and NSR."""
    with _lock:
        return {
            "nsr": _latest_nsr,
            "rv_raw": _latest_rv_raw,
            "rv_sparse": _latest_rv_sparse,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the microstructure noise guard."""
    with _lock:
        now = time.monotonic()
        return {
            "nsr": _latest_nsr,
            "rv_raw": _latest_rv_raw,
            "rv_sparse": _latest_rv_sparse,
            "sample_count": len(_prices),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "max_noise_ratio": MAX_NOISE_RATIO,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset price history, RV metrics, and active cooldown blocks."""
    global _latest_nsr, _latest_rv_raw, _latest_rv_sparse, _blocked_until
    with _lock:
        _prices.clear()
        _latest_nsr = 0.0
        _latest_rv_raw = 0.0
        _latest_rv_sparse = 0.0
        _blocked_until = 0.0
