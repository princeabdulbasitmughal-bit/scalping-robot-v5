"""
wave175_cross_venue_quote_arbitrage_lag_guard.py
-------------------------------------------------
Guard: Cross-Venue Quote Latency Arbitrage & Dislocation Guard

Monitors price and quote synchronization between the local broker's execution book and a primary
institutional reference venue (e.g. LMAX, Currenex, EBS, CME).

High-frequency latency arbitrageurs (toxic snipers) monitor primary institutional quote feeds to
detect directional price shifts milliseconds before retail broker feeds update.
If a scalping algorithm enters trades using stale local quotes, it will systematically trade at
adverse prices against latency arbitrage flow:
1. Downside Dislocation (Ref Ask < Local Bid): Primary interbank market has plunged below the local
   broker's bid. Local bid quotes are stale; long orders will be executed right into a falling knife.
2. Upside Dislocation (Ref Bid > Local Ask): Primary interbank market has spiked above the local
   broker's ask. Local ask quotes are stale; short orders will be executed at disadvantageous levels.
3. Midpoint Divergence: |Mid_local - Mid_ref| / Mid_ref >= MAX_DIVERGENCE_BPS (default: 2.0 bps / 0.00020).
4. Feed Synchronization Lag: Timestamp delay between venues exceeds MAX_LATENCY_LAG_SEC (default: 2.5s).
5. Crossed Internal Books: Bid > Ask on either venue indicates inverted/corrupt quote feeds.

When any quote dislocation, latency lag, or book inversion is detected, entry orders are blocked
immediately for COOLDOWN_SECONDS (default: 45.0s) until venue quotes converge.

Logic:
- Ingests (local_bid, local_ask, ref_bid, ref_ask) with optional timestamps (local_ts, ref_ts).
- Validates strictly against booleans, NaNs, Infs, and non-positive prices.
- Checks for crossed quotes: local_bid > local_ask or ref_bid > ref_ask.
- Checks for crossed cross-venue arbitrage: ref_ask < local_bid or ref_bid > local_ask.
- Computes relative midpoint divergence = |Mid_local - Mid_ref| / Mid_ref.
- Evaluates inter-venue timestamp latency lag if timestamps are supplied.
- If any anomaly condition is met:
    blocks entries for COOLDOWN_SECONDS (45.0s).
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: invalid quote inputs are rejected without unblocking active protections.

Aliases (required):
  is_entry_blocked()                                       -> bool
  is_blocked()                                             -> bool   (alias)
  record_quotes(local_bid, local_ask, ref_bid, ref_ask, ...) -> None
  update(local_bid, local_ask, ref_bid, ref_ask, ...)       -> None   (alias)
  get_mid_divergence()                                     -> float
  get_latency_lag()                                        -> float
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
MAX_DIVERGENCE_BPS: float = 0.00020   # 2.0 basis points (0.02%) maximum acceptable midpoint divergence
MAX_LATENCY_LAG_SEC: float = 2.5      # Maximum allowable timestamp desynchronization between venues
COOLDOWN_SECONDS: float = 45.0        # Block duration on quote dislocation or latency lag


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_latest_divergence: float = 0.0
_latest_latency_lag: float = 0.0
_dislocation_detected: bool = False
_blocked_until: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_quotes(
    local_bid,
    local_ask,
    ref_bid,
    ref_ask,
    local_ts=None,
    ref_ts=None,
) -> None:
    """Record synchronized quotes from local broker and reference venue."""
    for val in (local_bid, local_ask, ref_bid, ref_ask):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return
        if math.isnan(val) or math.isinf(val) or val <= 0.0:
            return

    lb = float(local_bid)
    la = float(local_ask)
    rb = float(ref_bid)
    ra = float(ref_ask)

    global _latest_divergence, _latest_latency_lag, _dislocation_detected, _blocked_until
    with _lock:
        # Calculate relative midpoint divergence unconditionally for diagnostics
        mid_local = 0.5 * (lb + la)
        mid_ref = 0.5 * (rb + ra)
        divergence = abs(mid_local - mid_ref) / mid_ref if mid_ref > 0.0 else 0.0
        _latest_divergence = divergence

        # Inter-venue timestamp latency lag
        if local_ts is not None and ref_ts is not None:
            if not isinstance(local_ts, bool) and isinstance(local_ts, (int, float)) and \
               not isinstance(ref_ts, bool) and isinstance(ref_ts, (int, float)):
                if not math.isnan(local_ts) and not math.isinf(local_ts) and \
                   not math.isnan(ref_ts) and not math.isinf(ref_ts):
                    _latest_latency_lag = abs(float(local_ts) - float(ref_ts))

        # Check internal crossed books
        if lb > la or rb > ra:
            _dislocation_detected = True
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Check cross-venue arbitrage dislocation
        # Downside: Ref Ask < Local Bid (interbank has crashed below local bid)
        # Upside: Ref Bid > Local Ask (interbank has spiked above local ask)
        if ra < lb or rb > la:
            _dislocation_detected = True
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Midpoint divergence threshold check
        if divergence >= MAX_DIVERGENCE_BPS:
            _dislocation_detected = True
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Latency lag threshold check
        if _latest_latency_lag >= MAX_LATENCY_LAG_SEC:
            _dislocation_detected = True
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        _dislocation_detected = False


def update(local_bid, local_ask, ref_bid, ref_ask, local_ts=None, ref_ts=None) -> None:
    """Alias for record_quotes()."""
    record_quotes(local_bid, local_ask, ref_bid, ref_ask, local_ts=local_ts, ref_ts=ref_ts)


def is_entry_blocked() -> bool:
    """Return True if quote dislocation or latency lag has triggered an active block."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_mid_divergence() -> float:
    """Return the most recently computed relative midpoint divergence."""
    with _lock:
        return _latest_divergence


def get_latency_lag() -> float:
    """Return the most recently measured inter-venue timestamp latency lag in seconds."""
    with _lock:
        return _latest_latency_lag


def get_status() -> Dict[str, Any]:
    """Return a diagnostic snapshot of the cross-venue arbitrage guard state."""
    with _lock:
        now = time.monotonic()
        return {
            "mid_divergence": _latest_divergence,
            "latency_lag_sec": _latest_latency_lag,
            "dislocation_detected": _dislocation_detected,
            "max_divergence_bps": MAX_DIVERGENCE_BPS,
            "max_latency_lag_sec": MAX_LATENCY_LAG_SEC,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset all divergence metrics, lag measurements, and active blocks."""
    global _latest_divergence, _latest_latency_lag, _dislocation_detected, _blocked_until
    with _lock:
        _latest_divergence = 0.0
        _latest_latency_lag = 0.0
        _dislocation_detected = False
        _blocked_until = 0.0
