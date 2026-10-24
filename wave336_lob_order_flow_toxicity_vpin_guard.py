"""
Wave 336 — LOB Order-Flow Toxicity VPIN Guard
==============================================
Volume-Synchronised Probability of Informed Trading (VPIN) guard.

Methodology
-----------
* Partition volume into equal-sized buckets of size `bucket_volume`.
* For each completed bucket, compute the signed-volume fraction:
  tau = |V_buy - V_sell| / (V_buy + V_sell)
* VPIN = rolling mean of tau over the last `n_buckets` buckets.
* Block when VPIN >= `vpin_threshold` AND spread is above `primary_spread_threshold_bps`.

Blocking reasons
----------------
VPIN_TOXICITY_BREACH   — rolling VPIN >= threshold
INPUT_VALIDATION_ERROR — malformed arguments

Public API (standardised)
-------------------------
update(bid, ask, volume, side, timestamp)  -> None
is_blocked(current_time=None)              -> bool
is_entry_blocked(bid, ask, ts)             -> bool
reset()                                    -> None
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave336LOBOrderFlowToxicityVPINGuard"]

_REASON_VPIN = "VPIN_TOXICITY_BREACH"
_REASON_VAL  = "INPUT_VALIDATION_ERROR"


class Wave336LOBOrderFlowToxicityVPINGuard:
    """VPIN-based order-flow toxicity guard for LOB microstructure."""

    def __init__(
        self,
        bucket_volume: float = 100.0,
        n_buckets: int = 10,
        vpin_threshold: float = 0.60,
        primary_spread_threshold_bps: float = 2.0,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if bucket_volume <= 0 or n_buckets < 1 or not (0 < vpin_threshold <= 1):
            raise ValueError("Invalid VPIN guard parameters.")
        self._bucket_volume   = float(bucket_volume)
        self._n_buckets       = int(n_buckets)
        self._vpin_threshold  = float(vpin_threshold)
        self._spread_thr_bps  = float(primary_spread_threshold_bps)
        self._cooldown        = float(cooldown_seconds)

        self._lock            = threading.RLock()
        self._taus: deque     = deque(maxlen=n_buckets)
        self._buf_buy: float  = 0.0
        self._buf_sell: float = 0.0
        self._buf_total: float= 0.0
        self._blocked_until   = 0.0
        self._last_reason     = ""

    # ------------------------------------------------------------------
    def update(
        self,
        bid: float,
        ask: float,
        volume: float,
        side: str,          # "buy" or "sell"
        timestamp: float,
    ) -> None:
        with self._lock:
            # Validate
            if isinstance(bid, bool) or isinstance(ask, bool) or isinstance(volume, bool):
                self._block(timestamp, _REASON_VAL)
                return
            if not isinstance(bid, (int, float)) or not isinstance(ask, (int, float)):
                self._block(timestamp, _REASON_VAL)
                return
            if not isinstance(volume, (int, float)) or volume <= 0:
                self._block(timestamp, _REASON_VAL)
                return
            if side not in ("buy", "sell"):
                self._block(timestamp, _REASON_VAL)
                return
            if bid <= 0 or ask <= 0 or ask <= bid:
                self._block(timestamp, _REASON_VAL)
                return

            mid = (bid + ask) / 2.0
            spread_bps = (ask - bid) / mid * 10_000.0

            # Accumulate into current bucket
            if side == "buy":
                self._buf_buy += volume
            else:
                self._buf_sell += volume
            self._buf_total += volume

            # Complete bucket(s)
            while self._buf_total >= self._bucket_volume:
                frac = self._bucket_volume / self._buf_total
                b = self._buf_buy * frac
                s = self._buf_sell * frac
                denom = b + s
                tau = abs(b - s) / denom if denom > 0 else 0.0
                self._taus.append(tau)

                self._buf_total -= self._bucket_volume
                self._buf_buy   *= (1 - frac)
                self._buf_sell  *= (1 - frac)

            # Evaluate VPIN
            if len(self._taus) >= self._n_buckets:
                vpin = sum(self._taus) / len(self._taus)
                if vpin >= self._vpin_threshold and spread_bps >= self._spread_thr_bps:
                    self._block(timestamp, _REASON_VPIN)

    def _block(self, timestamp: float, reason: str) -> None:
        self._blocked_until = time.monotonic() + self._cooldown
        self._last_reason   = reason

    # ------------------------------------------------------------------
    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            t = time.monotonic() if current_time is None else current_time
            return t < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: float) -> bool:
        return self.is_blocked(ts)

    def reset(self) -> None:
        with self._lock:
            self._taus.clear()
            self._buf_buy   = 0.0
            self._buf_sell  = 0.0
            self._buf_total = 0.0
            self._blocked_until = 0.0
            self._last_reason   = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason
