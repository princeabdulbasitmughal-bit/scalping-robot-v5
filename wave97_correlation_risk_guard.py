"""
wave97_correlation_risk_guard.py
----------------------------------
Guard: Correlation Risk Guard

Blocks new entries when two tracked instruments show high price correlation
over a rolling window, indicating concentration risk (both positions would
move together, amplifying losses).

Logic:
- Maintains two rolling deques of price returns (last N=20 ticks) for
  symbol_a and symbol_b respectively.
- Computes Pearson correlation coefficient between the two return series.
- If abs(correlation) >= MAX_CORRELATION (default: 0.85), entry is blocked
  for COOLDOWN_SECONDS (default: 60s).
- Warmup: MIN_SAMPLES required in both series before blocking activates.
- Fail-closed: any division-by-zero or NaN in correlation → no block triggered.
- Thread-safe: threading.RLock() on all shared state.

Aliases:
  is_entry_blocked() -> bool
  is_blocked()       -> bool  (same)
  update_a(price)    -> None  (feed price for instrument A)
  update_b(price)    -> None  (feed price for instrument B)
  update(price_a, price_b) -> None  (feed both at once)
  reset()            -> None
"""

import math
import threading
import time
from collections import deque

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_CORRELATION: float = 0.85   # absolute Pearson correlation threshold
COOLDOWN_SECONDS: float = 60.0  # block duration after breach
MIN_SAMPLES: int = 5            # minimum return samples in each series
WINDOW_SIZE: int = 20           # rolling window length (number of prices)


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()

_prices_a: deque = deque(maxlen=WINDOW_SIZE + 1)  # +1 to compute returns
_prices_b: deque = deque(maxlen=WINDOW_SIZE + 1)

_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _pearson(xs, ys) -> float:
    """Compute Pearson r for two equal-length lists. Returns NaN on failure."""
    n = len(xs)
    if n < 2:
        return float("nan")
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    denom = math.sqrt(var_x * var_y)
    if denom == 0.0:
        return float("nan")
    return cov / denom


def _returns(prices) -> list:
    """Compute simple returns list from a price deque."""
    p = list(prices)
    if len(p) < 2:
        return []
    return [(p[i] - p[i - 1]) / p[i - 1] for i in range(1, len(p)) if p[i - 1] != 0.0]


def _check_and_block() -> None:
    """Internal: recompute correlation and set block if threshold exceeded."""
    global _blocked_until
    ret_a = _returns(_prices_a)
    ret_b = _returns(_prices_b)
    min_len = min(len(ret_a), len(ret_b))
    if min_len < MIN_SAMPLES:
        return
    # Align to same length (most recent)
    ret_a = ret_a[-min_len:]
    ret_b = ret_b[-min_len:]
    r = _pearson(ret_a, ret_b)
    if math.isnan(r):
        return
    if abs(r) >= MAX_CORRELATION:
        _blocked_until = time.monotonic() + COOLDOWN_SECONDS


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _validate_price(price) -> bool:
    """Return True iff price is a valid finite positive number."""
    if isinstance(price, bool):
        return False
    if not isinstance(price, (int, float)):
        return False
    if math.isnan(price) or math.isinf(price):
        return False
    if price <= 0.0:
        return False
    return True


def update_a(price) -> None:
    """Feed a new price tick for instrument A."""
    if not _validate_price(price):
        return
    with _lock:
        _prices_a.append(float(price))
        _check_and_block()


def update_b(price) -> None:
    """Feed a new price tick for instrument B."""
    if not _validate_price(price):
        return
    with _lock:
        _prices_b.append(float(price))
        _check_and_block()


def update(price_a, price_b) -> None:
    """Feed price ticks for both instruments simultaneously."""
    if not _validate_price(price_a) or not _validate_price(price_b):
        return
    with _lock:
        _prices_a.append(float(price_a))
        _prices_b.append(float(price_b))
        _check_and_block()


def is_entry_blocked() -> bool:
    """Return True when correlation risk is currently blocking entries."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Clear all state (use between tests or sessions)."""
    global _blocked_until
    with _lock:
        _prices_a.clear()
        _prices_b.clear()
        _blocked_until = 0.0
