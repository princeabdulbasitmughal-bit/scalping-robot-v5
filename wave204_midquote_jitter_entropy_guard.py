"""
wave204_midquote_jitter_entropy_guard.py
-----------------------------------------
Guard: High-Frequency Midquote Micro-Jitter & Transition Entropy Guard

Monitors rapid micro-tick midquote oscillations, pinging noise, and deterministic flickering:
    Midquote:     P_{mid, t} = (Bid_t + Ask_t) / 2
    Tick sign:    s_t = sign(P_{mid, t} - P_{mid, t-1}) in {-1, +1}
    Jitter ratio: J = Count(s_t != s_{t-1}) / (N - 1)
    Entropy:      H_{jitter} = -p_{flip} * log2(p_{flip}) - p_{same} * log2(p_{same})
where N = 20 rolling midquote price changes.

In normal, balanced price discovery, midquote movements exhibit two-sided stochastic diffusion:
    - Jitter alternation ratio: J is near 0.50 (0.35 <= J <= 0.65)
    - Transition entropy:       H_{jitter} is near 1.0 bit (>= 0.80 bits)

During predatory high-frequency microstructure events—such as quote flickering, micro-flickering spoofing,
or latency-pinging algorithmic traps—the midquote rapidly alternates back and forth (+tick, -tick, +tick, -tick):
    1) Excessive sign alternation (pinging flutter):
       J >= MAX_JITTER_RATIO (default: 0.80, or >= 80% flip rate) with fast tick cadence
       (mean tick dt <= 0.20s).
    2) Extreme entropy collapse:
       H_{jitter} <= MIN_JITTER_ENTROPY (default: 0.35 bits) with elevated alternation rate (J >= 0.75).

Trading into this artificial midquote jitter subjects limit scalpers to adverse routing queue priority,
stale fills, and excessive broker execution latency.

When excessive midquote jitter or entropy collapse is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests quotes (bid > 0.0, ask > bid, ts=None).
- Computes midquote P_{mid} and sign of price increment.
- Maintains rolling window of WINDOW_SIZE = 20 midquote directional signs and timestamps.
- Requires at least MIN_SAMPLES = 10 price increments before evaluation.
- Calculates Jitter Ratio J and Binary Transition Entropy H_{jitter}.
- Blocks entries for COOLDOWN_SECONDS (45.0s) if thresholds are breached.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive bids/asks, or inverted quotes are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_midquote(bid, ask, ts=None)                       -> None
  update(bid, ask, ts=None)                                -> None   (alias)
  get_jitter_metrics()                                     -> dict
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
MIN_SAMPLES: int = 10
MAX_JITTER_RATIO: float = 0.80         # 80% alternation rate indicates high-frequency pinging
MIN_JITTER_ENTROPY: float = 0.35       # 0.35 bits transition entropy collapse
MAX_MEAN_DT_SEC: float = 0.20          # 200ms maximum average tick interval for jitter condition
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prev_mid: Optional[float] = None
_prev_ts: Optional[float] = None
_signs = collections.deque(maxlen=WINDOW_SIZE)
_dts = collections.deque(maxlen=WINDOW_SIZE)
_latest_jitter_ratio: float = 0.50
_latest_entropy: float = 1.0
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


def record_midquote(bid: float, ask: float, ts: Optional[float] = None) -> None:
    """
    Ingest a new quote, compute midquote increment sign, and evaluate jitter metrics.
    """
    global _prev_mid, _prev_ts, _latest_jitter_ratio, _latest_entropy, _blocked_until

    if not _is_valid_price(bid) or not _is_valid_price(ask):
        return
    if float(ask) <= float(bid):
        return

    mid = (float(bid) + float(ask)) / 2.0

    with _lock:
        now = time.monotonic() if ts is None else float(ts)

        if _prev_mid is None:
            _prev_mid = mid
            _prev_ts = now
            return

        diff = mid - _prev_mid
        dt = max(1e-4, now - _prev_ts) if _prev_ts is not None else 0.10
        _prev_mid = mid
        _prev_ts = now

        # Only register meaningful price increments
        if abs(diff) < 1e-9:
            return

        sign = 1 if diff > 0 else -1
        _signs.append(sign)
        _dts.append(dt)

        n = len(_signs)
        if n < MIN_SAMPLES:
            return

        # Calculate sign flips
        flips = sum(1 for i in range(1, n) if _signs[i] != _signs[i - 1])
        jitter_ratio = flips / float(n - 1)
        _latest_jitter_ratio = jitter_ratio

        # Mean tick interval
        mean_dt = sum(_dts) / float(len(_dts))

        # Binary transition entropy
        p_flip = max(1e-6, min(1.0 - 1e-6, jitter_ratio))
        p_same = 1.0 - p_flip
        entropy = - (p_flip * math.log2(p_flip) + p_same * math.log2(p_same))
        _latest_entropy = entropy

        # Condition 1: Excessive sign alternation pinging with high cadence
        if jitter_ratio >= MAX_JITTER_RATIO and mean_dt <= MAX_MEAN_DT_SEC:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 2: Deterministic transition entropy collapse
        if entropy <= MIN_JITTER_ENTROPY and jitter_ratio >= 0.75:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(bid: float, ask: float, ts: Optional[float] = None) -> None:
    """Alias for record_midquote()."""
    record_midquote(bid, ask, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to midquote jitter."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_jitter_metrics() -> Dict[str, float]:
    """Return latest calculated jitter ratio and transition entropy."""
    with _lock:
        return {
            "jitter_ratio": _latest_jitter_ratio,
            "jitter_entropy": _latest_entropy,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the midquote jitter guard."""
    with _lock:
        now = time.monotonic()
        return {
            "jitter_ratio": _latest_jitter_ratio,
            "jitter_entropy": _latest_entropy,
            "sample_count": len(_signs),
            "window_size": WINDOW_SIZE,
            "min_samples": MIN_SAMPLES,
            "max_jitter_threshold": MAX_JITTER_RATIO,
            "min_entropy_threshold": MIN_JITTER_ENTROPY,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset midquote history, signs buffer, and active cooldown blocks."""
    global _prev_mid, _prev_ts, _latest_jitter_ratio, _latest_entropy, _blocked_until
    with _lock:
        _prev_mid = None
        _prev_ts = None
        _signs.clear()
        _dts.clear()
        _latest_jitter_ratio = 0.50
        _latest_entropy = 1.0
        _blocked_until = 0.0
