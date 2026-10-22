"""
wave251_trade_run_sign_inversion_chaos_guard.py
-------------------------------------------------
Guard: Microstructure Trade Run Sign Inversion & Ping-Pong Chaos Guard

Monitors high-frequency trade sign inversion rate and acute alternating whipsaw streaks
(Engle & Russell 1998; Almgren & Chriss 2000; Hasbrouck 2007):
    Trade Direction:         s_t in {+1 (buy), -1 (sell)}
    Sign Inversion:          I_t = 1 if s_t != s_{t-1} else 0
    Inversion Frequency:     R_{inv} = (1 / (N - 1)) * \\sum_{t=2}^N I_t
    Alternating Streak:      L_{alt} = length of consecutive sign-inverting trade sequence (+-+-+-+-)

In ordinary directional trend or diffusive double-auction markets:
    - Trade flow displays moderate sign clustering or continuation:
      R_{inv} ~ 0.40 - 0.55 across rolling N=25 trades, with L_{alt} <= 4.

During toxic HFT ping-pong chop, predatory front-running whipsaw, or algorithmic cross-market sniping:
    - Consecutive fills violently alternate between bid and ask touch without net displacement:
        1) Severe Ping-Pong Inversion Chaos:
           R_{inv} >= MAX_INVERSION_RATE (default: 0.85 or 85% alternating) over rolling N >= 15 trades.
        2) Acute Alternating Inversion Streak:
           L_{alt} >= MAX_ALTERNATING_STREAK (default: 8 consecutive reversals).

Attempting to scalp or place resting orders into high-frequency ping-pong chaos guarantees
double-sided spread churn, rapid stop-loss whipsaw, and severe execution drag.

When ping-pong inversion chaos or acute alternating streak is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade direction via record_trade(side, ts=None).
- Maintains rolling history of WINDOW_SIZE = 25 trade signs.
- Minimum MIN_SAMPLES = 15 trades required for rolling inversion rate evaluation.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or invalid side representations are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade(side, ts=None)                                                                  -> None
  update(side, ts=None)                                                                        -> None   (alias)
  get_inversion_metrics()                                                                      -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any, Union

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WINDOW_SIZE: int = 25
MIN_SAMPLES: int = 15
MAX_INVERSION_RATE: float = 0.85       # 85% trade sign inversion rate
MAX_ALTERNATING_STREAK: int = 8        # 8 consecutive alternating reversals
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_trades_history = collections.deque(maxlen=WINDOW_SIZE)  # elements: +1 or -1
_current_alternating_streak: int = 0
_latest_inversion_rate: float = 0.50
_blocked_until: float = 0.0


def _parse_side(val: Any) -> Optional[int]:
    """Parse trade side into +1 (buy) or -1 (sell). Returns None if invalid."""
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        if math.isnan(val) or math.isinf(val):
            return None
        if val > 0:
            return 1
        elif val < 0:
            return -1
        return None
    if isinstance(val, str):
        s = val.strip().lower()
        if s in ("buy", "b", "long", "+1", "1"):
            return 1
        elif s in ("sell", "s", "short", "-1"):
            return -1
    return None


def record_trade(
    side: Union[str, int, float],
    ts: Optional[float] = None,
) -> None:
    """
    Ingest a trade side and evaluate inversion frequency and alternating streaks.
    """
    global _current_alternating_streak, _latest_inversion_rate, _blocked_until

    s = _parse_side(side)
    if s is None:
        return

    with _lock:
        # Check alternating streak against previous trade
        if len(_trades_history) > 0:
            prev_s = _trades_history[-1]
            if s != prev_s:
                _current_alternating_streak += 1
            else:
                _current_alternating_streak = 1
        else:
            _current_alternating_streak = 1

        _trades_history.append(s)

        # Update inversion metrics
        n = len(_trades_history)
        if n >= 2:
            inversions = sum(
                1 for i in range(1, n) if _trades_history[i] != _trades_history[i - 1]
            )
            _latest_inversion_rate = inversions / (n - 1)

        # Condition 1: Acute alternating inversion streak
        if _current_alternating_streak >= MAX_ALTERNATING_STREAK:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 2: Rolling inversion rate over N >= MIN_SAMPLES
        if n >= MIN_SAMPLES and _latest_inversion_rate >= MAX_INVERSION_RATE:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(
    side: Union[str, int, float],
    ts: Optional[float] = None,
) -> None:
    """Alias for record_trade()."""
    record_trade(side, ts)


def is_entry_blocked() -> bool:
    """Check if new entries are blocked by trade sign inversion chaos."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_inversion_metrics() -> Dict[str, float]:
    """Retrieve current inversion metrics."""
    with _lock:
        return {
            "inversion_rate": _latest_inversion_rate,
            "alternating_streak": float(_current_alternating_streak),
        }


def get_status() -> Dict[str, Any]:
    """Retrieve complete guard status."""
    with _lock:
        now = time.monotonic()
        blocked = now < _blocked_until
        remaining = max(0.0, _blocked_until - now) if blocked else 0.0
        return {
            "guard_name": "wave251_trade_run_sign_inversion_chaos_guard",
            "is_blocked": blocked,
            "blocked_seconds_remaining": remaining,
            "sample_count": len(_trades_history),
            "inversion_rate": _latest_inversion_rate,
            "alternating_streak": _current_alternating_streak,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "max_inversion_rate": MAX_INVERSION_RATE,
            "max_alternating_streak": MAX_ALTERNATING_STREAK,
        }


def reset() -> None:
    """Reset all guard state and clear cooldowns."""
    global _current_alternating_streak, _latest_inversion_rate, _blocked_until

    with _lock:
        _trades_history.clear()
        _current_alternating_streak = 0
        _latest_inversion_rate = 0.50
        _blocked_until = 0.0
