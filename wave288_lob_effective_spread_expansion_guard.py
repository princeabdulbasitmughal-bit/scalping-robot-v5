"""
wave288_lob_effective_spread_expansion_guard.py
-----------------------------------------------
Guard: LOB Realized Effective Spread Blowout & Execution Cost Expansion Guard

Monitors realized effective spread, effective-to-quoted spread ratio, and order book penetration depth
(Roll 1984; Stoll 1989; Bessembinder 2003; Hasbrouck 2009):
    Midpoint Price:              M = (Ask + Bid) / 2
    Quoted Spread:               S_{quote} = (Ask - Bid) / M * 10,000 in bps
    Effective Spread:            S_{eff} = 2 * D * (P_{trade} - M) / M * 10,000 in bps  where D in {+1, -1}
    Effective-to-Quoted Ratio:   R_{EQ} = S_{eff} / max(S_{quote}, 0.20)

Under competitive, deep limit order book conditions:
    - Executions occur at or inside the quotes: S_{eff} <= 1.80 bps, R_{EQ} in [0.70, 1.20].
    - Walking the book is rare, preserving low transaction friction.

During predatory sweeping runs, inventory evaporation, or aggressive multi-tick market orders:
    - Executions blow through multiple depth levels, causing effective spreads to surge:
        1) Effective Spread Blowout:
           Rolling mean effective spread \\bar{S}_{eff} >= MAX_MEAN_EFFECTIVE_SPREAD_BPS (default: 3.80 bps)
           with mean ratio \\bar{R}_{EQ} >= MIN_EQ_RATIO (default: 2.20)
           over rolling N >= MIN_TRADES (default: 10 executions).
        2) Acute Spread Blowout:
           Instantaneous effective spread S_{eff} >= ACUTE_EFFECTIVE_SPREAD_BPS (default: 6.50 bps).

Entering trades when effective spreads are blown out subjects market orders to extreme adverse pricing,
severe price-walking penalties, and negative expected returns.

When effective spread blowout or an acute spread shock is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests trade execution via record_execution(trade_price, bid_price, ask_price, direction, ts=None) or
  direct metrics via record_effective_metrics(effective_bps, eq_ratio=None, sample_count=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 20 execution observations.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or invalid directions are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_execution(trade_price, bid_price, ask_price, direction, ts=None)                      -> None
  record_effective_metrics(effective_bps, eq_ratio=None, sample_count=None, ts=None)           -> None
  update(trade_price, bid_price, ask_price, direction, ts=None)                                -> None   (alias)
  get_effective_spread_metrics()                                                               -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, Optional


class Wave288LobEffectiveSpreadExpansionGuard:
    """
    Guards against realized effective spread blowouts, deep book penetration, and severe liquidity premia.
    """

    MAX_MEAN_EFFECTIVE_SPREAD_BPS: float = 3.80
    MIN_EQ_RATIO: float = 2.20
    MIN_TRADES: int = 10
    ACUTE_EFFECTIVE_SPREAD_BPS: float = 6.50
    WINDOW_SIZE: int = 20
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_mean_effective_spread_bps: float = MAX_MEAN_EFFECTIVE_SPREAD_BPS,
        min_eq_ratio: float = MIN_EQ_RATIO,
        min_trades: int = MIN_TRADES,
        acute_effective_spread_bps: float = ACUTE_EFFECTIVE_SPREAD_BPS,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_mean_effective_spread_bps = float(max_mean_effective_spread_bps)
        self.min_eq_ratio = float(min_eq_ratio)
        self.min_trades = int(min_trades)
        self.acute_effective_spread_bps = float(acute_effective_spread_bps)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._effective_history = collections.deque(maxlen=self.window_size)
        self._ratio_history = collections.deque(maxlen=self.window_size)

        self._latest_effective_bps: float = 0.0
        self._latest_eq_ratio: float = 1.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _check_and_trigger_block(
        self,
        mean_eff: float,
        acute_eff: float,
        mean_ratio: float,
        sample_count: int,
    ) -> bool:
        # 1. Acute effective spread blowout
        if acute_eff >= self.acute_effective_spread_bps:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_EFFECTIVE_SPREAD_BLOWOUT: acute_eff={acute_eff:.2f}bps >= {self.acute_effective_spread_bps:.2f}bps"
            )
            return True

        # 2. Persistent effective spread expansion
        if (
            sample_count >= self.min_trades
            and mean_eff >= self.max_mean_effective_spread_bps
            and mean_ratio >= self.min_eq_ratio
        ):
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"EFFECTIVE_SPREAD_EXPANSION: mean_eff={mean_eff:.2f}bps >= {self.max_mean_effective_spread_bps:.2f}bps, "
                f"ratio={mean_ratio:.2f} >= {self.min_eq_ratio:.2f} (N={sample_count})"
            )
            return True

        return False

    def record_execution(
        self,
        trade_price: float,
        bid_price: float,
        ask_price: float,
        direction: int,
        ts: Optional[float] = None,
    ) -> None:
        """
        Record a trade fill with prevailing touch prices and trade direction (+1 buy, -1 sell).
        """
        with self._lock:
            if (
                not self._is_valid_num(trade_price)
                or not self._is_valid_num(bid_price)
                or not self._is_valid_num(ask_price)
                or not self._is_valid_num(direction)
                or trade_price <= 0.0
                or bid_price <= 0.0
                or ask_price <= 0.0
                or ask_price < bid_price
                or int(direction) not in (-1, 1)
            ):
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_EXECUTION_INPUT"
                return

            px = float(trade_price)
            bid = float(bid_price)
            ask = float(ask_price)
            d = int(direction)

            mid = (bid + ask) / 2.0
            quoted_bps = ((ask - bid) / mid) * 10000.0
            effective_bps = max(0.0, 2.0 * d * (px - mid) / mid * 10000.0)
            eq_ratio = effective_bps / max(quoted_bps, 0.20)

            self._latest_effective_bps = effective_bps
            self._latest_eq_ratio = eq_ratio
            self._effective_history.append(effective_bps)
            self._ratio_history.append(eq_ratio)
            self._sample_count += 1

            mean_eff = statistics.mean(self._effective_history) if self._effective_history else effective_bps
            mean_ratio = statistics.mean(self._ratio_history) if self._ratio_history else eq_ratio

            self._check_and_trigger_block(
                mean_eff,
                effective_bps,
                mean_ratio,
                self._sample_count,
            )

    def record_effective_metrics(
        self,
        effective_bps: float,
        eq_ratio: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed effective spread metrics.
        """
        with self._lock:
            if not self._is_valid_num(effective_bps) or effective_bps < 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_EFFECTIVE_METRIC"
                return

            eff = float(effective_bps)
            ratio = float(eq_ratio) if (self._is_valid_num(eq_ratio) and eq_ratio >= 0.0) else self.min_eq_ratio + 0.50
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_trades

            self._latest_effective_bps = eff
            self._latest_eq_ratio = ratio
            self._sample_count = cnt
            self._effective_history.append(eff)
            self._ratio_history.append(ratio)

            mean_eff = statistics.mean(self._effective_history) if self._effective_history else eff
            mean_ratio = statistics.mean(self._ratio_history) if self._ratio_history else ratio

            self._check_and_trigger_block(
                mean_eff,
                eff,
                mean_ratio,
                cnt,
            )

    def update(
        self,
        trade_price: float,
        bid_price: float,
        ask_price: float,
        direction: int,
        ts: Optional[float] = None,
    ) -> None:
        """Alias for record_execution."""
        self.record_execution(trade_price, bid_price, ask_price, direction, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_effective_spread_metrics(self) -> Dict[str, Any]:
        with self._lock:
            if self._effective_history:
                mean_eff = statistics.mean(self._effective_history)
                max_eff = max(self._effective_history)
            else:
                mean_eff = self._latest_effective_bps
                max_eff = self._latest_effective_bps

            if self._ratio_history:
                mean_ratio = statistics.mean(self._ratio_history)
            else:
                mean_ratio = self._latest_eq_ratio

            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "mean_effective_spread_bps": float(mean_eff),
                "max_effective_spread_bps": float(max_eff),
                "mean_eq_ratio": float(mean_ratio),
                "latest_effective_spread_bps": float(self._latest_effective_bps),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_effective_spread_metrics()

    def reset(self) -> None:
        with self._lock:
            self._effective_history.clear()
            self._ratio_history.clear()
            self._latest_effective_bps = 0.0
            self._latest_eq_ratio = 1.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
