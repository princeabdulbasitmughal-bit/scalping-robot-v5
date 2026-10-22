"""
wave258_hf_price_jump_intensity_guard.py
----------------------------------------
Guard: High-Frequency Price Jump Intensity & Cascade Arrival Guard

Monitors discontinuous price innovations and jump arrival clustering in high-frequency tick data
(Mancini 2009; Bacry, Delattre, Hoffmann & Muzy 2013; Ait-Sahalia & Jacod 2014):
    Tick Return (bps):          r_t = (|P_t - P_{t-1}| / P_{t-1}) * 10^4
    Jump Indicator:             I_{jump}(t) = 1 if r_t >= JUMP_THRESHOLD_BPS (2.50 bps)
    Jump Intensity:             lambda_{jump}(W) = N_{jumps}(W) / W  (jumps / sec over W = 30s)
    Acute Burst Interval:       Delta t_{burst} = t_jump - t_{prev_jump}

Under orderly continuous double-auction conditions:
    - Price changes are dominated by continuous Brownian diffusion with small tick movements (|r_t| < 1.0 bps).
    - Discrete price jumps are rare, isolated events (at most 0 to 1 jump per 30-second window; lambda_{jump} < 0.05 jumps/s).

During predatory news cascades, liquidity hole collapses, or algorithmic stop-loss cascades:
    - Discrete price jumps cluster in rapid succession (Hawkes self-exciting point process):
        1) Jump Intensity Cascade:
           N_{jumps} >= MAX_JUMP_COUNT (default: 4 jumps within rolling W = 30.0s window).
        2) Acute Jump Burst:
           2 or more acute jumps of magnitude r_t >= ACUTE_JUMP_BPS (default: 3.50 bps)
           occurring within Delta t <= ACUTE_BURST_WINDOW_SEC (default: 3.0s).

Entering new scalping positions during price jump cascades exposes executions to massive slippage,
spread widening, and extreme adverse selection.

When jump intensity clustering or acute burst is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests prices via record_price(price, ts=None) or jump returns via record_jump(return_bps, ts=None).
- Maintains timestamped deque of jump events within rolling WINDOW_SECONDS = 30.0s.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive prices are rejected.

Aliases (required):
  is_entry_blocked()                                   -> bool
  is_blocked()                                         -> bool   (alias)
  record_price(price, ts=None)                         -> None
  record_jump(return_bps, ts=None)                     -> None
  update(price, ts=None)                               -> None   (alias)
  get_jump_metrics()                                   -> dict
  get_status()                                         -> dict
  reset()                                              -> None
"""

import collections
import math
import threading
import time
from typing import Dict, Optional, Any, Deque, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
JUMP_THRESHOLD_BPS: float = 2.50         # 2.50 bps threshold to qualify as discrete jump
WINDOW_SECONDS: float = 30.0            # 30.0s rolling observation window
MAX_JUMP_COUNT: int = 4                 # 4 jumps in window indicates toxic clustering
ACUTE_JUMP_BPS: float = 3.50            # 3.50 bps acute jump threshold
ACUTE_BURST_WINDOW_SEC: float = 3.0     # 3.0s window for acute double jump
COOLDOWN_SECONDS: float = 45.0          # 45.0s block duration

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_last_price: Optional[float] = None
_last_price_ts: Optional[float] = None
_last_acute_jump_ts: Optional[float] = None
_jump_events: Deque[Tuple[float, float]] = collections.deque()  # (ts, return_bps)
_latest_return_bps: float = 0.0
_blocked_until: float = 0.0


def _is_valid_positive(val: Any) -> bool:
    """Validate value is a positive finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val > 0.0


def _is_valid_numeric(val: Any) -> bool:
    """Validate value is a finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return True


def _purge_old_jumps(now_ts: float) -> None:
    """Remove jumps older than WINDOW_SECONDS from the rolling deque."""
    cutoff = now_ts - WINDOW_SECONDS
    while _jump_events and _jump_events[0][0] < cutoff:
        _jump_events.popleft()


