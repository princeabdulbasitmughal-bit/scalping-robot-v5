"""
wave223_cross_asset_microstructure_correlation_breakdown_guard.py
-------------------------------------------------------------------
Guard: Cross-Asset Microstructure Correlation Breakdown Guard

Monitors ultra-high-frequency return correlation breakdown between the traded symbol
(e.g., Gold / XAUUSD) and its macro anchor index (e.g., DXY / US Dollar Index)
(Forbes & Rigobon 2002; Engle 2002 DCC):
    Return Target:         r_{tgt, i} = (P_{tgt, i} - P_{tgt, i-1}) / P_{tgt, i-1} * 10,000 (bps)
    Return Anchor:         r_{anc, i} = (P_{anc, i} - P_{anc, i-1}) / P_{anc, i-1} * 10,000 (bps)
    Rolling Correlation:   rho = Cov(r_{tgt}, r_{anc}) / (sigma_{tgt} * sigma_{anc})
                           over rolling N = 25 ticks.

In healthy macro-coupled microstructure regimes:
    - Gold and the US Dollar maintain a strong, stable inverse relationship:
      rho <= -0.50 (typical baseline: rho ~ -0.70).
    - Statistical arbitrage and scalping pricing models rely on this tight co-movement.

During severe idiosyncratic liquidity dislocations, sudden central bank intervention,
or structural market decoupling:
    - The cross-asset correlation breaks down completely or flips sign:
        1) Correlation Inversion Dislocation:
           rho >= BREAKDOWN_CORRELATION_THRESHOLD (default: +0.25, reflecting a massive
           >= 0.95 dislocation from the typical -0.70 inverse baseline).
        2) Active Volatility Floor:
           sigma_{tgt} >= MIN_VOLATILITY_BPS (default: 0.5 bps) AND
           sigma_{anc} >= MIN_VOLATILITY_BPS (default: 0.5 bps).

Operating statistical scalping models during active cross-asset correlation decoupling
results in severe model breakdown, mispriced spreads, and massive directional slippage.

When a cross-asset correlation breakdown is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests paired quotes via record_prices(price_target, price_anchor, ts=None).
- Computes basis-point returns for both assets.
- Maintains rolling window of WINDOW_SIZE = 25 return pairs.
- Requires MIN_SAMPLES = 15 pairs before evaluating Pearson correlation rho.
- Evaluates correlation breakdown vs BREAKDOWN_CORRELATION_THRESHOLD (+0.25).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive prices are rejected.

Aliases (required):
  is_entry_blocked()                                                   -> bool
  is_blocked()                                                         -> bool   (alias)
  record_prices(price_target, price_anchor, ts=None)                   -> None
  update(price_target, price_anchor, ts=None)                          -> None   (alias)
  get_correlation_metrics()                                           -> dict
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
EXPECTED_BASELINE_RHO: float = -0.70      # Inverse correlation baseline (e.g. Gold vs USD)
BREAKDOWN_CORRELATION_THRESHOLD: float = 0.25  # Inversion to +0.25 indicates complete breakdown
MIN_VOLATILITY_BPS: float = 0.5           # Minimum 0.5 bps stddev to avoid division by zero
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_tgt_price: Optional[float] = None
_prev_anc_price: Optional[float] = None
_tgt_returns = collections.deque(maxlen=WINDOW_SIZE)
_anc_returns = collections.deque(maxlen=WINDOW_SIZE)
_latest_rho: float = -0.70
_latest_tgt_std: float = 0.0
_latest_anc_std: float = 0.0
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


def record_prices(
    price_target: float,
    price_anchor: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest paired price ticks and evaluate rolling Pearson cross-asset correlation.
    """
    global _prev_tgt_price, _prev_anc_price, _latest_rho, _latest_tgt_std, _latest_anc_std, _blocked_until

    if not _is_valid_price(price_target) or not _is_valid_price(price_anchor):
        return

    pt = float(price_target)
    pa = float(price_anchor)

    with _lock:
        if _prev_tgt_price is None or _prev_anc_price is None:
            _prev_tgt_price = pt
            _prev_anc_price = pa
            return

        r_tgt = ((pt - _prev_tgt_price) / _prev_tgt_price) * 10_000.0
        r_anc = ((pa - _prev_anc_price) / _prev_anc_price) * 10_000.0

        _prev_tgt_price = pt
        _prev_anc_price = pa

        _tgt_returns.append(r_tgt)
        _anc_returns.append(r_anc)

        n = len(_tgt_returns)
        if n < MIN_SAMPLES:
            return

        mean_tgt = sum(_tgt_returns) / float(n)
        mean_anc = sum(_anc_returns) / float(n)

        var_tgt = sum((r - mean_tgt) ** 2 for r in _tgt_returns)
        var_anc = sum((r - mean_anc) ** 2 for r in _anc_returns)

        std_tgt = math.sqrt(var_tgt / float(n))
        std_anc = math.sqrt(var_anc / float(n))

        _latest_tgt_std = std_tgt
        _latest_anc_std = std_anc

        # Minimum volatility floor check
        if std_tgt < MIN_VOLATILITY_BPS or std_anc < MIN_VOLATILITY_BPS:
            return

        cov = sum((_tgt_returns[i] - mean_tgt) * (_anc_returns[i] - mean_anc) for i in range(n))
        denom = math.sqrt(var_tgt * var_anc)

        if denom <= 1e-9:
            return

        rho = max(-1.0, min(1.0, cov / denom))
        _latest_rho = rho

        # Check Correlation Breakdown: flipped from negative baseline to >= +0.25
        if rho >= BREAKDOWN_CORRELATION_THRESHOLD:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(
    price_target: float,
    price_anchor: float,
    ts: Optional[float] = None,
) -> None:
    """Alias for record_prices()."""
    record_prices(price_target, price_anchor, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to correlation breakdown."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_correlation_metrics() -> Dict[str, float]:
    """Return latest calculated correlation rho, target std, and anchor std."""
    with _lock:
        return {
            "correlation_rho": _latest_rho,
            "target_std_bps": _latest_tgt_std,
            "anchor_std_bps": _latest_anc_std,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the cross-asset correlation guard."""
    with _lock:
        now = time.monotonic()
        return {
            "correlation_rho": _latest_rho,
            "target_std_bps": _latest_tgt_std,
            "anchor_std_bps": _latest_anc_std,
            "sample_count": len(_tgt_returns),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "expected_baseline_rho": EXPECTED_BASELINE_RHO,
            "breakdown_threshold": BREAKDOWN_CORRELATION_THRESHOLD,
            "min_volatility_bps": MIN_VOLATILITY_BPS,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset paired price history, return deques, metrics, and active cooldown blocks."""
    global _prev_tgt_price, _prev_anc_price, _latest_rho, _latest_tgt_std, _latest_anc_std, _blocked_until
    with _lock:
        _prev_tgt_price = None
        _prev_anc_price = None
        _tgt_returns.clear()
        _anc_returns.clear()
        _latest_rho = -0.70
        _latest_tgt_std = 0.0
        _latest_anc_std = 0.0
        _blocked_until = 0.0
