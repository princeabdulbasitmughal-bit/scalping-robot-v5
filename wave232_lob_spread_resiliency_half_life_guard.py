"""
wave232_lob_spread_resiliency_half_life_guard.py
-------------------------------------------------
Guard: Quote Level Resiliency Half-Life & Spread Gap Recovery Guard

Monitors limit order book resiliency decay and post-shock spread healing dynamics
(Large 2007; Degryse, de Jong, van Kervel & Wuyts 2015):
    Spread Blowout Shock:  S_{shock} >= 4.0 bps
    Post-Shock Retrace:    R_{retrace} = (S_{shock} - S(t)) / max(0.1, S_{shock} - S_{baseline})
    Unhealed Duration:     dt_{unhealed} = t - t_{shock} (sec)

In deep, resilient electronic limit order books:
    - Liquidity shocks are swiftly absorbed: market makers fill the spread back to baseline
      within fractions of a second: t_{1/2} < 0.5s, with R_{retrace} >= 0.70 in <= 1.0s.

During persistent liquidity droughts, order book fractures, or institutional retreat:
    - The spread blows out and fails to heal, remaining wide and fragile:
        1) Slow Resiliency Healing:
           S_{shock} >= MIN_SHOCK_SPREAD_BPS (default: 4.0 bps) AND
           dt_{unhealed} >= MAX_RECOVERY_TIME_SEC (default: 2.0s) AND
           R_{retrace} < MIN_RETRACE_RATIO (default: 0.40, meaning < 40% healed).
        2) Persistent Wide Spread Fracture:
           Current spread S(t) >= PERSISTENT_WIDE_SPREAD_BPS (default: 8.0 bps)
           for dt >= 1.5 seconds.

Submitting market orders or posting passive quotes during unhealed spread fractures guarantees
paying massive bid-ask friction and suffering immediate adverse selection.

When spread resiliency failure is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests spread observations via record_spread(spread_bps, ts=None)
  or record_spread_shock(spread_bps, shock_start_spread_bps, elapsed_sec, ts=None).
- Tracks shock start spread, baseline spread, and recovery time.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative values are rejected.

Aliases (required):
  is_entry_blocked()                                                                   -> bool
  is_blocked()                                                                         -> bool   (alias)
  record_spread(spread_bps, ts=None)                                                   -> None
  record_spread_shock(spread_bps, shock_start_spread_bps, elapsed_sec, ts=None)         -> None
  update(spread_bps, ts=None)                                                          -> None   (alias)
  get_resiliency_metrics()                                                             -> dict
  get_status()                                                                         -> dict
  reset()                                                                              -> None
"""

import math
import threading
import time
from typing import Dict, Optional, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASELINE_SPREAD_BPS: float = 1.0          # 1.0 bp normal baseline spread
MIN_SHOCK_SPREAD_BPS: float = 4.0         # 4.0 bps spread shock threshold
MAX_RECOVERY_TIME_SEC: float = 2.0        # 2.0 seconds maximum allowed recovery window
MIN_RETRACE_RATIO: float = 0.40           # 40% minimum retrace back toward baseline
PERSISTENT_WIDE_SPREAD_BPS: float = 8.0   # 8.0 bps wide spread fracture
PERSISTENT_DURATION_SEC: float = 1.5      # 1.5 seconds wide spread persistence
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_shock_start_spread: float = 0.0
_shock_start_ts: Optional[float] = None
_wide_spread_start_ts: Optional[float] = None
_latest_spread_bps: float = 1.0
_latest_retrace_ratio: float = 1.0
_latest_elapsed_sec: float = 0.0
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


