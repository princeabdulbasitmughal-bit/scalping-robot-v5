"""
wave122_tick_reversal_intensity_guard.py
------------------------------------------
Guard: High-Frequency Reversal Intensity (Ping-Pong Chop) Guard

Monitors micro-structure turbulence by tracking the frequency of immediate directional
flips (up-tick to down-tick or down-tick to up-tick) across consecutive ticks.
High flip rates (ping-pong market) result in severe scalping slippage and spread losses.

Logic:
- Records directional moves: +1 (up), -1 (down).
- Evaluates whether each move reverses the previous directional move.
- Maintains a rolling deque of last WINDOW_SIZE directional transitions (1 for reversal, 0 for continuation).
- When len(deque) >= MIN_SAMPLES (default: 10), computes reversal rate = reversals / total.
- If reversal_rate >= MAX_REVERSAL_RATE (default: 0.70, i.e. 70% immediate flips),
  blocks entries for COOLDOWN_SECONDS (default: 45.0s).
- Flat ticks (equal price) are ignored.
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
WINDOW_SIZE: int = 20              # rolling window of directional transitions
MIN_SAMPLES: int = 10              # minimum transitions before evaluation
MAX_REVERSAL_RATE: float = 0.70    # 70% reversal rate threshold
COOLDOWN_SECONDS: float = 45.0     # duration of block on ping-pong chop


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_last_price: float = -1.0
_last_direction: int = 0           # +1 for up, -1 for down
_reversals: deque = deque(maxlen=WINDOW_SIZE)
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update(price) -> None:
    """Record a price tick and evaluate directional reversal frequency."""
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return

    p = float(price)
    now = time.monotonic()

    global _last_price, _last_direction, _blocked_until
    with _lock:
        if _last_price <= 0.0:
            _last_price = p
            return

        if p > _last_price:
            current_dir = 1
        elif p < _last_price:
            current_dir = -1
        else:
            return  # flat tick ignored

        _last_price = p

        if _last_direction != 0:
            is_flip = 1 if (current_dir != _last_direction) else 0
            _reversals.append(is_flip)

            if len(_reversals) >= MIN_SAMPLES:
                reversal_rate = sum(_reversals) / len(_reversals)
                if reversal_rate >= MAX_REVERSAL_RATE:
                    _blocked_until = now + COOLDOWN_SECONDS

        _last_direction = current_dir


def is_entry_blocked() -> bool:
    """Return True if high reversal intensity (ping-pong chop) is blocking entries."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Clear tick transition history and reset block."""
    global _last_price, _last_direction, _blocked_until
    with _lock:
        _last_price = -1.0
        _last_direction = 0
        _reversals.clear()
        _blocked_until = 0.0
