"""
wave290_lob_quote_cancellation_ratio_guard.py
---------------------------------------------
Guard: LOB Quote-to-Trade Ratio & Cancellation Intensity Guard

Monitors limit order book quote cancellation rates, quote-to-trade ratio, and phantom liquidity stuffing
(Biais et al. 1995; Hasbrouck & Saar 2009, 2013; Cartea & Jaimungal 2014):
    Sliding Window:               Delta T = 10.0 seconds
    Quote Cancellations in Window: N_{cancel}
    Trades Executed in Window:    N_{trade}
    Quote-to-Trade Ratio:         R_{Q/T} = N_{cancel} / max(N_{trade}, 1)
    Acute Burst Window:           Delta t <= 0.50 seconds

Under organic, bona fide electronic market making:
    - Participants post resting depth with authentic execution intent:
      R_{Q/T} in [2.0, 15.0], with steady execution clearance.

During algorithmic spoofing, phantom quote layering, or quote stuffing:
    - High-frequency algorithms post and cancel hundreds of resting quotes without executing trades:
        1) Excessive Quote-to-Trade Cancellation Ratio:
           R_{Q/T} >= MAX_QUOTE_TRADE_RATIO (default: 35.0)
           with cancellations N_{cancel} >= MIN_CANCELLATIONS (default: 50)
           over rolling window W = 10.0s.
        2) Acute Phantom Cancellation Burst:
           N_{cancel} >= ACUTE_BURST_CANCELLATIONS (default: 30 cancellations)
           within Delta t <= ACUTE_BURST_WINDOW_SEC (default: 0.50s) with 0 trades.

Routing orders into phantom depth environments guarantees high cancellation race latency,
sudden depth vaporization, and devastating adverse execution.

When excessive cancellation ratio or an acute phantom burst is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests events via record_cancellation(ts=None) and record_trade(ts=None) or
  direct metrics via record_cancellation_metrics(quote_trade_ratio, cancel_count=None, trade_count=None, ts=None).
- Maintains sliding window timestamps of cancellations and trades.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or negative timestamps/counts are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_cancellation(ts=None)                                                                 -> None
  record_trade(ts=None)                                                                        -> None
  record_cancellation_metrics(quote_trade_ratio, cancel_count=None, trade_count=None, ts=None) -> None
  update(quote_trade_ratio, cancel_count=None, ts=None)                                        -> None   (alias)
  get_cancellation_metrics()                                                                   -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave290LobQuoteCancellationRatioGuard:
    """
    Guards against high-frequency phantom quote stuffing, spoofing layering, and depth vaporization.
    """

    MAX_QUOTE_TRADE_RATIO: float = 35.0
    MIN_CANCELLATIONS: int = 50
    ACUTE_BURST_CANCELLATIONS: int = 30
    ACUTE_BURST_WINDOW_SEC: float = 0.50
    WINDOW_SEC: float = 10.0
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_quote_trade_ratio: float = MAX_QUOTE_TRADE_RATIO,
        min_cancellations: int = MIN_CANCELLATIONS,
        acute_burst_cancellations: int = ACUTE_BURST_CANCELLATIONS,
        acute_burst_window_sec: float = ACUTE_BURST_WINDOW_SEC,
        window_sec: float = WINDOW_SEC,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_quote_trade_ratio = float(max_quote_trade_ratio)
        self.min_cancellations = int(min_cancellations)
        self.acute_burst_cancellations = int(acute_burst_cancellations)
        self.acute_burst_window_sec = float(acute_burst_window_sec)
        self.window_sec = float(window_sec)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._cancel_timestamps = collections.deque()
        self._trade_timestamps = collections.deque()

        self._latest_ratio: float = 1.0
        self._latest_cancel_count: int = 0
        self._latest_trade_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _purge_old_events(self, now_ts: float) -> None:
        cutoff = now_ts - self.window_sec
        while self._cancel_timestamps and self._cancel_timestamps[0] < cutoff:
            self._cancel_timestamps.popleft()
        while self._trade_timestamps and self._trade_timestamps[0] < cutoff:
            self._trade_timestamps.popleft()

    def _check_and_trigger_block(
        self,
        ratio: float,
        cancel_cnt: int,
        trade_cnt: int,
        burst_cancel_cnt: int,
    ) -> bool:
        # 1. Acute phantom cancellation burst
        if burst_cancel_cnt >= self.acute_burst_cancellations:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_PHANTOM_BURST: cancellations={burst_cancel_cnt} >= {self.acute_burst_cancellations} "
                f"in dt <= {self.acute_burst_window_sec:.2f}s"
            )
            return True

        # 2. Excessive quote-to-trade cancellation ratio
        if cancel_cnt >= self.min_cancellations and ratio >= self.max_quote_trade_ratio:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"EXCESSIVE_CANCELLATION_RATIO: ratio={ratio:.1f} >= {self.max_quote_trade_ratio:.1f}, "
                f"cancels={cancel_cnt} >= {self.min_cancellations} (trades={trade_cnt})"
            )
            return True

        return False

    def record_cancellation(self, ts: Optional[float] = None) -> None:
        """
        Record a quote cancellation event timestamp.
        """
        with self._lock:
            now_ts = float(ts) if (self._is_valid_num(ts) and ts >= 0.0) else time.time()
            self._cancel_timestamps.append(now_ts)
            self._purge_old_events(now_ts)

            cancel_cnt = len(self._cancel_timestamps)
            trade_cnt = len(self._trade_timestamps)
            ratio = cancel_cnt / max(trade_cnt, 1)

            burst_cutoff = now_ts - self.acute_burst_window_sec
            burst_cancel_cnt = sum(1 for t in self._cancel_timestamps if t >= burst_cutoff)

            self._latest_ratio = ratio
            self._latest_cancel_count = cancel_cnt
            self._latest_trade_count = trade_cnt

            self._check_and_trigger_block(
                ratio,
                cancel_cnt,
                trade_cnt,
                burst_cancel_cnt,
            )

    def record_trade(self, ts: Optional[float] = None) -> None:
        """
        Record a filled trade execution event timestamp.
        """
        with self._lock:
            now_ts = float(ts) if (self._is_valid_num(ts) and ts >= 0.0) else time.time()
            self._trade_timestamps.append(now_ts)
            self._purge_old_events(now_ts)

            cancel_cnt = len(self._cancel_timestamps)
            trade_cnt = len(self._trade_timestamps)
            ratio = cancel_cnt / max(trade_cnt, 1)

            self._latest_ratio = ratio
            self._latest_cancel_count = cancel_cnt
            self._latest_trade_count = trade_cnt

    def record_cancellation_metrics(
        self,
        quote_trade_ratio: float,
        cancel_count: Optional[int] = None,
        trade_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed cancellation ratio metrics.
        """
        with self._lock:
            if not self._is_valid_num(quote_trade_ratio) or quote_trade_ratio < 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_CANCELLATION_METRIC"
                return

            ratio = float(quote_trade_ratio)
            c_cnt = int(cancel_count) if (self._is_valid_num(cancel_count) and cancel_count >= 0) else self.min_cancellations
            t_cnt = int(trade_count) if (self._is_valid_num(trade_count) and trade_count >= 0) else 1

            self._latest_ratio = ratio
            self._latest_cancel_count = c_cnt
            self._latest_trade_count = t_cnt

            self._check_and_trigger_block(
                ratio,
                c_cnt,
                t_cnt,
                c_cnt if ratio >= 50.0 else 0,
            )

    def update(
        self,
        quote_trade_ratio: float,
        cancel_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """Alias for record_cancellation_metrics."""
        self.record_cancellation_metrics(quote_trade_ratio, cancel_count=cancel_count, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_cancellation_metrics(self) -> Dict[str, Any]:
        with self._lock:
            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "quote_trade_ratio": float(self._latest_ratio),
                "cancellation_count": int(self._latest_cancel_count),
                "trade_count": int(self._latest_trade_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_cancellation_metrics()

    def reset(self) -> None:
        with self._lock:
            self._cancel_timestamps.clear()
            self._trade_timestamps.clear()
            self._latest_ratio = 1.0
            self._latest_cancel_count = 0
            self._latest_trade_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
