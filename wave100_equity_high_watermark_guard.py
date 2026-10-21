"""
wave100_equity_high_watermark_guard.py
----------------------------------------
Guard: Equity High-Watermark Drawdown Guard

Blocks new entries when the current equity has fallen more than a
configurable percentage below its session high-watermark (peak equity
seen since last reset), indicating the account is in a significant
drawdown event.

Logic:
- Tracks the highest equity seen since last reset (_hwm).
- On every update(), computes drawdown % = (hwm - equity) / hwm * 100.
- If drawdown_pct >= MAX_DRAWDOWN_PCT (default: 5.0%), entry is blocked
  for COOLDOWN_SECONDS (default: 120s).
- Warmup: first update() sets the HWM baseline; no block on first call.
- Fail-closed: bool/NaN/Inf/non-numeric inputs silently ignored.
- Thread-safe: threading.RLock() on all shared state.
- Monotonic clock for cooldown.

Aliases (required):
  is_entry_blocked()   -> bool
  is_blocked()         -> bool   (alias)
  update(equity)       -> None
  reset()              -> None
"""

import math
import threading
import time

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_DRAWDOWN_PCT: float = 5.0      # max drawdown from HWM before blocking (%)
COOLDOWN_SECONDS: float = 120.0    # block duration after breach


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_hwm: float = 0.0            # high-watermark equity
_initialized: bool = False   # True after first valid update
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update(equity) -> None:
    """Record new equity; update HWM; trigger block if drawdown >= threshold.

    Args:
        equity: Current account equity in USD (finite positive, not bool).
    """
    if isinstance(equity, bool):
        return
    if not isinstance(equity, (int, float)):
        return
    if math.isnan(equity) or math.isinf(equity):
        return
    if equity <= 0.0:
        return

    global _hwm, _initialized, _blocked_until
    eq = float(equity)

    with _lock:
        if not _initialized:
            _hwm = eq
            _initialized = True
            return

        # Update high-watermark
        if eq > _hwm:
            _hwm = eq

        # Compute drawdown from HWM
        if _hwm <= 0.0:
            return
        drawdown_pct = (_hwm - eq) / _hwm * 100.0

        if drawdown_pct >= MAX_DRAWDOWN_PCT:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def is_entry_blocked() -> bool:
    """Return True when equity is in significant drawdown from session HWM."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Clear HWM, initialization flag, and block (use between tests/sessions)."""
    global _hwm, _initialized, _blocked_until
    with _lock:
        _hwm = 0.0
        _initialized = False
        _blocked_until = 0.0
