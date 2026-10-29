"""
Wave 434 -- Mid-Price Hawkes Excitation Jump Guard
=================================================
Presides over self-exciting jump processes in high-frequency mid-price returns.
Microstructure shocks often trigger cascades of subsequent jumps (Hawkes process).
When conditional jump intensity lambda(t) spikes above institutional thresholds,
the market is experiencing algorithmic cascade avalanche or liquidity contagion.

Methodology
-----------
* Tracks midprice log returns: r_t = ln(mid_t / mid_{t-1}).
* Identifies jumps where |r_t| >= `jump_threshold`.
* Evaluates self-exciting Hawkes intensity:
    lambda(t) = mu + sum_{t_i < t} alpha * exp(-beta * (t - t_i))
* If lambda(t) >= `max_hawkes_intensity`, blocks with SELF_EXCITING_HAWKES_JUMP_AVALANCHE.
* If |r_t| >= `catastrophic_jump_threshold`, blocks with CATASTROPHIC_PRICE_DISLOCATION.

Blocking reasons
----------------
SELF_EXCITING_HAWKES_JUMP_AVALANCHE -- jump clustering intensity exceeded safety limits
CATASTROPHIC_PRICE_DISLOCATION      -- single-tick return exceeded catastrophic threshold
INPUT_VALIDATION_ERROR              -- bid >= ask, non-numeric, or non-monotonic timestamps

Public API (standardised)
-------------------------
update(bid, ask, timestamp)         -> None
is_blocked(current_time=None)       -> bool
is_entry_blocked(bid, ask, ts=None) -> bool
reset()                             -> None
last_reason                         -> str
hawkes_intensity                    -> float
last_jump_size                      -> float
"""

from __future__ import annotations

import collections
import math
import threading
import time
from typing import Deque, Optional

__all__ = ["Wave434MidpriceHawkesExcitationJumpGuard"]

_REASON_HAWKES = "SELF_EXCITING_HAWKES_JUMP_AVALANCHE"
_REASON_CATA = "CATASTROPHIC_PRICE_DISLOCATION"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave434MidpriceHawkesExcitationJumpGuard:
    """Wave 434: Mid-Price Hawkes Excitation Jump Guard."""

    def __init__(
        self,
        jump_threshold: float = 0.0003,
        baseline_mu: float = 0.05,
        alpha_excitation: float = 1.0,
        beta_decay: float = 0.8,
        max_hawkes_intensity: float = 2.50,
        catastrophic_jump_threshold: float = 0.010,
        memory_seconds: float = 10.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if (
            jump_threshold <= 0.0
            or baseline_mu < 0.0
            or alpha_excitation <= 0.0
            or beta_decay <= 0.0
            or max_hawkes_intensity <= baseline_mu
            or catastrophic_jump_threshold <= jump_threshold
            or memory_seconds <= 0.0
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave434MidpriceHawkesExcitationJumpGuard")

        self._jump_thresh = float(jump_threshold)
        self._mu = float(baseline_mu)
        self._alpha = float(alpha_excitation)
        self._beta = float(beta_decay)
        self._max_intensity = float(max_hawkes_intensity)
        self._cata_thresh = float(catastrophic_jump_threshold)
        self._memory_sec = float(memory_seconds)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_ts: Optional[float] = None
        self._last_mid: Optional[float] = None
        self._jump_timestamps: Deque[float] = collections.deque()
        self._current_intensity: float = self._mu
        self._last_jump: float = 0.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def hawkes_intensity(self) -> float:
        with self._lock:
            return self._current_intensity

    @property
    def last_jump_size(self) -> float:
        with self._lock:
            return self._last_jump

    def reset(self) -> None:
        with self._lock:
            self._last_ts = None
            self._last_mid = None
            self._jump_timestamps.clear()
            self._current_intensity = self._mu
            self._last_jump = 0.0
            self._blocked_until = 0.0
            self._last_reason = ""

    def _block(self, reason: str, ts: Optional[float] = None) -> None:
        ref_t = time.monotonic() if ts is None else ts
        self._blocked_until = max(self._blocked_until, ref_t + self._cooldown)
        self._last_reason = reason

    def update(self, bid: float, ask: float, timestamp: float) -> None:
        with self._lock:
            if (
                not isinstance(bid, (int, float))
                or not isinstance(ask, (int, float))
                or not isinstance(timestamp, (int, float))
                or bid <= 0.0
                or ask <= bid
                or timestamp < 0.0
            ):
                self._block(_REASON_VAL, timestamp if (isinstance(timestamp, (int, float)) and timestamp > 0) else None)
                return

            if self._last_ts is not None and timestamp < self._last_ts:
                self._block(_REASON_VAL, timestamp)
                return

            ts = float(timestamp)
            mid = (float(bid) + float(ask)) / 2.0

            if self._last_mid is not None and self._last_mid > 0.0:
                ret = math.log(mid / self._last_mid)
                abs_ret = abs(ret)

                if abs_ret >= self._cata_thresh:
                    self._block(_REASON_CATA, ts)
                    self._last_jump = abs_ret
                    self._last_ts = ts
                    self._last_mid = mid
                    return

                if abs_ret >= self._jump_thresh:
                    self._jump_timestamps.append(ts)
                    self._last_jump = abs_ret

                # Prune jumps older than memory window
                cutoff = ts - self._memory_sec
                while self._jump_timestamps and self._jump_timestamps[0] < cutoff:
                    self._jump_timestamps.popleft()

                # Evaluate Hawkes intensity: lambda(t) = mu + sum alpha * exp(-beta * (t - t_i))
                lam = self._mu
                for tj in self._jump_timestamps:
                    dt = ts - tj
                    if dt >= 0:
                        lam += self._alpha * math.exp(-self._beta * dt)

                self._current_intensity = lam

                if lam >= self._max_intensity:
                    self._block(_REASON_HAWKES, ts)

            self._last_ts = ts
            self._last_mid = mid

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
