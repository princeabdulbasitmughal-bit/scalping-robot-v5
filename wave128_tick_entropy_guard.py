"""
wave128_tick_entropy_guard.py
------------------------------
Guard: Microstructure Tick Direction Shannon Entropy Guard

Monitors the randomness and informational entropy of discrete price changes
(uptick, uptick, flat, downtick) across a rolling window of recent ticks.

Healthy, deep, and liquid markets exhibit dispersed, high-entropy micro-movements.
When spoofing, repetitive quoting cycles, quote stuffing, or liquidity freeze
occurs, price direction transitions collapse into low-entropy states (e.g. repeated
all-flat quotes, or repetitive alternating tick loops).

Logic:
- Stores the last WINDOW_SIZE (default: 20) tick direction states:
    +1 (price increased)
    -1 (price decreased)
     0 (price unchanged)
- Once at least MIN_TICKS (default: 15) directional transitions are recorded:
    p_up   = count(+1) / N
    p_down = count(-1) / N
    p_flat = count(0)  / N
    Shannon Entropy H = - sum_{p > 0}(p * log2(p))  in bits
- If H < MIN_SHANNON_ENTROPY (default: 0.60 bits), market liquidity is deemed
  unnatural, pinned, or repetitive:
    blocks entries for COOLDOWN_SECONDS (default: 45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Fail-closed: invalid, non-numeric, boolean, NaN, Inf, non-positive price values ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()             -> bool
  is_blocked()                   -> bool   (alias)
  record_tick(price, ts=None)    -> None
  update(price, ts=None)         -> None   (alias)
  get_current_entropy()          -> float
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
WINDOW_SIZE: int = 20                  # rolling tick direction buffer
MIN_TICKS: int = 15                    # minimum observations to evaluate entropy
MIN_SHANNON_ENTROPY: float = 0.60      # minimum bits (max is log2(3) ~= 1.585 bits)
COOLDOWN_SECONDS: float = 45.0         # duration of entry block on low entropy


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_directions = collections.deque(maxlen=WINDOW_SIZE)
_prev_price: Optional[float] = None
_blocked_until: float = 0.0
_last_entropy: float = 1.585           # default to theoretical maximum


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_tick(price, ts=None) -> None:
    """Record a tick price and compute rolling Shannon direction entropy."""
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return
    if math.isnan(price) or math.isinf(price) or price <= 0.0:
        return

    curr_p = float(price)

    global _prev_price, _blocked_until, _last_entropy
    with _lock:
        if _prev_price is None:
            _prev_price = curr_p
            return

        diff = curr_p - _prev_price
        if diff > 1e-9:
            direction = 1
        elif diff < -1e-9:
            direction = -1
        else:
            direction = 0

        _directions.append(direction)
        _prev_price = curr_p

        if len(_directions) >= MIN_TICKS:
            n = len(_directions)
            c_up = sum(1 for d in _directions if d == 1)
            c_down = sum(1 for d in _directions if d == -1)
            c_flat = sum(1 for d in _directions if d == 0)

            entropy = 0.0
            for count in (c_up, c_down, c_flat):
                if count > 0:
                    p = count / n
                    entropy -= p * math.log2(p)

            _last_entropy = entropy

            if entropy < MIN_SHANNON_ENTROPY:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(price, ts=None) -> None:
    """Alias for record_tick()."""
    record_tick(price, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if low tick entropy has activated a protective block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_current_entropy() -> float:
    """Return the most recently computed Shannon entropy in bits."""
    with _lock:
        return _last_entropy


def reset() -> None:
    """Reset all directional history, entropy metrics, and active block."""
    global _prev_price, _blocked_until, _last_entropy
    with _lock:
        _directions.clear()
        _prev_price = None
        _blocked_until = 0.0
        _last_entropy = 1.585
