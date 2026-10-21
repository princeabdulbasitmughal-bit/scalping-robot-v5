"""
wave106_overnight_position_guard.py
--------------------------------------
Guard: Overnight Position Guard

Blocks new entries during a configurable window around the daily rollover /
overnight period to avoid holding through swap charges and thin liquidity.
Also blocks opening NEW positions when an existing position has been open
across midnight (i.e., held overnight), as these positions carry additional
risk from gap moves.

Logic:
- Two mechanisms, either of which triggers a block:
  1. TIME WINDOW: Blocks when current UTC time is within BLOCK_BEFORE_CLOSE
     minutes of 21:00 UTC or within BLOCK_AFTER_OPEN minutes of 21:00 UTC
     (configurable rollover hour). Default: 15 min before + 15 min after.
  2. OVERNIGHT FLAG: When flag_overnight() is called (e.g., detected an open
     position that survived midnight), blocks for OVERNIGHT_COOLDOWN_SECONDS
     (default: 300s = 5 minutes).
- Fail-closed: corrupted inputs to flag_overnight ignored (guard stays safe).
- Thread-safe: threading.RLock() on all shared state.
- Monotonic clock for overnight cooldown; UTC datetime for window check.

Aliases (required):
  is_entry_blocked()   -> bool
  is_blocked()         -> bool   (alias)
  flag_overnight()     -> None   (signal that a position survived overnight)
  update()             -> None   (alias for flag_overnight)
  reset()              -> None
"""

import math
import threading
import time
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ROLLOVER_HOUR_UTC: int = 21           # broker rollover hour (21:00 UTC)
BLOCK_BEFORE_CLOSE_MIN: int = 15      # block N minutes before rollover
BLOCK_AFTER_OPEN_MIN: int = 15        # block N minutes after rollover
OVERNIGHT_COOLDOWN_SECONDS: float = 300.0  # 5 min block after overnight flag


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_overnight_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _in_rollover_window() -> bool:
    """Return True if current UTC time is within the rollover block window."""
    now_utc = datetime.now(tz=timezone.utc)
    hour = now_utc.hour
    minute = now_utc.minute
    # Minutes from midnight expressed as total minutes
    now_min = hour * 60 + minute
    rollover_min = ROLLOVER_HOUR_UTC * 60
    block_start = rollover_min - BLOCK_BEFORE_CLOSE_MIN
    block_end = rollover_min + BLOCK_AFTER_OPEN_MIN
    return block_start <= now_min < block_end


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def flag_overnight() -> None:
    """Signal that a position was detected as having survived overnight.
    Triggers a cooldown block for OVERNIGHT_COOLDOWN_SECONDS.
    """
    global _overnight_blocked_until
    with _lock:
        _overnight_blocked_until = time.monotonic() + OVERNIGHT_COOLDOWN_SECONDS


def update() -> None:
    """Alias for flag_overnight()."""
    flag_overnight()


def is_entry_blocked() -> bool:
    """Return True when either the rollover window is active OR overnight
    cooldown has not expired.
    """
    with _lock:
        if time.monotonic() < _overnight_blocked_until:
            return True
    return _in_rollover_window()


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def reset() -> None:
    """Clear overnight cooldown (use between tests or sessions)."""
    global _overnight_blocked_until
    with _lock:
        _overnight_blocked_until = 0.0