def record_spread(
    spread_bps: float,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest a spread measurement and evaluate resiliency recovery and persistent fracture.
    """
    global _shock_start_spread, _shock_start_ts, _wide_spread_start_ts
    global _latest_spread_bps, _latest_retrace_ratio, _latest_elapsed_sec, _blocked_until

    if not _is_valid_positive(spread_bps):
        return

    s = float(spread_bps)

    with _lock:
        now = time.monotonic() if ts is None else float(ts)
        _latest_spread_bps = s

        # Check Condition 2: Persistent Wide Spread Fracture
        if s >= PERSISTENT_WIDE_SPREAD_BPS:
            if _wide_spread_start_ts is None:
                _wide_spread_start_ts = now
            elif (now - _wide_spread_start_ts) >= PERSISTENT_DURATION_SEC:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return
        else:
            _wide_spread_start_ts = None

        # Track Shock initiation and recovery
        if s >= MIN_SHOCK_SPREAD_BPS:
            if _shock_start_ts is None or s > _shock_start_spread:
                _shock_start_spread = s
                _shock_start_ts = now

        if _shock_start_ts is not None:
            elapsed = max(0.0, now - _shock_start_ts)
            _latest_elapsed_sec = elapsed

            denom = max(0.1, _shock_start_spread - BASELINE_SPREAD_BPS)
            retrace = max(0.0, (_shock_start_spread - s) / denom)
            _latest_retrace_ratio = retrace

            # Condition 1: Failed Resiliency Retrace after MAX_RECOVERY_TIME_SEC
            if elapsed >= MAX_RECOVERY_TIME_SEC and retrace < MIN_RETRACE_RATIO:
                _blocked_until = time.monotonic() + COOLDOWN_SECONDS
                return

            # Clear shock if fully retraced
            if retrace >= 0.85:
                _shock_start_ts = None
                _shock_start_spread = 0.0


def record_spread_shock(
    spread_bps: float,
    shock_start_spread_bps: float,
    elapsed_sec: float,
    ts: Optional[float] = None,
) -> None:
    """
    Directly evaluate spread resiliency shock metrics.
    """
    global _latest_spread_bps, _latest_retrace_ratio, _latest_elapsed_sec, _blocked_until

    if not _is_valid_positive(spread_bps) or not _is_valid_positive(shock_start_spread_bps):
        return
    if isinstance(elapsed_sec, bool) or not isinstance(elapsed_sec, (int, float)):
        return
    if math.isnan(elapsed_sec) or math.isinf(elapsed_sec) or elapsed_sec < 0.0:
        return

    s = float(spread_bps)
    s_shock = float(shock_start_spread_bps)
    dt = float(elapsed_sec)

    with _lock:
        denom = max(0.1, s_shock - BASELINE_SPREAD_BPS)
        retrace = max(0.0, (s_shock - s) / denom)

        _latest_spread_bps = s
        _latest_retrace_ratio = retrace
        _latest_elapsed_sec = dt

        if s_shock >= MIN_SHOCK_SPREAD_BPS and dt >= MAX_RECOVERY_TIME_SEC and retrace < MIN_RETRACE_RATIO:
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(spread_bps: float, ts: Optional[float] = None) -> None:
    """Alias for record_spread()."""
    record_spread(spread_bps, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to spread resiliency failure."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_resiliency_metrics() -> Dict[str, float]:
    """Return latest calculated spread, retrace ratio, and elapsed shock time."""
    with _lock:
        return {
            "spread_bps": _latest_spread_bps,
            "retrace_ratio": _latest_retrace_ratio,
            "elapsed_shock_sec": _latest_elapsed_sec,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the spread resiliency guard."""
    with _lock:
        now = time.monotonic()
        return {
            "spread_bps": _latest_spread_bps,
            "retrace_ratio": _latest_retrace_ratio,
            "elapsed_shock_sec": _latest_elapsed_sec,
            "min_shock_spread_bps": MIN_SHOCK_SPREAD_BPS,
            "max_recovery_time_sec": MAX_RECOVERY_TIME_SEC,
            "min_retrace_ratio": MIN_RETRACE_RATIO,
            "persistent_wide_spread_bps": PERSISTENT_WIDE_SPREAD_BPS,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset spread shock trackers, metrics, and active cooldown blocks."""
    global _shock_start_spread, _shock_start_ts, _wide_spread_start_ts
    global _latest_spread_bps, _latest_retrace_ratio, _latest_elapsed_sec, _blocked_until
    with _lock:
        _shock_start_spread = 0.0
        _shock_start_ts = None
        _wide_spread_start_ts = None
        _latest_spread_bps = 1.0
        _latest_retrace_ratio = 1.0
        _latest_elapsed_sec = 0.0
        _blocked_until = 0.0
