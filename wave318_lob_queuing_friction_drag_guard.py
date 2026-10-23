"""
wave318_lob_queuing_friction_drag_guard.py
-----------------------------------------
Guard: LOB Bid-Ask Effective Queuing Friction & Slippage Drag Guard

Monitors limit order book effective half-spread friction and depth-penalized execution drag,
guarding against acute queue evaporation, prohibitive round-trip transaction costs, and adverse slippage traps
(Stoll 2000; Amihud 2002; Hasbrouck 2007; Almgren & Chriss 2000):
    Bid and Ask Quotes:           p_{bid}, p_{ask}
    Mid-Price:                    p_{mid} = (p_{bid} + p_{ask}) / 2
    Half-Spread Friction:         F_{spread} = ((p_{ask} - p_{bid}) / (2 * p_{mid})) * 10000  (in bps)
    Inside Top Depth:             Q_1 = (q_{bid, 1} + q_{ask, 1}) in lots
    Effective Friction Drag:      Phi_{drag} = F_{spread} * (1.0 + V_{target} / max(Q_1, 0.20))
                                  (for benchmark order size V_{target} = 1.0 lot)
    Rolling Mean Friction:        \\bar{Phi}_{drag} = (1 / N) * sum_{i=1}^N Phi_{drag, i}

Under healthy liquid quoting conditions:
    - Transaction costs and market impact are modest and tightly bounded:
      Phi_{drag} <= 2.00 bps, Q_1 >= 2.50 lots.

Under thin books, predatory liquidity withdrawal, or prohibitive queuing friction:
    - Orders face excessive market impact drag and queue penalties:
        1) Friction Drag Surge:
           Rolling mean friction drag \\bar{Phi}_{drag} >= MAX_FRICTION_DRAG_BPS (default: 4.20 bps)
           with average spread S >= MIN_SPREAD_BPS (default: 2.20 bps)
           over rolling N >= MIN_SAMPLES (default: 10 snapshots).
        2) Acute Queuing Freeze Shock:
           Instantaneous Phi_{drag} >= ACUTE_FRICTION_DRAG_BPS (default: 7.00 bps),
           OR acute inside depth Q_1 <= ACUTE_MIN_DEPTH_LOTS (default: 0.15 lots) with spread S >= 3.00 bps.

Entering orders during prohibitive queuing friction guarantees paying severe fill drag and
incurring immediate adverse execution slippage.

When friction drag surge or an acute queuing freeze shock is detected, entry orders
are blocked for COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests quotes and depth via record_lob_friction(bid, ask, bid_depth, ask_depth, ts=None) or
  direct metrics via record_friction_metrics(friction_drag_bps, spread_bps=None, sample_count=None, ts=None).
- Rolling window of WINDOW_SIZE = 25 snapshots.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, non-positive quotes/depths are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_lob_friction(bid, ask, bid_depth, ask_depth, ts=None)                                 -> None
  record_friction_metrics(friction_drag_bps, spread_bps=None, sample_count=None, ts=None)      -> None
  update(bid, ask, bid_depth, ask_depth, ts=None)                                              -> None   (alias)
  get_friction_metrics()                                                                       -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional


class Wave318LobQueuingFrictionDragGuard:
    """
    Guards against prohibitive LOB queuing friction, depth-penalized execution drag, and acute slippage traps.
    """

    MAX_FRICTION_DRAG_BPS: float = 4.20
    MIN_SPREAD_BPS: float = 2.20
    MIN_SAMPLES: int = 10
    ACUTE_FRICTION_DRAG_BPS: float = 7.00
    ACUTE_MIN_DEPTH_LOTS: float = 0.15
    ACUTE_MIN_SPREAD_BPS: float = 3.00
    BENCHMARK_VOLUME_LOTS: float = 1.00
    WINDOW_SIZE: int = 25
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_friction_drag_bps: float = MAX_FRICTION_DRAG_BPS,
        min_spread_bps: float = MIN_SPREAD_BPS,
        min_samples: int = MIN_SAMPLES,
        acute_friction_drag_bps: float = ACUTE_FRICTION_DRAG_BPS,
        acute_min_depth_lots: float = ACUTE_MIN_DEPTH_LOTS,
        acute_min_spread_bps: float = ACUTE_MIN_SPREAD_BPS,
        benchmark_volume_lots: float = BENCHMARK_VOLUME_LOTS,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_friction_drag_bps = float(max_friction_drag_bps)
        self.min_spread_bps = float(min_spread_bps)
        self.min_samples = int(min_samples)
        self.acute_friction_drag_bps = float(acute_friction_drag_bps)
        self.acute_min_depth_lots = float(acute_min_depth_lots)
        self.acute_min_spread_bps = float(acute_min_spread_bps)
        self.benchmark_volume_lots = float(benchmark_volume_lots)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._drags = collections.deque(maxlen=self.window_size)
        self._spreads = collections.deque(maxlen=self.window_size)

        self._latest_drag_bps: float = 1.0
        self._latest_mean_drag_bps: float = 1.0
        self._latest_spread_bps: float = 1.0
        self._latest_depth_lots: float = 5.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _check_and_trigger_block(
        self,
        drag_bps: float,
        mean_drag_bps: float,
        spread_bps: float,
        mean_spread_bps: float,
        depth_lots: float,
        count: int,
    ) -> bool:
        # 1. Acute queuing freeze shock
        if drag_bps >= self.acute_friction_drag_bps:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_QUEUING_FRICTION_SHOCK: drag={drag_bps:.2f} >= {self.acute_friction_drag_bps:.2f} bps "
                f"(spread={spread_bps:.2f} bps, depth={depth_lots:.2f} lots)"
            )
            return True

        if depth_lots <= self.acute_min_depth_lots and spread_bps >= self.acute_min_spread_bps:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_QUEUE_EVAPORATION: depth={depth_lots:.2f} <= {self.acute_min_depth_lots:.2f} lots "
                f"with spread={spread_bps:.2f} >= {self.acute_min_spread_bps:.2f} bps"
            )
            return True

        # 2. Friction drag surge
        if count >= self.min_samples and mean_drag_bps >= self.max_friction_drag_bps and mean_spread_bps >= self.min_spread_bps:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"FRICTION_DRAG_SURGE: mean_drag={mean_drag_bps:.2f} >= {self.max_friction_drag_bps:.2f} bps "
                f"with mean_spread={mean_spread_bps:.2f} >= {self.min_spread_bps:.2f} bps over N={count}"
            )
            return True

        return False

    def record_lob_friction(
        self,
        bid: float,
        ask: float,
        bid_depth: float,
        ask_depth: float,
        ts: Optional[float] = None,
    ) -> None:
        """
        Record instantaneous quotes and depths in lots.
        """
        with self._lock:
            if (
                not self._is_valid_num(bid)
                or not self._is_valid_num(ask)
                or not self._is_valid_num(bid_depth)
                or not self._is_valid_num(ask_depth)
                or bid <= 0.0
                or ask <= 0.0
                or ask <= bid
                or bid_depth < 0.0
                or ask_depth < 0.0
            ):
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_LOB_FRICTION_INPUT"
                return

            mid = (bid + ask) / 2.0
            spread_bps = ((ask - bid) / mid) * 10000.0
            half_spread_bps = spread_bps / 2.0

            q_1 = float(bid_depth) + float(ask_depth)
            penalty = 1.0 + (self.benchmark_volume_lots / max(q_1, 0.20))
            drag_bps = half_spread_bps * penalty

            self._drags.append(drag_bps)
            self._spreads.append(spread_bps)
            self._sample_count += 1

            mean_drag = statistics.fmean(self._drags)
            mean_spr = statistics.fmean(self._spreads)

            self._latest_drag_bps = drag_bps
            self._latest_mean_drag_bps = mean_drag
            self._latest_spread_bps = spread_bps
            self._latest_depth_lots = q_1

            self._check_and_trigger_block(
                drag_bps,
                mean_drag,
                spread_bps,
                mean_spr,
                q_1,
                len(self._drags),
            )

    def record_friction_metrics(
        self,
        friction_drag_bps: float,
        spread_bps: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed friction drag metrics.
        """
        with self._lock:
            if not self._is_valid_num(friction_drag_bps) or friction_drag_bps < 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_DRAG_METRIC"
                return

            drag = float(friction_drag_bps)
            spr = float(spread_bps) if (self._is_valid_num(spread_bps) and spread_bps >= 0.0) else (self.min_spread_bps + 0.5)
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_samples

            self._latest_drag_bps = drag
            self._latest_mean_drag_bps = drag
            self._latest_spread_bps = spr
            self._sample_count = cnt

            self._check_and_trigger_block(
                drag,
                drag,
                spr,
                spr,
                2.0,
                cnt,
            )

    def update(
        self,
        bid: float,
        ask: float,
        bid_depth: float,
        ask_depth: float,
        ts: Optional[float] = None,
    ) -> None:
        """Alias for record_lob_friction."""
        self.record_lob_friction(bid, ask, bid_depth, ask_depth, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_friction_metrics(self) -> Dict[str, Any]:
        with self._lock:
            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "friction_drag_bps": float(self._latest_drag_bps),
                "mean_friction_drag_bps": float(self._latest_mean_drag_bps),
                "latest_spread_bps": float(self._latest_spread_bps),
                "latest_depth_lots": float(self._latest_depth_lots),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_friction_metrics()

    def reset(self) -> None:
        with self._lock:
            self._drags.clear()
            self._spreads.clear()
            self._latest_drag_bps = 1.0
            self._latest_mean_drag_bps = 1.0
            self._latest_spread_bps = 1.0
            self._latest_depth_lots = 5.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
