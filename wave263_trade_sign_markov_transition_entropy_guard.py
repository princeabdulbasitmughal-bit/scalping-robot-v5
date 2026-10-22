"""
wave263_trade_sign_markov_transition_entropy_guard.py
------------------------------------------------------
Guard: Trade Sign Markov Transition & Run Persistence Guard

Monitors empirical trade sign sequence dynamics, Markov chain transition probabilities, and run persistence
(Hasbrouck 1991; Bouchaud, Mezard & Potters 2004; Allez & Bouchaud 2014):
    Trade Sign:                 epsilon_t in {+1 (Buy), -1 (Sell)}
    Transition Pairs:           (epsilon_{t-1}, epsilon_t) in {(+1, +1), (+1, -1), (-1, -1), (-1, +1)}
    Run Persistence Ratio:      P_{persist} = (N_{++} + N_{--}) / N_{trans}
    Directional Run Streak:     L_{streak} = consecutive identical trade signs

Under balanced double-auction order flow without asymmetric information:
    - Order flow signs follow a near-symmetric memoryless process: P_{persist} ~ 0.45 - 0.55.
    - Directional streaks are short (L_{streak} <= 4 consecutive buys or sells).

During aggressive algorithmic queue sweeping, iceberg execution, or institutional momentum runs:
    - Trade signs exhibit overwhelming serial continuation:
        1) Trade Sign Markov Persistence Herding:
           P_{persist} >= MAX_PERSISTENCE_RATIO (default: 0.82) over rolling N >= MIN_TRADES (20 trades).
        2) Acute Directional Sign Streak:
           L_{streak} >= MAX_ACUTE_STREAK (default: 8 consecutive identical signs).

Taking opposite positions during high-persistence trade runs or acute directional streaks guarantees
immediate adverse execution, front-running, and negative alpha.

When Markov sign persistence or an acute directional streak is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade signs via record_trade_sign(sign, ts=None) or
  direct persistence metrics via record_persistence(persistence_ratio, streak=None, sample_count=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 25 trade signs.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or zero trade signs are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade_sign(sign, ts=None)                                                             -> None
  record_persistence(persistence_ratio, streak=None, sample_count=None, ts=None)               -> None
  update(sign, ts=None)                                                                        -> None   (alias)
  get_markov_metrics()                                                                         -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any, Deque

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 25                   # 25 trade signs rolling window
MIN_TRADES: int = 20                    # 20 trade signs minimum for persistence evaluation
MAX_PERSISTENCE_RATIO: float = 0.82     # 82% persistence ratio indicates predatory sweep
MAX_ACUTE_STREAK: int = 8               # 8 consecutive identical signs indicates acute run
COOLDOWN_SECONDS: float = 45.0          # 45.0s block duration

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_signs_history: Deque[int] = collections.deque(maxlen=WINDOW_SIZE)
_current_streak_sign: Optional[int] = None
_current_streak_len: int = 0
_latest_persistence_ratio: float = 0.50
_blocked_until: float = 0.0


def _is_valid_numeric(val: Any) -> bool:
    """Validate value is a finite numeric float or int (not bool)."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return True


def record_persistence(
    persistence_ratio: float,
    streak: Optional[int] = None,
    sample_count: Optional[int] = None,
    ts: Optional[float] = None,
) -> None:
    """
    Directly ingest precomputed Markov persistence ratio and directional streak.
    """
    global _latest_persistence_ratio, _current_streak_len, _blocked_until

    if not _is_valid_numeric(persistence_ratio):
        return

    p = max(0.0, min(1.0, float(persistence_ratio)))
    stk = int(streak) if (streak is not None and isinstance(streak, int) and not isinstance(streak, bool) and streak > 0) else 0
    n = int(sample_count) if (sample_count is not None and isinstance(sample_count, int) and not isinstance(sample_count, bool) and sample_count > 0) else 25

    with _lock:
        _latest_persistence_ratio = p
        if stk > 0:
            _current_streak_len = stk

        # Condition 2: Acute Directional Sign Streak
        if stk >= MAX_ACUTE_STREAK:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 1: Trade Sign Markov Persistence Herding
        if p >= MAX_PERSISTENCE_RATIO and n >= MIN_TRADES:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def record_trade_sign(sign: int, ts: Optional[float] = None) -> None:
    """
    Ingest a single trade sign (+1 for Buy, -1 for Sell).
    """
    global _signs_history, _current_streak_sign, _current_streak_len
    global _latest_persistence_ratio, _blocked_until

    if not _is_valid_numeric(sign):
        return

    s_val = int(sign)
    if s_val == 0:
        return
    s = 1 if s_val > 0 else -1

    with _lock:
        # Update directional streak
        if _current_streak_sign == s:
            _current_streak_len += 1
        else:
            _current_streak_sign = s
            _current_streak_len = 1

        # Condition 2: Acute Directional Sign Streak
        if _current_streak_len >= MAX_ACUTE_STREAK:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            _signs_history.append(s)
            return

        _signs_history.append(s)

        if len(_signs_history) >= MIN_TRADES:
            # Count Markov transitions
            n_trans = len(_signs_history) - 1
            if n_trans > 0:
                persist_count = 0
                for i in range(1, len(_signs_history)):
                    if _signs_history[i] == _signs_history[i - 1]:
                        persist_count += 1
                persist_ratio = persist_count / float(n_trans)
                _latest_persistence_ratio = persist_ratio

                # Condition 1: Trade Sign Markov Persistence Herding
                if persist_ratio >= MAX_PERSISTENCE_RATIO:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                    return


def update(sign: int, ts: Optional[float] = None) -> None:
    """Module alias for record_trade_sign."""
    record_trade_sign(sign, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if entry is currently blocked by Markov persistence guard."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked."""
    return is_entry_blocked()


def get_markov_metrics() -> Dict[str, Any]:
    """Return dictionary of current Markov transition metrics."""
    with _lock:
        return {
            "persistence_ratio": round(_latest_persistence_ratio, 4),
            "current_streak": _current_streak_len,
            "current_streak_sign": _current_streak_sign,
            "sample_count": len(_signs_history),
            "max_persistence_ratio": MAX_PERSISTENCE_RATIO,
            "max_acute_streak": MAX_ACUTE_STREAK,
            "is_blocked": is_entry_blocked(),
        }


def get_status() -> Dict[str, Any]:
    """Return complete status dictionary."""
    with _lock:
        remaining_cd = max(0.0, _blocked_until - time.monotonic())
        metrics = get_markov_metrics()
        metrics["cooldown_remaining_sec"] = round(remaining_cd, 2)
        return metrics


def reset() -> None:
    """Reset all state to initial defaults."""
    global _signs_history, _current_streak_sign, _current_streak_len
    global _latest_persistence_ratio, _blocked_until
    with _lock:
        _signs_history.clear()
        _current_streak_sign = None
        _current_streak_len = 0
        _latest_persistence_ratio = 0.50
        _blocked_until = 0.0
