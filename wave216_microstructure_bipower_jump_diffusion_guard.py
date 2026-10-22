"""
wave216_microstructure_bipower_jump_diffusion_guard.py
-------------------------------------------------------
Guard: Microstructure Bipower Variation & Realized Jump Diffusion Guard

Decomposes high-frequency price variance into continuous Brownian diffusion and discrete
jump components using Barndorff-Nielsen & Shephard (2004) Bipower Variation (BV):
    Return:            r_i = (P_i - P_{i-1}) / P_{i-1} * 10,000 (bps)
    Realized Variance: RV = sum_{i=1}^N r_i^2
    Bipower Variation: BV = (pi / 2) * sum_{i=2}^N |r_i| * |r_{i-1}|
    Jump Ratio:        J = max(0.0, (RV - BV) / max(1e-6, RV))

In normal continuous microstructure diffusion:
    - Price changes are small, gradual, and Gaussian.
    - BV closely approximates RV, meaning J < 0.25 (jump fraction < 25%).

During toxic microstructure jumps (news releases, stop hunts, block market orders wiping multiple price levels):
    - A single large return shock r_j causes r_j^2 to dominate RV, while adjacent cross-products |r_j||r_{j-1}|
      remain dampened by the typical background return size.
    - The jump fraction J escalates sharply:
        1) J >= MAX_JUMP_FRACTION (default: 0.55 or 55% of realized variance from discrete jumps).
        2) RV >= MIN_RV_BPS2 (default: 2.0 bps^2, preventing false positives during low-volatility dead markets).
    - Or instantaneous volatility spike:
        sigma_inst >= MAX_VOLATILITY_SPIKE_BPS (default: 8.0 bps).

Posting passive liquidity or executing market scalping orders during discrete jump shocks guarantees
severe adverse selection and immediate execution haircut.

When a discrete jump shock is detected, entry orders are blocked for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests midquote/price via record_price(price, ts=None).
- Computes basis-point returns r_i.
- Maintains rolling window of WINDOW_SIZE = 25 returns.
- Requires MIN_SAMPLES = 15 returns before evaluating jump ratio.
- Evaluates RV, BV, and Jump Ratio J.
- Blocks entries for COOLDOWN_SECONDS (45.0s) if (J >= 0.55 and RV >= 2.0) or (sigma_inst >= 8.0 bps).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive prices are rejected.

Aliases (required):
  is_entry_blocked()                       -> bool
  is_blocked()                             -> bool   (alias)
  record_price(price, ts=None)             -> None
  update(price, ts=None)                   -> None   (alias)
  get_jump_metrics()                       -> dict
  get_status()                             -> dict
  reset()                                  -> None
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
MAX_JUMP_FRACTION: float = 0.55          # 55% of variance from discrete jumps
MIN_RV_BPS2: float = 2.0                 # 2.0 bps^2 minimum realized variance to trigger jump block
MAX_VOLATILITY_SPIKE_BPS: float = 8.0    # 8.0 bps single-return instantaneous jump shock
COOLDOWN_SECONDS: float = 45.0

# Mathematical constant for Bipower Variation: pi / 2
PI_OVER_TWO: float = math.pi / 2.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_price: Optional[float] = None
_returns = collections.deque(maxlen=WINDOW_SIZE)
_latest_rv: float = 0.0
_latest_bv: float = 0.0
_latest_jump_fraction: float = 0.0
_latest_max_return_bps: float = 0.0
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
    Ingest a new price tick and evaluate Realized Variance vs Bipower Variation jump diffusion.
    """
    global _prev_price, _latest_rv, _latest_bv, _latest_jump_fraction, _latest_max_return_bps, _blocked_until

    if not _is_valid_price(price):
        return

    p = float(price)

    with _lock:
        if _prev_price is None:
            _prev_price = p
            return

        # Calculate basis point return
        ret_bps = ((p - _prev_price) / _prev_price) * 10_000.0
        _prev_price = p
        _returns.append(ret_bps)

        n = len(_returns)
        if n < MIN_SAMPLES:
            return

        # Realized Variance: sum(r_i^2)
        rv = sum(r * r for r in _returns)
        _latest_rv = rv

        # Instantaneous max single return
        abs_returns = [abs(r) for r in _returns]
        max_ret = max(abs_returns)
        _latest_max_return_bps = max_ret

        # Bipower Variation: (pi / 2) * sum(|r_i| * |r_{i-1}|)
        bv_sum = sum(abs_returns[i] * abs_returns[i - 1] for i in range(1, n))
        bv = PI_OVER_TWO * bv_sum
        _latest_bv = bv

        # Jump fraction
        jump_fraction = max(0.0, (rv - bv) / max(1e-6, rv))
        _latest_jump_fraction = jump_fraction

        # Condition 1: Significant discrete jump fraction with elevated realized variance
        if jump_fraction >= MAX_JUMP_FRACTION and rv >= MIN_RV_BPS2:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 2: Extreme instantaneous jump return shock
        if max_ret >= MAX_VOLATILITY_SPIKE_BPS:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(price: float, ts: Optional[float] = None) -> None:
    """Alias for record_price()."""
    record_price(price, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to jump diffusion shock."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_jump_metrics() -> Dict[str, float]:
    """Return latest calculated RV, BV, Jump Fraction, and Max Return."""
    with _lock:
        return {
            "realized_variance": _latest_rv,
            "bipower_variation": _latest_bv,
            "jump_fraction": _latest_jump_fraction,
            "max_return_bps": _latest_max_return_bps,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the bipower jump diffusion guard."""
    with _lock:
        now = time.monotonic()
        return {
            "realized_variance": _latest_rv,
            "bipower_variation": _latest_bv,
            "jump_fraction": _latest_jump_fraction,
            "max_return_bps": _latest_max_return_bps,
            "sample_count": len(_returns),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "max_jump_fraction": MAX_JUMP_FRACTION,
            "min_rv_bps2": MIN_RV_BPS2,
            "max_volatility_spike_bps": MAX_VOLATILITY_SPIKE_BPS,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset price history, returns deque, jump metrics, and active cooldown blocks."""
    global _prev_price, _latest_rv, _latest_bv, _latest_jump_fraction, _latest_max_return_bps, _blocked_until
    with _lock:
        _prev_price = None
        _returns.clear()
        _latest_rv = 0.0
        _latest_bv = 0.0
        _latest_jump_fraction = 0.0
        _latest_max_return_bps = 0.0
        _blocked_until = 0.0
