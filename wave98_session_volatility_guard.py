"""
wave98_session_volatility_guard.py
------------------------------------
Guard: Session Volatility Guard

Blocks new entries when the realised intra-session volatility (standard
deviation of mid-price returns over the last N ticks) exceeds a configurable
threshold, indicating abnormally turbulent market conditions.

Logic:
- Maintains a rolling deque of the last WINDOW_SIZE mid-prices.
- Computes sample std-dev of tick-to-tick log-returns.
- If std_dev >= MAX_VOLATILITY (default: 0.002 == 0.2% per tick), entry is
  blocked for COOLDOWN_SECONDS (default: 60s).
- Warmup: MIN_SAMPLES price updates required before blocking can activate.
- Fail-closed: NaN/Inf or corrupted inputs → state unchanged; if warmup
  not met → not blocked (fail-open during warmup is intentional).
- Thread-safe: threading.RLock() on all shared state.
- Monotonic clock for cooldown deadline.

Aliases (required):
  is_entry_blocked() -> bool
  is_blocked()       -> bool   (alias)
  update(mid_price)  -> None
  reset()            -> None
"""

import math
import threading
import time
from collections import deque

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 20              # rolling price window
MAX_VOLATILITY: float = 0.002     # max per-tick log-return std dev (0.2%)
COOLDOWN_SECONDS: float = 60.0   # block duration after breach
MIN_SAMPLES: int = 5              # minimum prices before blocking activates


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prices: deque = deque(maxlen=WINDOW_SIZE)
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_std(prices) -> float:
    """Compute sample std dev of log-returns. Returns NaN when insufficient."""
    p = list(prices)
    if len(p) < 2:
        return float("nan")
    returns = []
    for i in range(1, len(p)):
        if p[i - 1] <= 0.0 or p[i] <= 0.0:
            return float("nan")
        lr = math.log(p[i] / p[i - 1])
        returns.append(lr)
    n = len(returns)
    if n < 1:
        return float("nan")
    mean = sum(returns) / n
    if n == 1:
        return 0.0
    variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
    return math.sqrt(variance)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update(mid_price) -> None:
    """Record a new mid-price tick.

    Args:
        mid_price: Current mid-price (finite positive number, not bool).
    """
    if isinstance(mid_price, bool):
        return
    if not isinstance(mid_price, (int, float)):
        return
    if math.isnan(mid_price) or math.isinf(mid_price):
        return
    if mid_price <= 0.0:
        return

    global _blocked_until
    with _lock:
        _prices.append(float(mid_price))
        if len(_prices) < MIN_SAMPLES:
            return
        std = _compute_std(_prices)
        if math.isnan(std):
            return
        if std >= MAX_VOLATILITY:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def is_entry_blocked() -> bool:
    """Return True when session volatility has breached the threshold."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Clear all state (use between tests or sessions)."""
    global _blocked_until
    with _lock:
        _prices.clear()
        _blocked_until = 0.0
