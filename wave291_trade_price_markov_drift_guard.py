"""
wave291_trade_price_markov_drift_guard.py
-----------------------------------------
Guard: Trade Price Transition Markov Matrix & Directional Drift Guard

Monitors consecutive trade price tick transitions, first-order Markov persistence, and directional trending runs
(Niederhoffer & Osborne 1966; Roll 1984; Hasbrouck 1991; Campbell, Lo & MacKinlay 1997):
    Price Change Direction:      delta_t = sign(P_t - P_{t-1}) in {+1, -1} (ignoring zero ticks)
    State Transitions:           (delta_{t-1}, delta_t) in {(+, +), (+, -), (-, +), (-, -)}
    Up-Up Persistence:           P(+|+) = N(+, +) / max(N(+, +) + N(+, -), 1)
    Down-Down Persistence:       P(-|-) = N(-, -) / max(N(-, -) + N(-, +), 1)
    Max Markov Persistence:      P_{persist} = max(P(+|+), P(-|-))
    Directional Run Streak:      L_{streak} = consecutive price changes of identical sign

Under competitive bid-ask bouncing conditions:
    - Successive price changes alternate due to liquidity supply (bid vs ask fills):
      P(+|-) ~ 0.50, P(-|+) ~ 0.50, with low persistence P_{persist} <= 0.40.

During predatory sweeping runs, momentum cascades, or informed order flow:
    - Price changes display persistent, unreversed directional trending:
        1) Persistent Markov Directional Drift:
           Persistence probability P_{persist} >= MAX_PERSISTENCE (default: 0.75)
           over rolling N >= MIN_TRANSITIONS (default: 20 non-zero transitions).
        2) Acute Directional Price Run Streak:
           Consecutive unreversed price changes L_{streak} >= ACUTE_RUN_STREAK (default: 7 ticks).

Entering trades against an active Markov price trend exposes scalping positions to immediate
severe drawdown, directional price drift, and momentum exhaustion traps.

When Markov persistence drift or an acute price run streak is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade price via record_trade_price(price, ts=None) or
  direct metrics via record_markov_metrics(persistence_prob, streak_len=None, sample_count=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 30 tick transitions.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or non-positive prices are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade_price(price, ts=None)                                                           -> None
  record_markov_metrics(persistence_prob, streak_len=None, sample_count=None, ts=None)         -> None
  update(price, ts=None)                                                                       -> None   (alias)
  get_markov_metrics()                                                                         -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave291TradePriceMarkovDriftGuard:
    """
    Guards against high-frequency trade price Markov drift, directional trending sweeps, and momentum traps.
    """

    MAX_PERSISTENCE: float = 0.75
    MIN_TRANSITIONS: int = 20
    ACUTE_RUN_STREAK: int = 7
    WINDOW_SIZE: int = 30
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_persistence: float = MAX_PERSISTENCE,
        min_transitions: int = MIN_TRANSITIONS,
        acute_run_streak: int = ACUTE_RUN_STREAK,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_persistence = float(max_persistence)
        self.min_transitions = int(min_transitions)
        self.acute_run_streak = int(acute_run_streak)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._transitions = collections.deque(maxlen=self.window_size)

        self._last_price: Optional[float] = None
        self._last_direction: Optional[int] = None
        self._streak_len: int = 0

        self._latest_persistence: float = 0.50
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _calculate_persistence(self) -> float:
        if len(self._transitions) < 4:
            return 0.50

        n_up_up = sum(1 for prev, curr in self._transitions if prev == 1 and curr == 1)
        n_up_down = sum(1 for prev, curr in self._transitions if prev == 1 and curr == -1)
        n_down_up = sum(1 for prev, curr in self._transitions if prev == -1 and curr == 1)
        n_down_down = sum(1 for prev, curr in self._transitions if prev == -1 and curr == -1)

        p_up_up = n_up_up / max(n_up_up + n_up_down, 1)
        p_down_down = n_down_down / max(n_down_down + n_down_up, 1)

        return max(p_up_up, p_down_down)

    def _check_and_trigger_block(
        self,
        persistence: float,
        streak_len: int,
        sample_count: int,
    ) -> bool:
        # 1. Acute directional price run streak
        if streak_len >= self.acute_run_streak:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_PRICE_RUN_STREAK: streak={streak_len} >= {self.acute_run_streak} consecutive ticks"
            )
            return True

        # 2. Persistent Markov directional drift
        if sample_count >= self.min_transitions and persistence >= self.max_persistence:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"MARKOV_DIRECTIONAL_DRIFT: persistence={persistence:.2f} >= {self.max_persistence:.2f} (N={sample_count})"
            )
            return True

        return False

    def record_trade_price(self, price: float, ts: Optional[float] = None) -> None:
        """
        Record a trade execution price and evaluate discrete direction change.
        """
        with self._lock:
            if not self._is_valid_num(price) or price <= 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_PRICE_INPUT"
                return

            px = float(price)

            if self._last_price is not None:
                diff = px - self._last_price
                if abs(diff) > 1e-6:
                    direction = 1 if diff > 0 else -1

                    if self._last_direction is not None:
                        self._transitions.append((self._last_direction, direction))
                        self._sample_count += 1

                    if self._last_direction is not None and direction == self._last_direction:
                        self._streak_len += 1
                    else:
                        self._streak_len = 1

                    self._last_direction = direction
                    persistence = self._calculate_persistence()
                    self._latest_persistence = persistence

                    self._check_and_trigger_block(
                        persistence,
                        self._streak_len,
                        len(self._transitions),
                    )

            self._last_price = px

    def record_markov_metrics(
        self,
        persistence_prob: float,
        streak_len: Optional[int] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed Markov transition metrics.
        """
        with self._lock:
            if not self._is_valid_num(persistence_prob) or persistence_prob < 0.0 or persistence_prob > 1.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_MARKOV_METRIC"
                return

            p = float(persistence_prob)
            stk = int(streak_len) if (self._is_valid_num(streak_len) and streak_len >= 0) else 1
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_transitions

            self._latest_persistence = p
            self._streak_len = stk
            self._sample_count = cnt

            self._check_and_trigger_block(
                p,
                stk,
                cnt,
            )

    def update(self, price: float, ts: Optional[float] = None) -> None:
        """Alias for record_trade_price."""
        self.record_trade_price(price, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_markov_metrics(self) -> Dict[str, Any]:
        with self._lock:
            persistence = self._calculate_persistence() if len(self._transitions) >= 4 else self._latest_persistence
            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "persistence_probability": float(persistence),
                "directional_streak_len": int(self._streak_len),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_markov_metrics()

    def reset(self) -> None:
        with self._lock:
            self._transitions.clear()
            self._last_price = None
            self._last_direction = None
            self._streak_len = 0
            self._latest_persistence = 0.50
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
