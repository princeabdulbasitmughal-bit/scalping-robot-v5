"""
Wave 419 -- Order Flow Toxicity Duration & Horizon Persistence Guard
=====================================================================
Monitors the continuous time duration and volume magnitude during which aggressive
order flow remains persistently one-sided (e.g., uninterrupted institutional sweeps).
While brief order imbalances are absorbed naturally by market makers, persistent toxic
flow lasting several seconds signals heavy institutional portfolio rebalancing or
predatory predatory execution, guaranteeing adverse fills for retail and scalper flow.

Methodology
-----------
* Observes trade fills: (volume, is_buy, timestamp).
* Maintains a rolling window of recent fills to calculate signed imbalance ratio:
    I = (V_{buy} - V_{sell}) / (V_{buy} + V_{sell}) in [-1, +1]
* If |I| >= `min_toxic_ratio`, initiates or extends persistent toxic episode duration tau = ts - t_{start}.
* Tracks cumulative sweep volume V_{sweep} during the toxic episode.
* If tau >= `max_toxic_duration_sec`, blocks with PERSISTENT_TOXIC_FLOW_DURATION.
* If V_{sweep} >= `max_sweep_volume`, blocks with UNRELENTING_ORDER_SWEEP.

Blocking reasons
----------------
PERSISTENT_TOXIC_FLOW_DURATION -- one-sided order flow persisted beyond maximum safe horizon
UNRELENTING_ORDER_SWEEP        -- cumulative volume swept in single episode exceeded safety limit
INPUT_VALIDATION_ERROR         -- non-positive volume, invalid timestamp, or non-numeric params

Public API (standardised)
-------------------------
update(volume, is_buy, timestamp) -> None
is_blocked(current_time=None)     -> bool
is_entry_blocked(bid, ask, ts)    -> bool
reset()                           -> None
last_reason                       -> str
toxic_duration_sec                -> float
cumulative_sweep_volume           -> float
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

__all__ = ["Wave419OrderFlowToxicityDurationGuard"]

_REASON_DURATION = "PERSISTENT_TOXIC_FLOW_DURATION"
_REASON_SWEEP = "UNRELENTING_ORDER_SWEEP"
_REASON_VAL = "INPUT_VALIDATION_ERROR"


class Wave419OrderFlowToxicityDurationGuard:
    """Order Flow Toxicity Duration and Horizon Persistence Guard."""

    def __init__(
        self,
        window_size: int = 10,
        max_toxic_duration_sec: float = 3.0,
        min_toxic_ratio: float = 0.70,
        max_sweep_volume: float = 500.0,
        cooldown_seconds: float = 60.0,
    ) -> None:
        if (
            window_size < 3
            or max_toxic_duration_sec <= 0.0
            or not (0.20 <= min_toxic_ratio <= 0.98)
            or max_sweep_volume <= 0.0
            or cooldown_seconds <= 0.0
        ):
            raise ValueError("Invalid parameters for Wave419OrderFlowToxicityDurationGuard")

        self._window_size = int(window_size)
        self._max_duration = float(max_toxic_duration_sec)
        self._min_toxic_ratio = float(min_toxic_ratio)
        self._max_sweep_vol = float(max_sweep_volume)
        self._cooldown = float(cooldown_seconds)

        self._lock = threading.Lock()
        self._last_ts: Optional[float] = None
        self._trades: deque[tuple[float, bool]] = deque(maxlen=self._window_size)
        self._toxic_start_ts: Optional[float] = None
        self._cumulative_sweep_vol: float = 0.0
        self._current_duration: float = 0.0
        self._blocked_until: float = 0.0
        self._last_reason: str = ""

    @property
    def last_reason(self) -> str:
        with self._lock:
            return self._last_reason

    @property
    def toxic_duration_sec(self) -> float:
        with self._lock:
            return self._current_duration

    @property
    def cumulative_sweep_volume(self) -> float:
        with self._lock:
            return self._cumulative_sweep_vol

    def reset(self) -> None:
        with self._lock:
            self._last_ts = None
            self._trades.clear()
            self._toxic_start_ts = None
            self._cumulative_sweep_vol = 0.0
            self._current_duration = 0.0
            self._blocked_until = 0.0
            self._last_reason = ""

    def _block(self, reason: str, ts: Optional[float] = None) -> None:
        ref_t = time.monotonic() if ts is None else ts
        self._blocked_until = max(self._blocked_until, ref_t + self._cooldown)
        self._last_reason = reason

    def update(self, volume: float, is_buy: bool, timestamp: float) -> None:
        with self._lock:
            if (
                not isinstance(volume, (int, float))
                or not isinstance(timestamp, (int, float))
                or volume <= 0.0
                or timestamp < 0.0
            ):
                self._block(_REASON_VAL, timestamp if timestamp > 0 else None)
                return

            if self._last_ts is not None and timestamp < self._last_ts:
                self._block(_REASON_VAL, timestamp)
                return

            ts = float(timestamp)
            vol = float(volume)
            self._trades.append((vol, bool(is_buy)))

            if len(self._trades) >= self._window_size:
                buy_vol = sum(v for v, b in self._trades if b)
                sell_vol = sum(v for v, b in self._trades if not b)
                total_vol = buy_vol + sell_vol

                if total_vol > 0.0:
                    imbalance = (buy_vol - sell_vol) / total_vol

                    if abs(imbalance) >= self._min_toxic_ratio:
                        if self._toxic_start_ts is None:
                            self._toxic_start_ts = ts
                            self._cumulative_sweep_vol = vol
                        else:
                            self._cumulative_sweep_vol += vol

                        dur = ts - self._toxic_start_ts
                        self._current_duration = dur

                        if dur >= self._max_duration:
                            self._block(_REASON_DURATION, ts)
                        elif self._cumulative_sweep_vol >= self._max_sweep_vol:
                            self._block(_REASON_SWEEP, ts)
                    else:
                        # Flow returned to balanced regime
                        self._toxic_start_ts = None
                        self._cumulative_sweep_vol = 0.0
                        self._current_duration = 0.0

            self._last_ts = ts

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        with self._lock:
            now = current_time if current_time is not None else time.monotonic()
            return now < self._blocked_until

    def is_entry_blocked(self, bid: float, ask: float, ts: Optional[float] = None) -> bool:
        return self.is_blocked(ts)