def record_jump(return_bps: float, ts: Optional[float] = None) -> None:
    """
    Directly ingest a price jump event with its return in basis points.
    """
    global _latest_return_bps, _last_acute_jump_ts, _last_price_ts, _blocked_until

    if not _is_valid_numeric(return_bps):
        return

    ret_bps = abs(float(return_bps))
    now = float(ts) if (ts is not None and _is_valid_numeric(ts)) else time.time()

    with _lock:
        _latest_return_bps = ret_bps
        _last_price_ts = now

        if ret_bps >= JUMP_THRESHOLD_BPS:
            _purge_old_jumps(now)
            _jump_events.append((now, ret_bps))

            # Condition 2: Acute Jump Burst (2 acute jumps within ACUTE_BURST_WINDOW_SEC)
            if ret_bps >= ACUTE_JUMP_BPS:
                if _last_acute_jump_ts is not None and (now - _last_acute_jump_ts) <= ACUTE_BURST_WINDOW_SEC:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                    _last_acute_jump_ts = now
                    return
                _last_acute_jump_ts = now

            # Condition 1: Jump Intensity Cascade
            if len(_jump_events) >= MAX_JUMP_COUNT:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return


def record_price(price: float, ts: Optional[float] = None) -> None:
    """
    Ingest price update, calculate tick return in basis points, and detect jumps.
    """
    global _last_price, _last_price_ts, _latest_return_bps, _last_acute_jump_ts, _blocked_until

    if not _is_valid_positive(price):
        return

    p = float(price)
    now = float(ts) if (ts is not None and _is_valid_numeric(ts)) else time.time()

    with _lock:
        if _last_price is None:
            _last_price = p
            _last_price_ts = now
            return

        prev_p = _last_price
        _last_price = p
        _last_price_ts = now

        if prev_p <= 0.0:
            return

        ret_bps = (abs(p - prev_p) / prev_p) * 10000.0
        _latest_return_bps = ret_bps

        if ret_bps >= JUMP_THRESHOLD_BPS:
            _purge_old_jumps(now)
            _jump_events.append((now, ret_bps))

            # Condition 2: Acute Jump Burst
            if ret_bps >= ACUTE_JUMP_BPS:
                if _last_acute_jump_ts is not None and (now - _last_acute_jump_ts) <= ACUTE_BURST_WINDOW_SEC:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                    _last_acute_jump_ts = now
                    return
                _last_acute_jump_ts = now

            # Condition 1: Jump Intensity Cascade
            if len(_jump_events) >= MAX_JUMP_COUNT:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return


def update(price: float, ts: Optional[float] = None) -> None:
    """Module alias for record_price."""
    record_price(price, ts=ts)


def is_entry_blocked() -> bool:
    """Return True if entry is currently blocked by jump intensity guard."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked."""
    return is_entry_blocked()


def get_jump_metrics(now_ts: Optional[float] = None) -> Dict[str, Any]:
    """Return dictionary of current jump metrics."""
    with _lock:
        if now_ts is not None and _is_valid_numeric(now_ts):
            now = float(now_ts)
        elif _last_price_ts is not None and _last_price_ts < 1_000_000_000.0:
            now = _last_price_ts
        else:
            now = time.time()
        _purge_old_jumps(now)
        jump_count = len(_jump_events)
        intensity_per_sec = jump_count / WINDOW_SECONDS if WINDOW_SECONDS > 0 else 0.0
        return {
            "latest_return_bps": round(_latest_return_bps, 4),
            "jump_count_window": jump_count,
            "jump_intensity_per_sec": round(intensity_per_sec, 4),
            "window_seconds": WINDOW_SECONDS,
            "max_jump_count": MAX_JUMP_COUNT,
            "jump_threshold_bps": JUMP_THRESHOLD_BPS,
            "is_blocked": is_entry_blocked(),
        }


def get_status() -> Dict[str, Any]:
    """Return complete status dictionary."""
    with _lock:
        remaining_cd = max(0.0, _blocked_until - time.monotonic())
        metrics = get_jump_metrics()
        metrics["cooldown_remaining_sec"] = round(remaining_cd, 2)
        return metrics


def reset() -> None:
    """Reset all state to initial defaults."""
    global _last_price, _last_price_ts, _last_acute_jump_ts, _latest_return_bps, _blocked_until
    with _lock:
        _last_price = None
        _last_price_ts = None
        _last_acute_jump_ts = None
        _jump_events.clear()
        _latest_return_bps = 0.0
        _blocked_until = 0.0
