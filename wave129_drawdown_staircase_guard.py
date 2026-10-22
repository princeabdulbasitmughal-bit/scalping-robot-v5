"""
wave129_drawdown_staircase_guard.py
------------------------------------
Guard: Equity Drawdown Staircase Guard (Cascading Lower Recovery Peaks)

Detects persistent degradation in the account equity curve characterized by
a sequence of cascading lower recovery highs (staircase breakdown pattern).

In hostile, one-way adverse regimes, equity frequently produces micro-rebounds
that fail to recover previous peaks, establishing successively lower local highs:
  Peak 1 > Peak 2 > Peak 3 (Staircase breakdown)

Logic:
- Tracks local swing troughs and subsequent recovery rebounds.
- A rebound requires equity to bounce by at least SWING_THRESHOLD_USD (default: 10.0)
  from the local trough.
- When equity subsequently rolls back from its candidate peak by at least
  SWING_ROLLBACK_USD (default: 5.0), the candidate peak is confirmed and stored.
- When MAX_LOWER_PEAKS (default: 3) consecutive swing peaks form strictly descending
  levels (Peak_i < Peak_{i-1}), a staircase breakdown is triggered:
    blocks entries for COOLDOWN_SECONDS (default: 180.0s).
- Recovery breakout: If equity breaks out above the highest peak in the current
  staircase sequence, the staircase is cleared and block lifted.
- Fail-closed: invalid, non-numeric, boolean, NaN, and Inf inputs are ignored.
- Thread-safe: threading.RLock() on all state.

Aliases (required):
  is_entry_blocked()               -> bool
  is_blocked()                     -> bool   (alias)
  record_equity(equity, ts=None)   -> None
  update(equity, ts=None)          -> None   (alias)
  get_staircase_count()            -> int
  reset()                          -> None
"""

import math
import threading
import time
from typing import List, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SWING_THRESHOLD_USD: float = 10.0    # minimum bounce from trough to initiate rebound
SWING_ROLLBACK_USD: float = 5.0      # pullback from peak to confirm swing high
MAX_LOWER_PEAKS: int = 3             # consecutive lower peaks triggering block
COOLDOWN_SECONDS: float = 180.0      # duration of staircase protection block


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_trough: Optional[float] = None
_candidate_peak: Optional[float] = None
_in_rebound: bool = False
_peaks: List[float] = []
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_equity(equity, ts=None) -> None:
    """Record current account equity and evaluate staircase lower peaks."""
    if isinstance(equity, bool) or not isinstance(equity, (int, float)):
        return
    if math.isnan(equity) or math.isinf(equity):
        return

    eq = float(equity)

    global _trough, _candidate_peak, _in_rebound, _peaks, _blocked_until
    with _lock:
        if _trough is None:
            _trough = eq
            _candidate_peak = eq
            return

        # Check breakout above highest recorded peak to clear staircase
        if _peaks and eq > max(_peaks):
            _peaks.clear()
            _blocked_until = 0.0

        if not _in_rebound:
            if eq < _trough:
                _trough = eq
                _candidate_peak = eq
            elif eq - _trough >= SWING_THRESHOLD_USD:
                _in_rebound = True
                _candidate_peak = eq
        else:
            if eq > _candidate_peak:
                _candidate_peak = eq
            elif _candidate_peak - eq >= SWING_ROLLBACK_USD:
                # Confirmed swing peak
                _peaks.append(_candidate_peak)
                _in_rebound = False
                _trough = eq
                _candidate_peak = eq

                # Evaluate last MAX_LOWER_PEAKS
                if len(_peaks) >= MAX_LOWER_PEAKS:
                    recent = _peaks[-MAX_LOWER_PEAKS:]
                    is_descending = all(recent[i] < recent[i - 1] for i in range(1, len(recent)))
                    if is_descending:
                        _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(equity, ts=None) -> None:
    """Alias for record_equity()."""
    record_equity(equity, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if drawdown staircase pattern has triggered protection."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_staircase_count() -> int:
    """Return the number of confirmed consecutive lower peaks currently recorded."""
    with _lock:
        if len(_peaks) < 2:
            return len(_peaks)
        count = 1
        for i in range(len(_peaks) - 1, 0, -1):
            if _peaks[i] < _peaks[i - 1]:
                count += 1
            else:
                break
        return count


def reset() -> None:
    """Reset all swing high tracking, peak history, and active block."""
    global _trough, _candidate_peak, _in_rebound, _peaks, _blocked_until
    with _lock:
        _trough = None
        _candidate_peak = None
        _in_rebound = False
        _peaks.clear()
        _blocked_until = 0.0
