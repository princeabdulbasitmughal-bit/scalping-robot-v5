"""
wave141_spectral_entropy_guard.py
---------------------------------
Guard: Fourier Transform Power Spectral Density (PSD) Entropy Guard

Evaluates the spectral entropy of the discrete Fourier transform of high-frequency
tick returns. In healthy liquid markets, price fluctuations exhibit broadband white
noise characteristics with high spectral entropy (SE >= 0.55).
When periodic algorithmic loops, rhythmic quote ping-pong, or repetitive spoofing
cycles dominate the order book, power spectral density collapses into discrete harmonic
spikes, driving spectral entropy towards zero.

Logic:
- Stores rolling window of WINDOW_SIZE (default: 16) fractional returns.
- Computes Discrete Fourier Transform (DFT) across K = WINDOW_SIZE / 2 positive frequency bins.
- Evaluates normalized power spectral density:
    p_k = PSD_k / sum(PSD)
- Computes Shannon spectral entropy:
    H = - sum_{p_k > 0}(p_k * ln(p_k))
    SE = H / ln(K)  (normalized to [0.0, 1.0])
- If SE < MIN_SPECTRAL_ENTROPY (default: 0.55):
    blocks entries for COOLDOWN_SECONDS (default: 60.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Fail-closed: invalid, non-numeric, boolean, NaN, Inf, and non-positive prices ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()             -> bool
  is_blocked()                   -> bool   (alias)
  record_price(price, ts=None)   -> None
  update(price, ts=None)         -> None   (alias)
  get_spectral_entropy()         -> float
  reset()                        -> None
"""

import collections
import math
import threading
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 16                  # rolling returns buffer size (power of 2)
MIN_OBSERVATIONS: int = 16             # minimum observations for spectral analysis
MIN_SPECTRAL_ENTROPY: float = 0.55     # threshold for harmonic concentration
COOLDOWN_SECONDS: float = 60.0         # duration of protective block


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_price: Optional[float] = None
_returns = collections.deque(maxlen=WINDOW_SIZE)
_blocked_until: float = 0.0
_last_se: float = 1.0                  # default to uniform white noise spectrum


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_price(price, ts=None) -> None:
    """Record tick price, compute return, and evaluate power spectral entropy."""
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return

    curr_p = float(price)

    global _prev_price, _blocked_until, _last_se
    with _lock:
        if _prev_price is None:
            _prev_price = curr_p
            return

        r = (curr_p - _prev_price) / _prev_price
        _returns.append(r)
        _prev_price = curr_p

        if len(_returns) >= MIN_OBSERVATIONS:
            n = len(_returns)
            k_bins = n // 2
            mean_r = sum(_returns) / n
            y = [val - mean_r for val in _returns]

            psd = []
            for k in range(1, k_bins + 1):
                re = 0.0
                im = 0.0
                angle_step = 2.0 * math.pi * k / n
                for idx in range(n):
                    angle = angle_step * idx
                    re += y[idx] * math.cos(angle)
                    im -= y[idx] * math.sin(angle)
                psd.append(re * re + im * im)

            total_power = sum(psd)
            if total_power > 1e-12 and k_bins > 1:
                p_dist = [p / total_power for p in psd]
                h = -sum(pk * math.log(pk) for pk in p_dist if pk > 1e-9)
                se = h / math.log(k_bins)
            else:
                se = 1.0

            # Bound within [0.0, 1.0]
            se = max(0.0, min(1.0, se))
            _last_se = se

            if se < MIN_SPECTRAL_ENTROPY:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(price, ts=None) -> None:
    """Alias for record_price()."""
    record_price(price, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if spectral entropy drop has triggered protection."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_spectral_entropy() -> float:
    """Return the most recently computed spectral entropy."""
    with _lock:
        return _last_se


def reset() -> None:
    """Reset price history, return buffer, and active block."""
    global _prev_price, _blocked_until, _last_se
    with _lock:
        _prev_price = None
        _returns.clear()
        _blocked_until = 0.0
        _last_se = 1.0
