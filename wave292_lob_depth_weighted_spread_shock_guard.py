"""
wave292_lob_depth_weighted_spread_shock_guard.py
------------------------------------------------
Guard: LOB Depth-Weighted Spread & Multi-Level Liquidity Squeeze Guard

Monitors multi-level limit order book depth-weighted spread, deep book gap width, and liquidity squeeze shocks
(Lee & Ready 1991; Biais, Hillion & Spatt 1995; Irvine, Benston & Kandel 2000; Cao, Hansch & Wang 2009):
    Multi-Tier Levels:           k = 1, 2, ..., L  (default: L = 3 tiers)
    Tier Spreads:                S_k = Ask_k - Bid_k
    Tier Combined Depth:         W_k = Q_{bid,k} + Q_{ask,k}
    Depth-Weighted Spread:       S_{depth} = sum_{k=1}^L (S_k * W_k) / max(sum_{k=1}^L W_k, 0.10)
    Normalized Spread bps:       S_{depth,bps} = (S_{depth} / Mid) * 10,000 in bps

Under competitive, deep market conditions:
    - Order book depth is densely layered with tight step intervals across levels 1 through 3:
      S_{depth,bps} <= 2.80 bps.
    - Outer book levels provide substantial liquidity cushion against large sweeps.

During liquidity squeezes, multi-tier dealer flight, or flash book thinning:
    - Inside spread may appear deceptively normal while outer levels sit at massive, hollow price gaps:
        1) Depth-Weighted Spread Squeeze:
           Rolling mean depth-weighted spread \\bar{S}_{depth,bps} >= MAX_MEAN_SPREAD_BPS (default: 4.20 bps)
           over rolling N >= MIN_SAMPLES (default: 8 book snapshots).
        2) Acute Multi-Level Squeeze Blowout:
           Instantaneous depth-weighted spread S_{depth,bps} >= ACUTE_SPREAD_BPS (default: 7.00 bps).

Executing orders during depth-weighted spread squeezes risks catastrophic fill degradation as soon as
Level-1 depth is exhausted, walking the order deep into penal price tiers.

When depth-weighted spread squeeze or an acute blowout is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests book snapshot via record_book_depth(bids, asks, ts=None) or
  direct metrics via record_depth_spread_metrics(spread_bps, sample_count=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 15 snapshots.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or inverted book levels are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_book_depth(bids, asks, ts=None)                                                       -> None
  record_depth_spread_metrics(spread_bps, sample_count=None, ts=None)                          -> None
  update(spread_bps, ts=None)                                                                  -> None   (alias)
  get_depth_spread_metrics()                                                                   -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


class Wave292LobDepthWeightedSpreadShockGuard:
    """
    Guards against multi-tier LOB liquidity squeezes, hollow deep books, and multi-level price shocks.
    """

    MAX_MEAN_SPREAD_BPS: float = 4.20
    MIN_SAMPLES: int = 8
    ACUTE_SPREAD_BPS: float = 7.00
    WINDOW_SIZE: int = 15
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        max_mean_spread_bps: float = MAX_MEAN_SPREAD_BPS,
        min_samples: int = MIN_SAMPLES,
        acute_spread_bps: float = ACUTE_SPREAD_BPS,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.max_mean_spread_bps = float(max_mean_spread_bps)
        self.min_samples = int(min_samples)
        self.acute_spread_bps = float(acute_spread_bps)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._spread_history = collections.deque(maxlen=self.window_size)

        self._latest_spread_bps: float = 0.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _check_and_trigger_block(self, mean_spr: float, acute_spr: float, sample_count: int) -> bool:
        # 1. Acute multi-level squeeze blowout
        if acute_spr >= self.acute_spread_bps:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_DEPTH_SPREAD_BLOWOUT: acute_spread={acute_spr:.2f}bps >= {self.acute_spread_bps:.2f}bps"
            )
            return True

        # 2. Depth-weighted spread squeeze persistence
        if sample_count >= self.min_samples and mean_spr >= self.max_mean_spread_bps:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"DEPTH_SPREAD_SQUEEZE: mean_spread={mean_spr:.2f}bps >= {self.max_mean_spread_bps:.2f}bps (N={sample_count})"
            )
            return True

        return False

    def record_book_depth(
        self,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        ts: Optional[float] = None,
    ) -> None:
        """
        Record order book snapshot with bids [(price, qty), ...] and asks [(price, qty), ...].
        """
        with self._lock:
            if not isinstance(bids, list) or not isinstance(asks, list) or len(bids) == 0 or len(asks) == 0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_BOOK_SNAPSHOT"
                return

            levels = min(len(bids), len(asks), 3)
            num_weighted_spread = 0.0
            total_weight = 0.0

            best_bid = bids[0][0]
            best_ask = asks[0][0]

            if not self._is_valid_num(best_bid) or not self._is_valid_num(best_ask) or best_ask < best_bid:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_BOOK_PRICES"
                return

            mid = (best_bid + best_ask) / 2.0
            if mid <= 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_MID_PRICE"
                return

            for k in range(levels):
                b_px, b_qty = bids[k]
                a_px, a_qty = asks[k]

                if (
                    not self._is_valid_num(b_px)
                    or not self._is_valid_num(b_qty)
                    or not self._is_valid_num(a_px)
                    or not self._is_valid_num(a_qty)
                    or b_qty < 0.0
                    or a_qty < 0.0
                    or a_px < b_px
                ):
                    now_mono = time.monotonic()
                    self._blocked_until = now_mono + self.cooldown_seconds
                    self._last_block_reason = "CORRUPTED_LEVEL_DATA"
                    return

                spr_k = a_px - b_px
                w_k = b_qty + a_qty
                num_weighted_spread += spr_k * w_k
                total_weight += w_k

            depth_spread = num_weighted_spread / max(total_weight, 0.10)
            depth_spread_bps = (depth_spread / mid) * 10000.0

            self._latest_spread_bps = depth_spread_bps
            self._spread_history.append(depth_spread_bps)
            self._sample_count += 1

            mean_spr = statistics.mean(self._spread_history) if self._spread_history else depth_spread_bps

            self._check_and_trigger_block(
                mean_spr,
                depth_spread_bps,
                self._sample_count,
            )

    def record_depth_spread_metrics(
        self,
        spread_bps: float,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed depth-weighted spread metrics.
        """
        with self._lock:
            if not self._is_valid_num(spread_bps) or spread_bps < 0.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_SPREAD_METRIC"
                return

            spr = float(spread_bps)
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_samples

            self._latest_spread_bps = spr
            self._sample_count = cnt
            self._spread_history.append(spr)

            mean_spr = statistics.mean(self._spread_history) if self._spread_history else spr

            self._check_and_trigger_block(
                mean_spr,
                spr,
                cnt,
            )

    def update(self, spread_bps: float, ts: Optional[float] = None) -> None:
        """Alias for record_depth_spread_metrics."""
        self.record_depth_spread_metrics(spread_bps, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_depth_spread_metrics(self) -> Dict[str, Any]:
        with self._lock:
            if self._spread_history:
                mean_spr = statistics.mean(self._spread_history)
                max_spr = max(self._spread_history)
            else:
                mean_spr = self._latest_spread_bps
                max_spr = self._latest_spread_bps

            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "mean_depth_weighted_spread_bps": float(mean_spr),
                "max_depth_weighted_spread_bps": float(max_spr),
                "latest_depth_weighted_spread_bps": float(self._latest_spread_bps),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_depth_spread_metrics()

    def reset(self) -> None:
        with self._lock:
            self._spread_history.clear()
            self._latest_spread_bps = 0.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
