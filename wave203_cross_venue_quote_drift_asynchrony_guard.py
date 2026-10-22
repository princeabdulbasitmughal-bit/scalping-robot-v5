"""
wave203_cross_venue_quote_drift_asynchrony_guard.py
----------------------------------------------------
Guard: Cross-Venue Asynchronous Price Drift & Latency Lag Guard

Monitors inter-venue quote dislocation and asynchronous lead-lag price discovery latency
between a primary low-latency reference venue and the local execution venue (Biais et al. 2015):
    Delta_{bps} = |P_{ref} - P_{local}| / P_{ref} * 10,000

In synchronized electronic markets with low bridge latency and rapid arbitrageurs, quote
dislocations between venues close within milliseconds:
    Delta_{bps} < 1.0 bp, with any micro-dislocation converging in < 0.20s.

When the local broker's pricing engine suffers quotation queue lag, socket buffering, or feeds
stale quotes during fast reference venue price moves:
    1) Persistent quote dislocation:
       Delta_{bps} >= MAX_DISLOCATION_BPS (default: 2.5 bps)
    2) Asynchronous latency lag:
       Dislocation fails to converge (Delta_{bps} > CONVERGENCE_BPS = 1.0 bp) after
       MAX_LAG_SECONDS (default: 1.0s).

Submitting execution orders against a stale, dislocated local quote exposes the trading system
to guaranteed adverse fill re-quotes, asymmetric slippage, or predatory front-running.

When cross-venue asynchronous lag is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests reference and local venue mid-prices (ref_price > 0.0, local_price > 0.0, ts=None).
- Computes basis-point price dislocation.
- Tracks duration of continuous dislocation >= MAX_DISLOCATION_BPS (2.5 bps).
- If dislocation persists for >= MAX_LAG_SECONDS (1.0s), blocks entries for COOLDOWN_SECONDS (45.0s).
- If dislocation converges to <= CONVERGENCE_BPS (1.0 bp), timer resets.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive price inputs are rejected.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_quotes(ref_price, local_price, ts=None)           -> None
  update(ref_price, local_price, ts=None)                  -> None   (alias)
  get_dislocation_bps()                                    -> float
  get_status()                                             -> dict
  reset()                                                  -> None
"""

import math
import threading
import time
from typing import Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_DISLOCATION_BPS: float = 2.5       # 2.5 bps initiates lag timer
CONVERGENCE_BPS: float = 1.0           # 1.0 bp indicates healthy convergence
MAX_LAG_SECONDS: float = 1.0           # 1.0s maximum allowable lag
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_dislocation_start_ts: Optional[float] = None
_latest_dislocation_bps: float = 0.0
_blocked_until: float = 0.0


def _is_valid_price(val: Any) -> bool:
    """Validate price is a positive finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val > 0.0


def record_quotes(ref_price: float, local_price: float, ts: Optional[float] = None) -> None:
    """
    Ingest reference and local prices, compute dislocation, and monitor latency lag.
    """
    global _dislocation_start_ts, _latest_dislocation_bps, _blocked_until

    if not _is_valid_price(ref_price) or not _is_valid_price(local_price):
        return

    rp = float(ref_price)
    lp = float(local_price)

    with _lock:
        now = time.monotonic() if ts is None else float(ts)

        dislocation_bps = (abs(rp - lp) / rp) * 10_000.0
        _latest_dislocation_bps = dislocation_bps

        if dislocation_bps >= MAX_DISLOCATION_BPS:
            if _dislocation_start_ts is None:
                _dislocation_start_ts = now
            else:
                elapsed_lag = now - _dislocation_start_ts
                if elapsed_lag >= MAX_LAG_SECONDS:
                    _blocked_until = time.monotonic() + COOLDOWN_SECONDS
        elif dislocation_bps <= CONVERGENCE_BPS:
            _dislocation_start_ts = None


def update(ref_price: float, local_price: float, ts: Optional[float] = None) -> None:
    """Alias for record_quotes()."""
    record_quotes(ref_price, local_price, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to cross-venue lag."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_dislocation_bps() -> float:
    """Return latest cross-venue price dislocation in basis points."""
    with _lock:
        return _latest_dislocation_bps


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the cross-venue lag guard."""
    with _lock:
        now = time.monotonic()
        lag_duration = (now - _dislocation_start_ts) if _dislocation_start_ts is not None else 0.0
        return {
            "dislocation_bps": _latest_dislocation_bps,
            "has_active_dislocation": _dislocation_start_ts is not None,
            "lag_duration_sec": lag_duration,
            "max_dislocation_threshold": MAX_DISLOCATION_BPS,
            "convergence_threshold": CONVERGENCE_BPS,
            "max_lag_seconds": MAX_LAG_SECONDS,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset dislocation history, timer state, and active cooldown blocks."""
    global _dislocation_start_ts, _latest_dislocation_bps, _blocked_until
    with _lock:
        _dislocation_start_ts = None
        _latest_dislocation_bps = 0.0
        _blocked_until = 0.0
