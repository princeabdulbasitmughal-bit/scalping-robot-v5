"""
Wave 439 -- Cross-Exchange Spread Arbitrage Divergence Sentinel
==============================================================
Monitors cross-venue price parity between the local execution venue and an
external reference benchmark feed (e.g. primary LP or futures market).
When local midprice decouples from reference benchmark by more than institutional
tolerances, the book is either suffering latency arbitrage adverse selection or
experiencing an exchange-specific liquidity fracture.

Methodology
-----------
* Tracks local bid/ask and external reference benchmark price: P_ref.
* Computes basis divergence in basis points (bps):
    B_bps = (|P_local - P_ref| / P_ref) * 10,000
* If B_bps >= `max_divergence_bps`, blocks with CROSS_VENUE_PRICE_DIVERGENCE_SPIKE.
* If time since last benchmark update >= `stale_feed_timeout_sec`,
  blocks with STALE_BENCHMARK_FEED_DISCONNECTION.

Blocking reasons
----------------
CROSS_VENUE_PRICE_DIVERGENCE_SPIKE   -- basis spread between venues breached limit
STALE_BENCHMARK_FEED_DISCONNECTION   -- reference venue price feed stale or offline
INPUT_VALIDATION_ERROR               -- bid >= ask, non-numeric, or non-monotonic timestamps

Public API (standardised)
-------------------------
update(bid, ask, ref_price, timestamp) -> None
is_blocked(current_time=None)          -> bool
is_entry_blocked(bid, ask, ts=None)    -> bool
reset()                                -> None
last_reason                            -> str
basis_divergence_bps                   -> float
"""

from __future__ import annotations

import threading
import time
from typing import Optional

__all__ = ["Wave439CrossVenueArbitrageDivergenceGuard"]

_REASON_SPIKE = "CROSS_VENUE_PRICE_DIVERGENCE_SPIKE"
_REASON_STALE = "STALE_BENCHMARK_FEED_DISCONNECTION"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave439CrossVenueArbitrageDivergenceGuard:
    """Wave 439: Cross-Exchange Spread Arbitrage Divergence Sentinel."""

    def __init__(
        self,
        max_divergence_bps: float = 6.0,
        stale_feed_timeout_sec: float = 3.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if (
            max_divergence_bps <= 0.5
            or stale_feed_timeout_sec <= 0.1
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave439CrossVenueArbitrageDivergenceGuard")

        self._max_bps = float(max_divergence_bps)
        self._stale_timeout = float(stale_feed_timeout_sec)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_ts: Optional[float] = None
        self._last_ref_ts: Optional[float] = None
        self._basis_bps: float = 0.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def basis_divergence_bps(self) -> float:
        with self._lock:
            return self._basis_bps

    def reset(self) -> None:
        with self._lock:
            self._last_ts = None
            self._last_ref_ts = None
            self._basis_bps = 0.0
            self._blocked_until = 0.0
            self._last_reason = ""

    def _block(self, reason: str, ts: Optional[float] = None) -> None:
        ref_t = time.monotonic() if ts is None else ts
        self._blocked_until = max(self._blocked_until, ref_t + self._cooldown)
        self._last_reason = reason

    def update(
        self,
        bid: float,
        ask: float,
        ref_price: float,
        timestamp: float,
    ) -> None:
        with self._lock:
            if (
                not isinstance(bid, (int, float))
                or not isinstance(ask, (int, float))
                or not isinstance(ref_price, (int, float))
                or not isinstance(timestamp, (int, float))
                or bid <= 0.0
                or ask <= bid
                or ref_price <= 0.0
                or timestamp < 0.0
            ):
                self._block(_REASON_VAL, timestamp if (isinstance(timestamp, (int, float)) and timestamp > 0) else None)
                return

            if self._last_ts is not None and timestamp < self._last_ts:
                self._block(_REASON_VAL, timestamp)
                return

            ts = float(timestamp)
            mid = (float(bid) + float(ask)) / 2.0
            ref_p = float(ref_price)

            # Check benchmark feed freshness
            if self._last_ref_ts is not None and (ts - self._last_ref_ts) >= self._stale_timeout:
                self._block(_REASON_STALE, ts)

            self._last_ref_ts = ts
            div_bps = (abs(mid - ref_p) / ref_p) * 10000.0
            self._basis_bps = div_bps

            if div_bps >= self._max_bps:
                self._block(_REASON_SPIKE, ts)

            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
