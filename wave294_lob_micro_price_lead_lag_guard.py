"""
wave294_lob_micro_price_lead_lag_guard.py
-----------------------------------------
Guard: LOB Stoikov Micro-Price Lead-Lag & Front-Running Drift Guard

Monitors limit order book Stoikov micro-price deviation from midpoint, predictive lead-lag bias, and quote front-running
(Stoikov 2018; Cont & de Larrard 2013; Lehalle & Mounjid 2017):
    Midpoint Price:              M = (P_{ask} + P_{bid}) / 2
    Stoikov Micro-Price:         P_{micro} = (Q_{bid} * P_{ask} + Q_{ask} * P_{bid}) / max(Q_{bid} + Q_{ask}, 1e-4)
    Micro-Price Deviation:       Delta_{micro} = (P_{micro} - M) / M * 10,000 in bps
    Rolling Mean Bias:           \\bar{Delta}_{micro} = (1 / N) * sum_{i=1}^N |Delta_{micro,i}|

Under symmetric, unpressured two-way liquidity quoting:
    - Queue depths on both sides remain balanced: Q_{bid} ~ Q_{ask}.
    - Micro-price hovers in close proximity to the midpoint: |Delta_{micro}| <= 1.00 bps.

During aggressive predatory front-running, queue pre-emption, or impending midpoint collapse:
    - Micro-price leads the midpoint with large, persistent directional bias, predicting an immediate adverse quote jump:
        1) Persistent Micro-Price Lead Bias:
           Rolling mean deviation |\\bar{Delta}_{micro}| >= MAX_MEAN_DEVIATION_BPS (default: 2.20 bps)
           with spread S_{bps} >= MIN_SPREAD_BPS (default: 2.00 bps)
           over rolling N >= MIN_SAMPLES (default: 12 book updates).
        2) Acute Micro-Price Shock:
           Instantaneous deviation |Delta_{micro}| >= ACUTE_DEVIATION_BPS (default: 4.50 bps).

Entering passive or market orders when micro-price is heavily skewed guarantees immediate adverse selection
and front-running by informed high-frequency traders.

When micro-price lead bias or an acute shock is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests top quotes via record_quotes(bid_px, ask_px, bid_qty, ask_qty, ts=None) or
  direct metrics via record_micro_price_metrics(deviation_bps, spread_bps=None, sample_count=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 20 observations.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or invalid quotes are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_quotes(bid_px, ask_px, bid_qty, ask_qty, ts=None)                                     -> None
  record_micro_price_metrics(deviation_bps, spread_bps=None, sample_count=None, ts=None)        -> None
  update(bid_px, ask_px, bid_qty, ask_qty, ts=None)                                            -> None   (alias)
  get_micro_price_metrics()                                                                    -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, Optional


class Wave294LobMicroPriceLeadLagGuard:
    """
    Guards against LOB Stoikov micro-price front-running, queue skew bias, and impending quote jumps.
    """

    MAX_MEAN_DEVIATION_BPS: float = 2.20
    MIN_SPREAD_BPS: float = 2.00
    MIN_SAMPLES: int = 12
    ACUTE_DEVIATION_BPS: float = 4.50
    WINDOW_SIZE: int = 20
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_mean_deviation_bps: float = MAX_MEAN_DEVIATION_BPS,
        min_spread_bps: float = MIN_SPREAD_BPS,
        min_samples: int = MIN_SAMPLES,
        acute_deviation_bps: float = ACUTE_DEVIATION_BPS,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_mean_deviation_bps = float(max_mean_deviation_bps)
        self.min_spread_bps = float(min_spread_bps)
        self.min_samples = int(min_samples)
        self.acute_deviation_bps = float(acute_deviation_bps)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._dev_history = collections.deque(maxlen=self.window_size)
        self._spread_history = collections.deque(maxlen=self.window_size)

        self._latest_deviation_bps: float = 0.0
        self._latest_spread_bps: float = 0.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _check_and_trigger_block(
        self,
        mean_dev: float,
        acute_dev: float,
        mean_spread: float,
        sample_count: int,
    ) -> bool:
        # 1. Acute micro-price shock
        if abs(acute_dev) >= self.acute_deviation_bps:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_MICRO_PRICE_SHOCK: deviation={acute_dev:.2f}bps >= {self.acute_deviation_bps:.2f}bps"
            )
            return True

        # 2. Persistent micro-price lead bias
        if (
            sample_count >= self.min_samples
            and mean_dev >= self.max_mean_deviation_bps
            and mean_spread >= self.min_spread_bps
        ):
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"MICRO_PRICE_LEAD_BIAS: mean_dev={mean_dev:.2f}bps >= {self.max_mean_deviation_bps:.2f}bps, "
                f"spread={mean_spread:.2f}bps >= {self.min_spread_bps:.2f}bps (N={sample_count})"
            )
            return True

        return False

    def record_quotes(
        self,
        bid_px: float,
        ask_px: float,
        bid_qty: float,
        ask_qty: float,
        ts: Optional[float] = None,
    ) -> None:
        """
        Record top-of-book prices and quantities, calculating Stoikov micro-price deviation.
        """
        with self._lock:
            if (
                not self._is_valid_num(bid_px)
                or not self._is_valid_num(ask_px)
                or not self._is_valid_num(bid_qty)
                or not self._is_valid_num(ask_qty)
                or bid_px <= 0.0
                or ask_px <= 0.0
                or ask_px < bid_px
                or bid_qty < 0.0
                or ask_qty < 0.0
                or (bid_qty == 0.0 and ask_qty == 0.0)
            ):
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_QUOTES_INPUT"
                return

            bp = float(bid_px)
            ap = float(ask_px)
            bq = float(bid_qty)
            aq = float(ask_qty)

            mid = (bp + ap) / 2.0
            spread_bps = ((ap - bp) / mid) * 10000.0
            micro_px = (bq * ap + aq * bp) / (bq + aq)
            dev_bps = ((micro_px - mid) / mid) * 10000.0

            self._latest_deviation_bps = dev_bps
            self._latest_spread_bps = spread_bps
            self._dev_history.append(abs(dev_bps))
            self._spread_history.append(spread_bps)
            self._sample_count += 1

            mean_dev = statistics.mean(self._dev_history) if self._dev_history else abs(dev_bps)
            mean_spr = statistics.mean(self._spread_history) if self._spread_history else spread_bps

            self._check_and_trigger_block(
                mean_dev,
                dev_bps,
                mean_spr,
                self._sample_count,
            )

    def record_micro_price_metrics(
        self,
        deviation_bps: float,
        spread_bps: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed micro-price deviation metrics.
        """
        with self._lock:
            if not self._is_valid_num(deviation_bps):
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_DEVIATION_METRIC"
                return

            dev = float(deviation_bps)
            spr = float(spread_bps) if (self._is_valid_num(spread_bps) and spread_bps >= 0.0) else self.min_spread_bps + 1.0
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_samples

            self._latest_deviation_bps = dev
            self._latest_spread_bps = spr
            self._sample_count = cnt
            self._dev_history.append(abs(dev))
            self._spread_history.append(spr)

            mean_dev = statistics.mean(self._dev_history) if self._dev_history else abs(dev)
            mean_spr = statistics.mean(self._spread_history) if self._spread_history else spr

            self._check_and_trigger_block(
                mean_dev,
                dev,
                mean_spr,
                cnt,
            )

    def update(
        self,
        bid_px: float,
        ask_px: float,
        bid_qty: float,
        ask_qty: float,
        ts: Optional[float] = None,
    ) -> None:
        """Alias for record_quotes."""
        self.record_quotes(bid_px, ask_px, bid_qty, ask_qty, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_micro_price_metrics(self) -> Dict[str, Any]:
        with self._lock:
            if self._dev_history:
                mean_dev = statistics.mean(self._dev_history)
                max_dev = max(self._dev_history)
            else:
                mean_dev = abs(self._latest_deviation_bps)
                max_dev = abs(self._latest_deviation_bps)

            if self._spread_history:
                mean_spr = statistics.mean(self._spread_history)
            else:
                mean_spr = self._latest_spread_bps

            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "mean_deviation_bps": float(mean_dev),
                "max_deviation_bps": float(max_dev),
                "latest_deviation_bps": float(self._latest_deviation_bps),
                "mean_spread_bps": float(mean_spr),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_micro_price_metrics()

    def reset(self) -> None:
        with self._lock:
            self._dev_history.clear()
            self._spread_history.clear()
            self._latest_deviation_bps = 0.0
            self._latest_spread_bps = 0.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
