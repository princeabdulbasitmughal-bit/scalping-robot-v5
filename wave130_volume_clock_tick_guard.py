"""
wave130_volume_clock_tick_guard.py
-----------------------------------
Guard: Volume Clock Trade Volume Acceleration Guard

Measures trading activity in volume time (cumulative traded volume) rather than
calendar seconds alone. A sudden exponential acceleration in traded contract volume
over a micro-window signals institutional block liquidation, iceberg sweeps, or
stop-loss cascades.

Logic:
- Records timestamped volume executions (lots or contracts).
- Evaluates recent short-term volume rate (volume accumulated over past SHORT_WINDOW_SEC, default: 10.0s)
  relative to the baseline volume rate over BASELINE_WINDOW_SEC (default: 60.0s).
- Dynamically scales baseline window by elapsed observation history to avoid false positives during warm-up.
- Computes volume surge ratio:
    surge_ratio = short_rate / baseline_rate
- If surge_ratio >= MAX_VOLUME_SURGE_RATIO (default: 4.0x) and minimum baseline
  volume is observed (MIN_BASELINE_VOLUME = 5.0 lots):
    blocks entries for COOLDOWN_SECONDS (default: 45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Fail-closed: non-numeric, boolean, NaN, Inf, and non-positive volume inputs ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()                    -> bool
  is_blocked()                          -> bool   (alias)
  record_volume(volume, ts=None)        -> None
  update(volume, ts=None)               -> None   (alias)
  get_volume_surge_ratio()              -> float
  reset()                               -> None
"""

import collections
import math
import threading
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SHORT_WINDOW_SEC: float = 10.0         # micro window for instantaneous rate
BASELINE_WINDOW_SEC: float = 60.0      # reference baseline window
MAX_VOLUME_SURGE_RATIO: float = 4.0    # 4x volume acceleration triggers block
MIN_BASELINE_VOLUME: float = 5.0       # minimum lots required in baseline to evaluate ratio
COOLDOWN_SECONDS: float = 45.0         # cooldown on volume shock


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
# entries stored as tuples: (monotonic_timestamp, volume)
_history = collections.deque()
_blocked_until: float = 0.0
_last_surge_ratio: float = 1.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_volume(volume, ts=None) -> None:
    """Record volume execution and evaluate volume clock acceleration."""
    if isinstance(volume, bool) or not isinstance(volume, (int, float)):
        return
    if math.isnan(volume) or math.isinf(volume) or volume <= 0.0:
        return

    vol = float(volume)
    now = float(ts) if (ts is not None and isinstance(ts, (int, float)) and not isinstance(ts, bool)) else time.monotonic()

    global _blocked_until, _last_surge_ratio
    with _lock:
        _history.append((now, vol))

        # Evict records older than BASELINE_WINDOW_SEC
        cutoff = now - BASELINE_WINDOW_SEC
        while _history and _history[0][0] < cutoff:
            _history.popleft()

        elapsed_base = now - _history[0][0]
        baseline_vol = sum(v for t, v in _history)

        if elapsed_base >= SHORT_WINDOW_SEC and baseline_vol >= MIN_BASELINE_VOLUME:
            short_cutoff = now - SHORT_WINDOW_SEC
            short_vol = sum(v for t, v in _history if t >= short_cutoff)

            eff_base_window = min(BASELINE_WINDOW_SEC, elapsed_base)
            short_rate = short_vol / SHORT_WINDOW_SEC
            base_rate = baseline_vol / eff_base_window

            if base_rate > 1e-9:
                surge = short_rate / base_rate
                _last_surge_ratio = surge
                if surge >= MAX_VOLUME_SURGE_RATIO:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(volume, ts=None) -> None:
    """Alias for record_volume()."""
    record_volume(volume, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if volume acceleration has activated an entry block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_volume_surge_ratio() -> float:
    """Return the most recently computed volume surge ratio."""
    with _lock:
        return _last_surge_ratio


def reset() -> None:
    """Reset all volume history, surge metrics, and active block."""
    global _blocked_until, _last_surge_ratio
    with _lock:
        _history.clear()
        _blocked_until = 0.0
        _last_surge_ratio = 1.0
