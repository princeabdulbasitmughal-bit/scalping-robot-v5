"""
wave102_spread_spike_guard.py
--------------------------------
Guard: Spread Spike Guard

Blocks new entries when the current bid-ask spread spikes significantly
above the rolling average spread, indicating thin liquidity or a
market-maker pullback event.

Logic:
- Maintains a rolling deque of the last WINDOW_SIZE spread samples (in pips).
- Computes rolling average of the window.
- If current_spread >= avg_spread * SPIKE_MULTIPLIER (default: 3.0x),
  entry is blocked for COOLDOWN_SECONDS (default: 45s).
- Warmup: MIN_SAMPLES spread values required before blocking can activate.
- Fail-closed: bool/NaN/Inf/negative/zero spread silently ignored.
- Thread-safe: threading.RLock() on all shared state.
- Monotonic clock for cooldown.

Aliases (required):
  is_entry_blocked()      -> bool
  is_blocked()            -> bool   (alias)
  update(spread_pips)     -> None
  reset()                 -> None
"""

import math
import threading
import time
from collections import deque

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 20          # rolling spread window
SPIKE_MULTIPLIER: float = 3.0  # current spread must be >= N * avg to block
COOLDOWN_SECONDS: float = 45.0 # block duration after spike
MIN_SAMPLES: int = 5           # warmup: minimum samples before blocking


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_spreads: deque = deque(maxlen=WINDOW_SIZE)
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update(spread_pips) -> None:
    """Record a new spread sample and check for spikes.

    Args:
        spread_pips: Current bid-ask spread in pips (finite positive, not bool).
    """
    if isinstance(spread_pips, bool):
        return
    if not isinstance(spread_pips, (int, float)):
        return
    if math.isnan(spread_pips) or math.isinf(spread_pips):
        return
    if spread_pips <= 0.0:
        return

    global _blocked_until
    sp = float(spread_pips)

    with _lock:
        _spreads.append(sp)

        if len(_spreads) < MIN_SAMPLES:
            return

        avg = sum(_spreads) / len(_spreads)
        if avg <= 0.0:
            return

        if sp >= avg * SPIKE_MULTIPLIER:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def is_entry_blocked() -> bool:
    """Return True when a spread spike was recently detected."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Clear all state (use between tests or sessions)."""
    global _blocked_until
    with _lock:
        _spreads.clear()
        _blocked_until = 0.0
