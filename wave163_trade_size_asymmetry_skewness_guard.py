"""
wave163_trade_size_asymmetry_skewness_guard.py
----------------------------------------------
Guard: Signed Trade Size Asymmetry & Volume Skewness Guard

Measures institutional order flow asymmetry via the skewness and concentration of signed
trade volumes:
    Signed_Volume_t = Sign_t * Volume_t  (where Sign in {+1 for buy, -1 for sell})
    gamma_1 = ( (1/N) * sum (Signed_Volume_t - mean_V)^3 ) / (std_V^3)
    Concentration = Buy_Volume / (Buy_Volume + Sell_Volume)

Under normal balanced market liquidity, retail flow consists of roughly symmetric buy and sell sizes.
When an institutional execution algorithm (e.g. iceberg sweep, liquidation block) sweeps liquidity,
signed trade volumes become heavily skewed (large one-sided volume bursts with tiny opposing fills).
If |gamma_1| >= MAX_SKEWNESS (default: 2.50) OR volume concentration >= 85% (or <= 15%),
severe institutional flow toxicity is detected, triggering an entry block for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Records trade volume and initiator sign (+1 buy, -1 sell).
- Validates inputs (volume > 0, numeric, non-NaN, non-Inf, non-boolean).
- Maintains rolling window (WINDOW_SIZE = 20 signed trades).
- Requires at least MIN_SAMPLES = 10 trades before evaluation.
- Computes sample skewness gamma_1 and directional volume concentration ratio.
- If |gamma_1| >= MAX_SKEWNESS (2.50) OR concentration >= MAX_IMBALANCE (0.85) OR concentration <= MIN_IMBALANCE (0.15):
    blocks entries for COOLDOWN_SECONDS (45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: invalid or corrupted trade parameters are ignored.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_trade(volume, sign, ts=None)                      -> None
  update(volume, sign, ts=None)                            -> None   (alias)
  get_volume_skewness()                                    -> float
  reset()                                                  -> None
"""

import collections
import math
import threading
import time
from typing import Deque, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_SKEWNESS: float = 2.50         # Sample skewness >= 2.50 indicates severe volume asymmetry
MAX_IMBALANCE: float = 0.85        # >= 85% buy volume concentration triggers block
MIN_IMBALANCE: float = 0.15        # <= 15% buy volume (>= 85% sell) triggers block
WINDOW_SIZE: int = 20              # Lookback window of signed trade observations
MIN_SAMPLES: int = 10              # Minimum observations required before evaluation
COOLDOWN_SECONDS: float = 45.0     # Block duration in seconds on order flow asymmetry


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_signed_volumes: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_latest_skewness: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_trade(volume, sign, ts=None) -> None:
    """Record a trade's volume and initiator sign, evaluating volume skewness and asymmetry."""
    for val in (volume, sign):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return
        if math.isnan(val) or math.isinf(val):
            return

    v = float(volume)
    s_raw = float(sign)

    if v <= 0.0:
        return

    s = 1.0 if s_raw > 0.0 else (-1.0 if s_raw < 0.0 else 0.0)
    if s == 0.0:
        return

    signed_v = s * v

    global _latest_skewness, _blocked_until
    with _lock:
        _signed_volumes.append(signed_v)
        if len(_signed_volumes) < MIN_SAMPLES:
            return

        n = len(_signed_volumes)
        mean_v = sum(_signed_volumes) / n
        var_v = sum((x - mean_v) ** 2 for x in _signed_volumes) / n

        # Calculate directional buy/sell concentration
        buy_vol = sum(x for x in _signed_volumes if x > 0.0)
        sell_vol = sum(-x for x in _signed_volumes if x < 0.0)
        total_vol = buy_vol + sell_vol

        concentration = (buy_vol / total_vol) if total_vol > 1e-9 else 0.50

        if var_v <= 1e-12:
            skewness = 0.0
        else:
            std_v = math.sqrt(var_v)
            m3 = sum((x - mean_v) ** 3 for x in _signed_volumes) / n
            skewness = m3 / (std_v ** 3)

        _latest_skewness = skewness

        if abs(skewness) >= MAX_SKEWNESS or concentration >= MAX_IMBALANCE or concentration <= MIN_IMBALANCE:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(volume, sign, ts=None) -> None:
    """Alias for record_trade()."""
    record_trade(volume, sign, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if signed trade size asymmetry has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_volume_skewness() -> float:
    """Return the most recently calculated signed trade volume skewness."""
    with _lock:
        return _latest_skewness


def reset() -> None:
    """Reset signed volume history, latest skewness, and active cooldown."""
    global _latest_skewness, _blocked_until
    with _lock:
        _signed_volumes.clear()
        _latest_skewness = 0.0
        _blocked_until = 0.0
