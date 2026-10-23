"""
wave319_trade_arrival_volatility_signature_guard.py
---------------------------------------------------
Guard: High-Frequency Trade Arrival Inter-Trade Return Volatility Signature Guard

Monitors realized inter-trade tick volatility RV_{tick} and discontinuous price jump leaps,
guarding against high-frequency volatility signature explosions, predatory news cascades, and flash dislocations
(Andersen & Bollerslev 1998; Engle & Sun 2007; Barndorff-Nielsen & Shephard 2002; Hansen & Lunde 2006):
    Trade Execution Price:        p_t
    Inter-Trade Log Return:       r_t = ln(p_t / p_{t-1}) * 10000  (in bps)
    Realized Tick Volatility:     RV_{tick} = sqrt((1 / N) * sum_{i=1}^N r_i^2)  (in bps / trade)
    Inter-Trade Jump Leap:        |r_t| in bps

Under calm, continuous trading conditions:
    - Tick-by-tick return volatility is tightly clustered and low:
      RV_{tick} in [0.20, 1.50] bps/trade, with rare individual ticks exceeding 2.00 bps.

Under sudden volatility shocks, toxic institutional sweeping, or flash panic:
    - High-frequency volatility signature explodes:
        1) Tick Volatility Signature Surge:
           Realized tick volatility RV_{tick} >= MAX_TICK_VOLATILITY_BPS (default: 2.80 bps/trade)
           over rolling N >= MIN_SAMPLES (default: 15 trades).
        2) Acute Trade Dislocation Jump:
           Single inter-trade return jump |r_t| >= ACUTE_PRICE_JUMP_BPS (default: 4.50 bps).

Entering orders during active volatility signature explosions guarantees extreme execution uncertainty,
wide bid-ask slippage, and immediate adverse price movement.

When volatility signature surge or an acute price jump is detected, entry orders
are blocked for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade price via record_trade_price(price, ts=None) or record_return(return_bps, ts=None) or
  direct metrics via record_volatility_metrics(tick_volatility_bps, max_jump_bps=None, sample_count=None, ts=None).
- Rolling window of WINDOW_SIZE = 25 returns.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive prices are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_trade_price(price, ts=None)                                                           -> None
  record_return(return_bps, ts=None)                                                           -> None
  record_volatility_metrics(tick_volatility_bps, max_jump_bps=None, sample_count=None, ts=None) -> None
  update(price, ts=None)                                                                       -> None   (alias)
  get_volatility_metrics()                                                                     -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave319TradeArrivalVolatilitySignatureGuard:
    """
    Guards against inter-trade tick volatility signature explosions, flash panic, and discontinuous price leaps.
    """

    MAX_TICK_VOLATILITY_BPS: float = 2.80
    MIN_SAMPLES: int = 15
    ACUTE_PRICE_JUMP_BPS: float = 4.50
    WINDOW_SIZE: int = 25
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_tick_volatility_bps: float = MAX_TICK_VOLATILITY_BPS,
        min_samples: int = MIN_SAMPLES,
        acute_price_jump_bps: float = ACUTE_PRICE_JUMP_BPS,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_tick_volatility_bps = float(max_tick_volatility_bps)
        self.min_samples = int(min_samples)
        self.acute_price_jump_bps = float(acute_price_jump_bps)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._returns = collections.deque(maxlen=self.window_size)

        self._last_price: Optional[float] = None

        self._latest_volatility: float = 0.50
        self._latest_jump: float = 0.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _calculate_volatility(self) -> float:
        if not self._returns:
            return 0.50
        ms = statistics.fmean(r ** 2 for r in self._returns)
        return math.sqrt(ms)

    def _check_and_trigger_block(
        self,
        volatility: float,
        acute_jump: float,
        count: int,
    ) -> bool:
        # 1. Acute trade price dislocation jump
        if abs(acute_jump) >= self.acute_price_jump_bps:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_PRICE_DISLOCATION_JUMP: |jump|={abs(acute_jump):.2f} >= {self.acute_price_jump_bps:.2f} bps"
            )
            return True

        # 2. Tick volatility signature surge
        if count >= self.min_samples and volatility >= self.max_tick_volatility_bps:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"TICK_VOLATILITY_SURGE: RV_tick={volatility:.2f} >= {self.max_tick_volatility_bps:.2f} bps/trade "
                f"over N={count} trades"
            )
            return True

        return False

    def record_return(self, return_bps: float, ts: Optional[float] = None) -> None:
        """
        Record inter-trade return in bps directly.
        """
        with self._lock:
            if not self._is_valid_num(return_bps):
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_RETURN_INPUT"
                return

            ret = float(return_bps)
            self._returns.append(ret)
            self._sample_count += 1

            rv = self._calculate_volatility()
            self._latest_volatility = rv
            self._latest_jump = abs(ret)

            self._check_and_trigger_block(
                rv,
                ret,
                len(self._returns),
            )

    def record_trade_price(self, price: float, ts: Optional[float] = None) -> None:
        """
        Record trade execution price and calculate log return in bps.
        """
        with self._lock:
            if not self._is_valid_num(price) or price <= 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_PRICE_INPUT"
                return

            p = float(price)
            if self._last_price is not None:
                ret_bps = math.log(p / self._last_price) * 10000.0
                self.record_return(ret_bps, ts=ts)
            self._last_price = p

    def record_volatility_metrics(
        self,
        tick_volatility_bps: float,
        max_jump_bps: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed tick volatility metrics.
        """
        with self._lock:
            if not self._is_valid_num(tick_volatility_bps) or tick_volatility_bps < 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_VOLATILITY_METRIC"
                return

            rv = float(tick_volatility_bps)
            jmp = float(max_jump_bps) if (self._is_valid_num(max_jump_bps) and max_jump_bps >= 0.0) else 0.50
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_samples

            self._latest_volatility = rv
            self._latest_jump = jmp
            self._sample_count = cnt

            self._check_and_trigger_block(
                rv,
                self.acute_price_jump_bps + 1.0 if rv >= 5.0 else jmp,
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

    def get_volatility_metrics(self) -> Dict[str, Any]:
        with self._lock:
            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "tick_volatility_bps": float(self._latest_volatility),
                "latest_jump_bps": float(self._latest_jump),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_volatility_metrics()

    def reset(self) -> None:
        with self._lock:
            self._returns.clear()
            self._last_price = None
            self._latest_volatility = 0.50
            self._latest_jump = 0.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
