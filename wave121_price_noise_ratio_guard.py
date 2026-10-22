"""
wave121_price_noise_ratio_guard.py
------------------------------------
Guard: Price Noise & Market Efficiency Ratio Guard

Monitors micro-structure efficiency by calculating the Kaufman Efficiency Ratio (ER)
over a rolling price window: ER = Net Directional Displacement / Total Price Path.
Low ER values indicate choppy, noisy, low-conviction price churn that generates
excessive spread losses and whipsaw executions.

Logic:
- Maintains a rolling deque of last WINDOW_SIZE mid-price ticks.
- Computes:
    net_change = abs(p[-1] - p[0])
    total_path = sum(abs(p[i] - p[i-1]) for i in range(1, len(p)))
    efficiency_ratio = net_change / total_path if total_path > 0 else 0.0
- If efficiency_ratio < MIN_EFFICIENCY_RATIO (default: 0.15, i.e. 85%+ noise churn),
  blocks entries for COOLDOWN_SECONDS (default: 45.0s).
- Warmup: requires full WINDOW_SIZE (default: 20 ticks) before evaluation.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()      -> bool
  is_blocked()            -> bool   (alias)
  update(price)           -> None
  reset()                 -> None
"""

import math
import threading
import time
from collections import deque

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 20              # rolling price tick window
MIN_EFFICIENCY_RATIO: float = 0.15 # minimum directional efficiency threshold
COOLDOWN_SECONDS: float = 45.0     # duration of block on noisy chop conditions


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_prices: deque = deque(maxlen=WINDOW_SIZE)
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update(price) -> None:
    """Record a price tick and evaluate efficiency ratio."""
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return

    p = float(price)
    now = time.monotonic()

    global _blocked_until
    with _lock:
        _prices.append(p)
        if len(_prices) == WINDOW_SIZE:
            net_change = abs(_prices[-1] - _prices[0])
            total_path = sum(abs(_prices[i] - _prices[i - 1]) for i in range(1, len(_prices)))
            if total_path > 0.0:
                er = net_change / total_path
                if er < MIN_EFFICIENCY_RATIO:
                    _blocked_until = now + COOLDOWN_SECONDS


def is_entry_blocked() -> bool:
    """Return True if price noise / low efficiency is currently blocking entries."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Clear prices and reset active block."""
    global _blocked_until
    with _lock:
        _prices.clear()
        _blocked_until = 0.0
