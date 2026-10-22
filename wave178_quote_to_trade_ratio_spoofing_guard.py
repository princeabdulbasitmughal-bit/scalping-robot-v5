"""
wave178_quote_to_trade_ratio_spoofing_guard.py
-----------------------------------------------
Guard: Quote-to-Trade Ratio (QTR) & Layering Spoofing Guard

Monitors the ratio of limit order quote updates (inserts, amends, cancels) to executed trades
over a rolling high-frequency time window:
    QTR = N_quotes / max(1, N_trades)

In continuous double auction markets, normal market making and informed trading generate
moderate quote-to-trade ratios (typically QTR between 5:1 and 25:1).
However, during predatory spoofing or layering routines, algorithmic manipulators flood the book
with non-executable limit orders to fabricate artificial depth, moving the mid-price without
filling actual trades:
    QTR >= MAX_QTR (default: 50.0:1)

When QTR reaches or exceeds MAX_QTR with a qualifying quote volume (MIN_QUOTES = 40 quotes in a
WINDOW_SECONDS = 10.0s window), the market is deemed corrupted by fake phantom depth.
Scalping algorithms entering into this spoofed order book risk immediate adverse selection when
the spoofer pulls their phantom liquidity.

When high QTR spoofing is detected, the guard blocks entry orders for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests quote events and trade events with timestamps (record_quote, record_trade, record_event).
- Maintains sliding time windows of quote and trade events over WINDOW_SECONDS (10.0s).
- Cleans events older than (current_time - WINDOW_SECONDS).
- Computes QTR = N_quotes / max(1, N_trades).
- If N_quotes >= MIN_QUOTES (40) and QTR >= MAX_QTR (50.0):
    blocks entries for COOLDOWN_SECONDS (45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative timestamps are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_quote(ts=None)                                    -> None
  record_trade(ts=None)                                    -> None
  record_event(event_type, ts=None)                        -> None
  update(event_type, ts=None)                              -> None   (alias)
  get_qtr()                                                -> float
  get_status()                                             -> dict
  reset()                                                  -> None
"""

import collections
import math
import threading
import time
from typing import Deque, Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_QTR: float = 50.0                 # QTR >= 50:1 indicates predatory spoofing/layering
MIN_QUOTES: int = 40                  # Minimum quotes in window to qualify for evaluation
WINDOW_SECONDS: float = 10.0          # Rolling evaluation time window
COOLDOWN_SECONDS: float = 45.0        # Block duration on spoofing detection


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_quotes: Deque[float] = collections.deque()
_trades: Deque[float] = collections.deque()
_latest_qtr: float = 0.0
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _purge_old_events(now: float) -> None:
    """Purge events outside the rolling time window. Must be called under _lock."""
    cutoff = now - WINDOW_SECONDS
    while _quotes and _quotes[0] < cutoff:
        _quotes.popleft()
    while _trades and _trades[0] < cutoff:
        _trades.popleft()


def record_quote(ts=None) -> None:
    """Record an incoming limit quote update (insert/amend/cancel)."""
    if ts is not None:
        if isinstance(ts, bool) or not isinstance(ts, (int, float)):
            return
        if math.isnan(ts) or math.isinf(ts) or ts < 0.0:
            return
        current_ts = float(ts)
    else:
        current_ts = time.monotonic()

    global _latest_qtr, _blocked_until
    with _lock:
        _quotes.append(current_ts)
        _purge_old_events(current_ts)

        n_q = len(_quotes)
        n_t = len(_trades)

        if n_q >= MIN_QUOTES:
            qtr = float(n_q) if n_t == 0 else (float(n_q) / float(n_t))
            _latest_qtr = qtr
            if qtr >= MAX_QTR:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS


def record_trade(ts=None) -> None:
    """Record an executed trade event."""
    if ts is not None:
        if isinstance(ts, bool) or not isinstance(ts, (int, float)):
            return
        if math.isnan(ts) or math.isinf(ts) or ts < 0.0:
            return
        current_ts = float(ts)
    else:
        current_ts = time.monotonic()

    global _latest_qtr
    with _lock:
        _trades.append(current_ts)
        _purge_old_events(current_ts)

        n_q = len(_quotes)
        n_t = len(_trades)
        if n_q >= MIN_QUOTES:
            _latest_qtr = float(n_q) / float(n_t)


def record_event(event_type: str, ts=None) -> None:
    """Record either a 'quote' or 'trade' event."""
    if not isinstance(event_type, str):
        return
    ev = event_type.strip().lower()
    if ev in ("quote", "quotes", "q"):
        record_quote(ts=ts)
    elif ev in ("trade", "trades", "t", "fill"):
        record_trade(ts=ts)


def update(event_type: str, ts=None) -> None:
    """Alias for record_event()."""
    record_event(event_type, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if high QTR spoofing has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_qtr() -> float:
    """Return the most recently computed Quote-to-Trade Ratio."""
    with _lock:
        return _latest_qtr


def get_status(ts=None) -> Dict[str, Any]:
    """Return a diagnostic snapshot of the QTR spoofing guard state."""
    with _lock:
        now = time.monotonic()
        if ts is not None and not isinstance(ts, bool) and isinstance(ts, (int, float)):
            _purge_old_events(float(ts))
        return {
            "qtr": _latest_qtr,
            "quote_count": len(_quotes),
            "trade_count": len(_trades),
            "min_quotes_threshold": MIN_QUOTES,
            "max_qtr_threshold": MAX_QTR,
            "window_seconds": WINDOW_SECONDS,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset all event deques, QTR metrics, and active blocks."""
    global _latest_qtr, _blocked_until
    with _lock:
        _quotes.clear()
        _trades.clear()
        _latest_qtr = 0.0
        _blocked_until = 0.0
