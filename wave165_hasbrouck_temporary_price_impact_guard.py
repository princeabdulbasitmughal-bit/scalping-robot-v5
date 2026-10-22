"""
wave165_hasbrouck_temporary_price_impact_guard.py
-------------------------------------------------
Guard: Hasbrouck Information Share & Temporary Price Impact Decay Guard

Decomposes trade execution price impact into permanent vs temporary components (Hasbrouck, 1991):
    Total Impact = |Trade_Price - Midpoint_0|
    Permanent Impact = |Midpoint_tau - Midpoint_0|
    Temporary Impact = max(0.0, Total Impact - Permanent Impact)

Permanent impact reflects genuine price discovery and informed order flow.
Temporary price impact represents the transient liquidity concession and inventory friction
extracted by market makers when an order sweeps a thin order book.
When temporary price impact surges (I_temp >= MAX_TEMP_IMPACT, default: 0.0020 / 20 bps),
it reveals that trades are executing into transient liquidity holes and paying prohibitive
inventory friction that immediately snaps back, generating instantaneous adverse slippage.
If I_temp >= 0.0020 or rolling average >= 0.0020, entries are blocked for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Records trade execution against prevailing midpoint, or direct resolution with subsequent midpoint.
- Computes Total Impact and resolves Permanent and Temporary Impact.
- Maintains rolling window (WINDOW_SIZE = 10 impact measurements).
- If latest I_temp >= MAX_TEMP_IMPACT (0.0020) OR rolling average I_temp >= MAX_TEMP_IMPACT:
    blocks entries for COOLDOWN_SECONDS (45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive prices are ignored.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_impact(trade_price, initial_mid, subsequent_mid, ts=None) -> None
  record_execution(trade_price, initial_mid, ts=None)      -> None
  record_midpoint(mid_price, ts=None)                      -> None
  update(trade_price, initial_mid, subsequent_mid=None, ts=None) -> None (alias)
  get_temporary_impact()                                   -> float
  reset()                                                  -> None
"""

import collections
import math
import threading
import time
from typing import Deque, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_TEMP_IMPACT: float = 0.0020    # 20 bps temporary price concession triggers liquidity hole guard
WINDOW_SIZE: int = 10              # Rolling window of trade executions
HORIZON_TICKS: int = 5             # Number of midpoint ticks to measure impact decay
COOLDOWN_SECONDS: float = 45.0     # Block duration in seconds on transient liquidity hole


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
# Each pending item: [trade_price, initial_mid, ticks_remaining]
_pending: List[List[float]] = []
_history: Deque[float] = collections.deque(maxlen=WINDOW_SIZE)
_latest_temp_impact: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_impact(trade_price, initial_mid, subsequent_mid, ts=None) -> None:
    """Directly record an execution with known initial and subsequent post-trade midpoints."""
    for val in (trade_price, initial_mid, subsequent_mid):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return
        if math.isnan(val) or math.isinf(val):
            return

    tp = float(trade_price)
    m0 = float(initial_mid)
    m_tau = float(subsequent_mid)

    if tp <= 0.0 or m0 <= 0.0 or m_tau <= 0.0:
        return

    tot_impact = abs(tp - m0)
    perm_impact = abs(m_tau - m0)
    temp_impact = max(0.0, tot_impact - perm_impact)

    global _latest_temp_impact, _blocked_until
    with _lock:
        _latest_temp_impact = temp_impact
        _history.append(temp_impact)

        avg_temp = sum(_history) / len(_history)
        if temp_impact >= MAX_TEMP_IMPACT or avg_temp >= MAX_TEMP_IMPACT:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def record_execution(trade_price, initial_mid, ts=None) -> None:
    """Register an execution to resolve temporary impact against subsequent midpoints."""
    for val in (trade_price, initial_mid):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return
        if math.isnan(val) or math.isinf(val):
            return

    tp = float(trade_price)
    m0 = float(initial_mid)

    if tp <= 0.0 or m0 <= 0.0:
        return

    with _lock:
        _pending.append([tp, m0, float(HORIZON_TICKS)])


def record_midpoint(mid_price, ts=None) -> None:
    """Ingest a new midpoint update to age pending executions and resolve decay."""
    if isinstance(mid_price, bool) or not isinstance(mid_price, (int, float)):
        return
    if math.isnan(mid_price) or math.isinf(mid_price) or mid_price <= 0.0:
        return

    m = float(mid_price)

    global _latest_temp_impact, _blocked_until
    with _lock:
        resolved = []
        remaining = []

        for item in _pending:
            item[2] -= 1.0
            if item[2] <= 0.0:
                resolved.append(item)
            else:
                remaining.append(item)

        _pending.clear()
        _pending.extend(remaining)

        for item in resolved:
            tp, m0, _ = item
            tot_impact = abs(tp - m0)
            perm_impact = abs(m - m0)
            temp_impact = max(0.0, tot_impact - perm_impact)

            _latest_temp_impact = temp_impact
            _history.append(temp_impact)

            avg_temp = sum(_history) / len(_history)
            if temp_impact >= MAX_TEMP_IMPACT or avg_temp >= MAX_TEMP_IMPACT:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def update(trade_price, initial_mid, subsequent_mid=None, ts=None) -> None:
    """Unified alias for recording execution or direct impact."""
    if subsequent_mid is not None:
        record_impact(trade_price, initial_mid, subsequent_mid, ts=ts)
    else:
        record_execution(trade_price, initial_mid, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if temporary price impact has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_temporary_impact() -> float:
    """Return the most recently calculated temporary price impact."""
    with _lock:
        return _latest_temp_impact


def reset() -> None:
    """Reset pending trades, impact history, latest impact, and active cooldown."""
    global _latest_temp_impact, _blocked_until
    with _lock:
        _pending.clear()
        _history.clear()
        _latest_temp_impact = 0.0
        _blocked_until = 0.0
