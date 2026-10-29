"""
Wave 443 -- High-Frequency Cross-Asset Lead-Lag Information Transfer Guard
=========================================================================
Monitors leading cross-asset macro information transmission (e.g. US Dollar Index,
10Y Treasury yield futures) onto high-frequency target assets (XAUUSD).
When a leading macroeconomic anchor asset undergoes a sharp directional shock,
there exists a microstructural latency window (50ms - 800ms) before the target
market fully incorporates the information. Trading during this latent propagation
window exposes market orders to catastrophic adverse selection.

Methodology
-----------
* Tracks tick midprice log returns of leading asset r_lead and target asset r_target.
* Detects lead impulse when |r_lead| >= `lead_shock_threshold`.
* Monitors pending latency propagation window (elapsed <= `max_propagation_window_sec`).
* Blocks entries with LATENT_CROSS_ASSET_IMPACT_PENDING until target asset adjusts
  or propagation window elapses.
* If leading asset variance spikes beyond ceiling, blocks with LEAD_ASSET_VOLATILITY_SUPERNOVA.

Blocking reasons
----------------
LATENT_CROSS_ASSET_IMPACT_PENDING  -- lead asset experienced sharp shock; target adjustment pending
LEAD_ASSET_VOLATILITY_SUPERNOVA    -- lead macro anchor asset entered extreme volatility dislocation
INPUT_VALIDATION_ERROR             -- non-numeric, zero prices, or non-monotonic timestamps

Public API (standardised)
-------------------------
update(lead_price, target_bid, target_ask, timestamp) -> None
is_blocked(current_time=None)                         -> bool
is_entry_blocked(bid, ask, ts=None)                   -> bool
reset()                                               -> None
last_reason                                           -> str
lead_return                                           -> float
is_propagation_pending                                -> bool
"""

from __future__ import annotations

import math
import threading
import time
from typing import Optional

__all__ = ["Wave443CrossAssetLeadLagTransferGuard"]

_REASON_PENDING = "LATENT_CROSS_ASSET_IMPACT_PENDING"
_REASON_SUPERNOVA = "LEAD_ASSET_VOLATILITY_SUPERNOVA"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave443CrossAssetLeadLagTransferGuard:
    """Wave 443: High-Frequency Cross-Asset Lead-Lag Information Transfer Guard."""

    def __init__(
        self,
        lead_shock_threshold: float = 0.0008,
        max_propagation_window_sec: float = 0.50,
        lead_vol_ceiling: float = 0.0050,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if (
            lead_shock_threshold <= 0.0
            or max_propagation_window_sec <= 0.01
            or lead_vol_ceiling <= lead_shock_threshold
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave443CrossAssetLeadLagTransferGuard")

        self._shock_thresh = float(lead_shock_threshold)
        self._max_prop_sec = float(max_propagation_window_sec)
        self._vol_ceil = float(lead_vol_ceiling)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_ts: Optional[float] = None
        self._last_lead_p: Optional[float] = None
        self._shock_ts: Optional[float] = None
        self._lead_ret: float = 0.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def lead_return(self) -> float:
        with self._lock:
            return self._lead_ret

    @property
    def is_propagation_pending(self) -> bool:
        with self._lock:
            return self._shock_ts is not None

    def reset(self) -> None:
        with self._lock:
            self._last_ts = None
            self._last_lead_p = None
            self._shock_ts = None
            self._lead_ret = 0.0
            self._blocked_until = 0.0
            self._last_reason = ""

    def _block(self, reason: str, ts: Optional[float] = None) -> None:
        ref_t = time.monotonic() if ts is None else ts
        self._blocked_until = max(self._blocked_until, ref_t + self._cooldown)
        self._last_reason = reason

    def update(
        self,
        lead_price: float,
        target_bid: float,
        target_ask: float,
        timestamp: float,
    ) -> None:
        with self._lock:
            if (
                not isinstance(lead_price, (int, float))
                or not isinstance(target_bid, (int, float))
                or not isinstance(target_ask, (int, float))
                or not isinstance(timestamp, (int, float))
                or lead_price <= 0.0
                or target_bid <= 0.0
                or target_ask <= target_bid
                or timestamp < 0.0
            ):
                self._block(_REASON_VAL, timestamp if (isinstance(timestamp, (int, float)) and timestamp > 0) else None)
                return

            if self._last_ts is not None and timestamp < self._last_ts:
                self._block(_REASON_VAL, timestamp)
                return

            ts = float(timestamp)
            lead_p = float(lead_price)

            if self._last_lead_p is not None and self._last_lead_p > 0.0:
                ret = math.log(lead_p / self._last_lead_p)
                abs_ret = abs(ret)
                self._lead_ret = ret

                if abs_ret >= self._vol_ceil:
                    self._block(_REASON_SUPERNOVA, ts)
                    self._shock_ts = ts
                elif abs_ret >= self._shock_thresh:
                    self._block(_REASON_PENDING, ts)
                    self._shock_ts = ts

            # Check if propagation window has elapsed
            if self._shock_ts is not None and (ts - self._shock_ts) > self._max_prop_sec:
                self._shock_ts = None

            self._last_ts = ts
            self._last_lead_p = lead_p

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
