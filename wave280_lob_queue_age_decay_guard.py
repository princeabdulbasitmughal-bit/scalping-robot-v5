"""
wave280_lob_queue_age_decay_guard.py
------------------------------------
Guard: LOB Inside-Queue Quote Age & Stale Depth Attrition Guard

Monitors limit order book touch quote resting duration, stale depth persistence, and quote refresh rates
(Biais, Hillion & Spatt 1995; Bouchaud et al. 2002; Gould et al. 2013; Cartea & Jaimungal 2014):
    Quote Age at Touch:          A_{quote} = t - t_{last_touch_update} (seconds)
    Rolling Mean Quote Age:      \\bar{A}_{quote} = (1 / N) * sum_{i=1}^N A_i
    Spread at Observation:       S_{bps} = (Ask - Bid) / Mid * 10,000

Under competitive electronic market making:
    - Resting orders at Level-1 are dynamically updated, cancelled, and restocked by market makers.
    - Mean quote age is modest (typically 0.20s to 4.00s), reflecting constant price revision and active risk hedging.

During market maker abandonment, toxic adverse selection traps, or liquidity vacuum:
    - Resting quotes sit unrefreshed for excessive durations without price updates:
        1) Stale Depth Persistence:
           Rolling mean quote age \\bar{A}_{quote} >= MAX_MEAN_QUOTE_AGE_SEC (default: 12.0s)
           with spread S_{bps} >= MIN_STALE_SPREAD_BPS (default: 2.50 bps) over N >= MIN_SAMPLES (8 observations).
        2) Acute Stale Trap:
           Current quote age A_{quote} >= ACUTE_STALE_AGE_SEC (default: 25.0s).

Orders executed against stale, abandoned quotes suffer high latency-arbitrage toxicity, adverse selection,
and sudden price gap risk upon resumption of liquidity.

When stale depth persistence or an acute stale trap is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests quote age via record_quote_age(age_seconds, spread_bps=None, sample_count=None, ts=None) or
  touch updates via record_touch_update(bid_price, ask_price, ts=None).
- Maintains rolling history of WINDOW_SIZE = 15 quote age observations.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative values are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_quote_age(age_seconds, spread_bps=None, sample_count=None, ts=None)                   -> None
  record_touch_update(bid_price, ask_price, ts=None)                                           -> None
  update(age_seconds, spread_bps=None, ts=None)                                                -> None   (alias)
  get_quote_age_metrics()                                                                      -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, Optional


class Wave280LobQueueAgeDecayGuard:
    """
    Guards against stale LOB touch quotes, market maker abandonment, and liquidity vacuum traps.
    """

    MAX_MEAN_QUOTE_AGE_SEC: float = 12.0
    MIN_STALE_SPREAD_BPS: float = 2.50
    MIN_SAMPLES: int = 8
    ACUTE_STALE_AGE_SEC: float = 25.0
    WINDOW_SIZE: int = 15
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_mean_quote_age_sec: float = MAX_MEAN_QUOTE_AGE_SEC,
        min_stale_spread_bps: float = MIN_STALE_SPREAD_BPS,
        min_samples: int = MIN_SAMPLES,
        acute_stale_age_sec: float = ACUTE_STALE_AGE_SEC,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_mean_quote_age_sec = float(max_mean_quote_age_sec)
        self.min_stale_spread_bps = float(min_stale_spread_bps)
        self.min_samples = int(min_samples)
        self.acute_stale_age_sec = float(acute_stale_age_sec)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._age_history = collections.deque(maxlen=self.window_size)
        self._spread_history = collections.deque(maxlen=self.window_size)

        self._last_touch_bid: Optional[float] = None
        self._last_touch_ask: Optional[float] = None
        self._last_touch_ts: Optional[float] = None

        self._latest_age: float = 0.0
        self._latest_spread_bps: float = 0.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _check_and_trigger_block(self, mean_age: float, mean_spread: float, acute_age: float) -> bool:
        # 1. Acute stale trap
        if acute_age >= self.acute_stale_age_sec:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_STALE_TRAP: acute_age={acute_age:.2f}s >= {self.acute_stale_age_sec:.2f}s"
            )
            return True

        # 2. Sluggish / stale depth persistence
        if (
            self._sample_count >= self.min_samples
            and mean_age >= self.max_mean_quote_age_sec
            and mean_spread >= self.min_stale_spread_bps
        ):
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"STALE_DEPTH_PERSISTENCE: mean_age={mean_age:.2f}s >= {self.max_mean_quote_age_sec:.2f}s, "
                f"spread={mean_spread:.2f}bps >= {self.min_stale_spread_bps:.2f}bps (N={self._sample_count})"
            )
            return True

        return False

    def record_quote_age(
        self,
        age_seconds: float,
        spread_bps: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Record a quote age observation and optional contemporaneous spread in basis points.
        """
        with self._lock:
            if not self._is_valid_num(age_seconds) or age_seconds < 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_AGE_INPUT"
                return

            spr = float(spread_bps) if (self._is_valid_num(spread_bps) and spread_bps >= 0.0) else 0.0

            age = float(age_seconds)
            self._latest_age = age
            self._latest_spread_bps = spr
            self._age_history.append(age)
            self._spread_history.append(spr)

            if sample_count is not None and self._is_valid_num(sample_count):
                self._sample_count = int(sample_count)
            else:
                self._sample_count += 1

            mean_age = statistics.mean(self._age_history) if self._age_history else age
            mean_spr = statistics.mean(self._spread_history) if self._spread_history else spr

            self._check_and_trigger_block(mean_age, mean_spr, age)

    def record_touch_update(
        self,
        bid_price: float,
        ask_price: float,
        ts: Optional[float] = None,
    ) -> None:
        """
        Record inside touch prices and evaluate elapsed quote resting age.
        """
        with self._lock:
            if (
                not self._is_valid_num(bid_price)
                or not self._is_valid_num(ask_price)
                or bid_price <= 0.0
                or ask_price <= 0.0
                or ask_price < bid_price
            ):
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_TOUCH_PRICES"
                return

            now_ts = float(ts) if (self._is_valid_num(ts) and ts >= 0.0) else time.time()
            mid = (bid_price + ask_price) / 2.0
            spread_bps = ((ask_price - bid_price) / mid) * 10000.0

            if self._last_touch_ts is not None and self._last_touch_bid is not None and self._last_touch_ask is not None:
                # If prices changed, calculate elapsed duration of the previous resting quote
                if bid_price != self._last_touch_bid or ask_price != self._last_touch_ask:
                    age = max(now_ts - self._last_touch_ts, 0.0)
                    self._last_touch_bid = bid_price
                    self._last_touch_ask = ask_price
                    self._last_touch_ts = now_ts
                    self.record_quote_age(age, spread_bps=spread_bps, ts=now_ts)
                else:
                    # Still same resting quote; update ongoing resting age
                    age = max(now_ts - self._last_touch_ts, 0.0)
                    self.record_quote_age(age, spread_bps=spread_bps, ts=now_ts)
            else:
                self._last_touch_bid = bid_price
                self._last_touch_ask = ask_price
                self._last_touch_ts = now_ts

    def update(
        self,
        age_seconds: float,
        spread_bps: Optional[float] = None,
        ts: Optional[float] = None,
    ) -> None:
        """Alias for record_quote_age."""
        self.record_quote_age(age_seconds, spread_bps=spread_bps, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_quote_age_metrics(self) -> Dict[str, Any]:
        with self._lock:
            if self._age_history:
                mean_age = statistics.mean(self._age_history)
                max_age = max(self._age_history)
            else:
                mean_age = self._latest_age
                max_age = self._latest_age

            if self._spread_history:
                mean_spread = statistics.mean(self._spread_history)
            else:
                mean_spread = self._latest_spread_bps

            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "mean_quote_age_sec": float(mean_age),
                "max_quote_age_sec": float(max_age),
                "latest_quote_age_sec": float(self._latest_age),
                "mean_spread_bps": float(mean_spread),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_quote_age_metrics()

    def reset(self) -> None:
        with self._lock:
            self._age_history.clear()
            self._spread_history.clear()
            self._last_touch_bid = None
            self._last_touch_ask = None
            self._last_touch_ts = None
            self._latest_age = 0.0
            self._latest_spread_bps = 0.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
