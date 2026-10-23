"""
wave312_lob_quote_churn_velocity_guard.py
-----------------------------------------
Guard: LOB Inside Quote Round-Trip Velocity & Quote Churn Guard

Monitors limit order book inside quote churn velocity and round-trip price revisions,
guarding against predatory quote stuffing, high-frequency latency pinging, and vanishing liquidity loops
(Hasbrouck & Saar 2013; Biais, Foucault & Moinas 2015; O'Hara 2015):
    Quote Updates:                Timestamped (bid, ask, mid) updates
    Quote Churn Velocity:         V_{churn} = N_{updates} / W  (updates / sec over window W = 5.0s)
    Round-Trip Revisions:         Price moves by Delta p and returns to prior level in dt <= 0.100s
    Round-Trip Ratio:             R_{round_trip} = N_{round_trips} / max(N_{updates}, 1)

Under normal liquid market making:
    - Quote updates arrive smoothly at sustainable rates with low round-trip flickering:
      V_{churn} <= 15.0 updates/sec, R_{round_trip} <= 0.35.

Under quote stuffing attacks, latency arbitrage, or phantom quote manipulation:
    - Order book undergoes frantic, unproductive quote revision storms:
        1) Quote Churn Velocity Surge:
           Rolling churn velocity V_{churn} >= MAX_CHURN_VELOCITY (default: 35.0 updates/s)
           with high round-trip ratio R_{round_trip} >= MIN_ROUND_TRIP_RATIO (default: 0.60)
           over rolling window W = 5.0 seconds.
        2) Acute Quote Flash Barrage:
           Rapid burst of >= ACUTE_FLASH_UPDATES (default: 25 updates) within dt <= ACUTE_BURST_SEC (default: 0.30s)
           with zero executed trades.

Trading during acute quote churn storms guarantees queue latency penalties, stale order fills,
and immediate adverse price slippage.

When quote churn surge or an acute flash barrage is detected, entry orders
are blocked for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests quote events via record_quote(mid_price, ts=None) or
  direct metrics via record_churn_metrics(churn_velocity, round_trip_ratio=None, sample_count=None, ts=None).
- Sliding window of WINDOW_SEC = 5.0 seconds.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive mid prices are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_quote(mid_price, ts=None)                                                             -> None
  record_churn_metrics(churn_velocity, round_trip_ratio=None, sample_count=None, ts=None)       -> None
  update(mid_price, ts=None)                                                                   -> None   (alias)
  get_churn_metrics()                                                                          -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave312LobQuoteChurnVelocityGuard:
    """
    Guards against LOB quote stuffing storms, rapid round-trip price flickering, and latency pinging.
    """

    MAX_CHURN_VELOCITY: float = 35.0
    MIN_ROUND_TRIP_RATIO: float = 0.60
    WINDOW_SEC: float = 5.0
    ACUTE_FLASH_UPDATES: int = 25
    ACUTE_BURST_SEC: float = 0.30
    ROUND_TRIP_MAX_DT: float = 0.100
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_churn_velocity: float = MAX_CHURN_VELOCITY,
        min_round_trip_ratio: float = MIN_ROUND_TRIP_RATIO,
        window_sec: float = WINDOW_SEC,
        acute_flash_updates: int = ACUTE_FLASH_UPDATES,
        acute_burst_sec: float = ACUTE_BURST_SEC,
        round_trip_max_dt: float = ROUND_TRIP_MAX_DT,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_churn_velocity = float(max_churn_velocity)
        self.min_round_trip_ratio = float(min_round_trip_ratio)
        self.window_sec = float(window_sec)
        self.acute_flash_updates = int(acute_flash_updates)
        self.acute_burst_sec = float(acute_burst_sec)
        self.round_trip_max_dt = float(round_trip_max_dt)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._quote_history = collections.deque()  # (ts, price)
        self._round_trips = collections.deque()    # ts

        self._latest_velocity: float = 0.0
        self._latest_round_trip_ratio: float = 0.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _purge_old_quotes(self, now_ts: float) -> None:
        cutoff = now_ts - self.window_sec
        while self._quote_history and self._quote_history[0][0] < cutoff:
            self._quote_history.popleft()

        while self._round_trips and self._round_trips[0] < cutoff:
            self._round_trips.popleft()

    def _check_and_trigger_block(
        self,
        velocity: float,
        rt_ratio: float,
        now_ts: float,
    ) -> bool:
        # 1. Acute quote flash barrage (>= 25 updates in <= 0.30s)
        if len(self._quote_history) >= self.acute_flash_updates:
            # Check elapsed time over the last acute_flash_updates
            last_n_t0 = self._quote_history[-self.acute_flash_updates][0]
            dt_burst = now_ts - last_n_t0
            if dt_burst <= self.acute_burst_sec:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = (
                    f"ACUTE_QUOTE_FLASH_BARRAGE: {self.acute_flash_updates} updates in "
                    f"{dt_burst * 1000:.1f}ms <= {self.acute_burst_sec * 1000:.1f}ms"
                )
                return True

        # 2. Quote churn velocity surge
        if len(self._quote_history) >= 20 and velocity >= self.max_churn_velocity and rt_ratio >= self.min_round_trip_ratio:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"QUOTE_CHURN_VELOCITY_SURGE: V_churn={velocity:.1f} >= {self.max_churn_velocity:.1f} up/s "
                f"with round_trip_ratio={rt_ratio:.2f} >= {self.min_round_trip_ratio:.2f}"
            )
            return True

        return False

    def record_quote(self, mid_price: float, ts: Optional[float] = None) -> None:
        """
        Record instantaneous mid-price update and evaluate quote churn velocity.
        """
        with self._lock:
            if not self._is_valid_num(mid_price) or mid_price <= 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_PRICE_INPUT"
                return

            now_ts = float(ts) if (self._is_valid_num(ts) and ts >= 0.0) else time.time()
            price = float(mid_price)

            # Check for round-trip: if price matches 2 ticks ago within round_trip_max_dt
            if len(self._quote_history) >= 2:
                t_prev2, p_prev2 = self._quote_history[-2]
                if abs(price - p_prev2) < 1e-6 and (now_ts - t_prev2) <= self.round_trip_max_dt:
                    self._round_trips.append(now_ts)

            self._quote_history.append((now_ts, price))
            self._sample_count += 1
            self._purge_old_quotes(now_ts)

            n_updates = len(self._quote_history)
            n_rt = len(self._round_trips)
            velocity = n_updates / self.window_sec
            rt_ratio = n_rt / max(n_updates, 1)

            self._latest_velocity = velocity
            self._latest_round_trip_ratio = rt_ratio

            self._check_and_trigger_block(velocity, rt_ratio, now_ts)

    def record_churn_metrics(
        self,
        churn_velocity: float,
        round_trip_ratio: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed quote churn metrics.
        """
        with self._lock:
            if not self._is_valid_num(churn_velocity) or churn_velocity < 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_CHURN_METRIC"
                return

            vel = float(churn_velocity)
            rt = float(round_trip_ratio) if (self._is_valid_num(round_trip_ratio) and round_trip_ratio >= 0.0) else (self.min_round_trip_ratio + 0.1)
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else 25

            self._latest_velocity = vel
            self._latest_round_trip_ratio = rt
            self._sample_count = cnt

            if vel >= self.max_churn_velocity and rt >= self.min_round_trip_ratio:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = (
                    f"QUOTE_CHURN_VELOCITY_SURGE: V_churn={vel:.1f} >= {self.max_churn_velocity:.1f} up/s "
                    f"with round_trip_ratio={rt:.2f} >= {self.min_round_trip_ratio:.2f}"
                )

    def update(self, mid_price: float, ts: Optional[float] = None) -> None:
        """Alias for record_quote."""
        self.record_quote(mid_price, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_churn_metrics(self) -> Dict[str, Any]:
        with self._lock:
            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "churn_velocity": float(self._latest_velocity),
                "round_trip_ratio": float(self._latest_round_trip_ratio),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_churn_metrics()

    def reset(self) -> None:
        with self._lock:
            self._quote_history.clear()
            self._round_trips.clear()
            self._latest_velocity = 0.0
            self._latest_round_trip_ratio = 0.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
