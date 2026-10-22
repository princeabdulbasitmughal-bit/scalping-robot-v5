"""
wave231_lob_replenishment_asymmetry_slope_guard.py
---------------------------------------------------
Guard: LOB Liquidity Replenishment Asymmetry & Replenishment Deficit Slope Guard

Monitors post-sweep limit order book replenishment velocity and structural resistance
to two-sided liquidity provision (Biais, Hillion & Spatt 1995; Foucault, Kadan & Kandel 2005):
    Replenishment Rate Bid:   R_{bid} = Delta Q_{bid} / max(0.05, dt) (lots/sec)
    Replenishment Rate Ask:   R_{ask} = Delta Q_{ask} / max(0.05, dt) (lots/sec)
    Asymmetry Slope Ratio:    A_{replenish} = max(R_{bid}, R_{ask}) / max(0.1, min(R_{bid}, R_{ask}))

In healthy limit order book dynamics:
    - Following depth consumption by aggressive market orders, market makers rapidly replenish
      liquidity on both sides: R_{bid} ~ R_{ask} >= 5.0 lots/sec, with A_{replenish} < 3.0x.

During structural liquidity resistance or impending breakout regimes:
    - Liquidity replenishes aggressively on one side while completely stalling on the other:
        1) Severe Replenishment Asymmetry:
           A_{replenish} >= MAX_REPLENISH_ASYMMETRY (default: 8.0x) AND
           max(R_{bid}, R_{ask}) >= DOMINANT_RATE_THRESHOLD (default: 10.0 lots/sec) AND
           min(R_{bid}, R_{ask}) <= LAGGING_RATE_THRESHOLD (default: 1.0 lot/sec).
        2) Bilateral Replenishment Drought:
           Both R_{bid} <= DROUGHT_RATE_THRESHOLD (default: 0.20 lots/sec) AND
           R_{ask} <= DROUGHT_RATE_THRESHOLD (0.20 lots/sec) with dt >= 1.0s.

Attempting to trade counter to the depleted side guarantees catastrophic slippage as the
unreplenished barrier collapses into thin air.

When replenishment asymmetry or bilateral drought is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests replenishment measurements via record_replenishment(bid_replenished_lots, ask_replenished_lots, dt_sec=1.0, ts=None).
- Computes R_{bid}, R_{ask}, and A_{replenish}.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, negative volumes, or non-positive dt are rejected.

Aliases (required):
  is_entry_blocked()                                                                   -> bool
  is_blocked()                                                                         -> bool   (alias)
  record_replenishment(bid_lots, ask_lots, dt_sec=1.0, ts=None)                         -> None
  update(bid_lots, ask_lots, dt_sec=1.0, ts=None)                                       -> None   (alias)
  get_replenishment_metrics()                                                          -> dict
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
MAX_REPLENISH_ASYMMETRY: float = 8.0      # 8.0x replenishment rate asymmetry
DOMINANT_RATE_THRESHOLD: float = 10.0     # 10.0 lots/sec dominant replenishment rate
LAGGING_RATE_THRESHOLD: float = 1.0       # 1.0 lot/sec lagging replenishment rate
DROUGHT_RATE_THRESHOLD: float = 0.20      # 0.20 lots/sec bilateral replenishment drought
COOLDOWN_SECONDS: float = 45.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_latest_rate_bid: float = 5.0
_latest_rate_ask: float = 5.0
_latest_asymmetry_ratio: float = 1.0
_blocked_until: float = 0.0


def _is_valid_non_negative(val: Any) -> bool:
    """Validate value is a non-negative finite numeric float."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return val >= 0.0


def record_replenishment(
    bid_lots: float,
    ask_lots: float,
    dt_sec: float = 1.0,
    ts: Optional[float] = None,
) -> None:
    """
    Ingest replenishment volumes and time elapsed to evaluate replenishment asymmetry slope.
    """
    global _latest_rate_bid, _latest_rate_ask, _latest_asymmetry_ratio, _blocked_until

    if not _is_valid_non_negative(bid_lots) or not _is_valid_non_negative(ask_lots):
        return
    if not _is_valid_non_negative(dt_sec) or dt_sec <= 0.0:
        return

    qb = float(bid_lots)
    qa = float(ask_lots)
    dt = float(dt_sec)

    with _lock:
        r_bid = qb / max(0.05, dt)
        r_ask = qa / max(0.05, dt)

        dominant_r = max(r_bid, r_ask)
        lagging_r = min(r_bid, r_ask)
        asym_ratio = dominant_r / max(0.1, lagging_r)

        _latest_rate_bid = r_bid
        _latest_rate_ask = r_ask
        _latest_asymmetry_ratio = asym_ratio

        # Condition 1: Severe replenishment asymmetry
        if (
            asym_ratio >= MAX_REPLENISH_ASYMMETRY
            and dominant_r >= DOMINANT_RATE_THRESHOLD
            and lagging_r <= LAGGING_RATE_THRESHOLD
        ):
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return

        # Condition 2: Bilateral replenishment drought post-sweep
        if (
            r_bid <= DROUGHT_RATE_THRESHOLD
            and r_ask <= DROUGHT_RATE_THRESHOLD
            and dt >= 1.0
        ):
            _blocked_until = time.monotonic() + COOLDOWN_SECONDS
            return


def update(
    bid_lots: float,
    ask_lots: float,
    dt_sec: float = 1.0,
    ts: Optional[float] = None,
) -> None:
    """Alias for record_replenishment()."""
    record_replenishment(bid_lots, ask_lots, dt_sec, ts)


def is_entry_blocked() -> bool:
    """Check if entry orders are currently blocked due to replenishment asymmetry."""
    with _lock:
        return time.monotonic() < _blocked_until


def is_blocked() -> bool:
    """Alias for is_entry_blocked()."""
    return is_entry_blocked()


def get_replenishment_metrics() -> Dict[str, float]:
    """Return latest calculated replenishment rates and asymmetry ratio."""
    with _lock:
        return {
            "rate_bid_lots_sec": _latest_rate_bid,
            "rate_ask_lots_sec": _latest_rate_ask,
            "asymmetry_ratio": _latest_asymmetry_ratio,
        }


def get_status() -> Dict[str, Any]:
    """Return diagnostic snapshot of the replenishment asymmetry guard."""
    with _lock:
        now = time.monotonic()
        return {
            "rate_bid_lots_sec": _latest_rate_bid,
            "rate_ask_lots_sec": _latest_rate_ask,
            "asymmetry_ratio": _latest_asymmetry_ratio,
            "max_replenish_asymmetry": MAX_REPLENISH_ASYMMETRY,
            "dominant_rate_threshold": DOMINANT_RATE_THRESHOLD,
            "lagging_rate_threshold": LAGGING_RATE_THRESHOLD,
            "drought_rate_threshold": DROUGHT_RATE_THRESHOLD,
            "cooldown_seconds": COOLDOWN_SECONDS,
            "is_blocked": now < _blocked_until,
            "blocked_seconds_remaining": max(0.0, _blocked_until - now),
        }


def reset() -> None:
    """Reset replenishment trackers, metrics, and active cooldown blocks."""
    global _latest_rate_bid, _latest_rate_ask, _latest_asymmetry_ratio, _blocked_until
    with _lock:
        _latest_rate_bid = 5.0
        _latest_rate_ask = 5.0
        _latest_asymmetry_ratio = 1.0
        _blocked_until = 0.0
