"""
wave296_lob_queue_imbalance_dispersion_entropy_guard.py
-------------------------------------------------------
Guard: LOB Multi-Level Imbalance Dispersion Shannon Entropy Guard

Monitors multi-level limit order book depth distribution, Shannon information entropy, and tier concentration
(Shannon 1948; Biais, Hillion & Spatt 1995; Gould et al. 2013; Cont, Kukanov & Stoikov 2014):
    Multi-Tier Levels:           k = 1, 2, ..., L  (default: L = 3 tiers)
    Tier Combined Depth:         W_k = Q_{bid,k} + Q_{ask,k} in lots
    Total Multi-Level Depth:     W_{total} = sum_{k=1}^L W_k
    Tier Depth Share:            p_k = W_k / max(W_{total}, 0.10)
    Normalized Shannon Entropy:  H_{norm} = - sum_{k=1}^L p_k * ln(p_k) / ln(L) in [0.0, 1.0]
    Max Tier Concentration:      p_{max} = max_{k}(p_k)

Under resilient, well-provisioned liquidity conditions:
    - Order book depth is evenly distributed across multiple price tiers:
      H_{norm} in [0.70, 1.00], with max tier share p_{max} <= 0.55.
    - Outer book tiers provide a balanced shock-absorbing buffer.

During predatory quote stacking, spoofing sweeps, or liquidity concentration traps:
    - Depth collapses into a single price level while adjacent levels sit completely hollow:
        1) Multi-Level Imbalance Dispersion Entropy Collapse:
           Rolling mean normalized entropy \\bar{H}_{norm} <= MIN_NORMALIZED_ENTROPY (default: 0.35)
           with total depth W_{total} >= MIN_TOTAL_DEPTH (default: 10.0 lots)
           over rolling N >= MIN_SAMPLES (default: 8 snapshots).
        2) Acute Single-Tier Concentration:
           Max tier depth share p_{max} >= ACUTE_CONCENTRATION (default: 0.85)
           with total depth W_{total} >= ACUTE_TOTAL_DEPTH (default: 12.0 lots).

Trading in an entropy-collapsed book exposes executions to catastrophic tier slippage
as soon as the single stacked depth level is wiped out.

When entropy collapse or acute tier concentration is detected, entry orders are blocked for
COOLDOWN_SECONDS (default: 45.0s).

Logic:
- Ingests book snapshot via record_book_depth(bids, asks, ts=None) or
  direct metrics via record_entropy_metrics(entropy_norm, max_share=None, total_depth=None, sample_count=None, ts=None).
- Maintains rolling history of WINDOW_SIZE = 15 snapshots.
- Cooldown timer: _blocked_until = time.monotonic() + COOLDOWN_SECONDS.
- Thread-safe: threading.RLock() on all state transitions.
- Fail-closed: non-numeric, boolean, NaN, Inf, or invalid depths are rejected.

Aliases (required):
  is_entry_blocked()                                                                           -> bool
  is_blocked()                                                                                 -> bool   (alias)
  record_book_depth(bids, asks, ts=None)                                                       -> None
  record_entropy_metrics(entropy_norm, max_share=None, total_depth=None, sample_count=None)     -> None
  update(entropy_norm, ts=None)                                                                -> None   (alias)
  get_dispersion_entropy_metrics()                                                             -> dict
  get_status()                                                                                 -> dict
  reset()                                                                                      -> None
"""

import collections
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


class Wave296LobQueueImbalanceDispersionEntropyGuard:
    """
    Guards against LOB multi-tier depth concentration, Shannon entropy collapse, and hollow book traps.
    """

    MIN_NORMALIZED_ENTROPY: float = 0.35
    MIN_TOTAL_DEPTH: float = 10.0
    MIN_SAMPLES: int = 8
    ACUTE_CONCENTRATION: float = 0.85
    ACUTE_TOTAL_DEPTH: float = 12.0
    WINDOW_SIZE: int = 15
    COOLDOWN_SECONDS: float = 45.0

    def __init__(
        self,
        min_normalized_entropy: float = MIN_NORMALIZED_ENTROPY,
        min_total_depth: float = MIN_TOTAL_DEPTH,
        min_samples: int = MIN_SAMPLES,
        acute_concentration: float = ACUTE_CONCENTRATION,
        acute_total_depth: float = ACUTE_TOTAL_DEPTH,
        window_size: int = WINDOW_SIZE,
        cooldown_seconds: float = COOLDOWN_SECONDS,
    ):
        self.min_normalized_entropy = float(min_normalized_entropy)
        self.min_total_depth = float(min_total_depth)
        self.min_samples = int(min_samples)
        self.acute_concentration = float(acute_concentration)
        self.acute_total_depth = float(acute_total_depth)
        self.window_size = int(window_size)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._entropy_history = collections.deque(maxlen=self.window_size)
        self._depth_history = collections.deque(maxlen=self.window_size)

        self._latest_entropy: float = 1.0
        self._latest_max_share: float = 0.33
        self._latest_total_depth: float = 0.0
        self._sample_count: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""

    def _is_valid_num(self, val: Any) -> bool:
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            return False
        return not (math.isnan(val) or math.isinf(val))

    def _calculate_entropy(self, weights: List[float]) -> Tuple[float, float]:
        total_w = sum(weights)
        if total_w <= 1e-4 or len(weights) < 2:
            return 1.0, 1.0

        k = len(weights)
        probs = [w / total_w for w in weights]
        max_p = max(probs)

        h = 0.0
        for p in probs:
            if p > 1e-6:
                h -= p * math.log(p)

        max_h = math.log(k)
        h_norm = h / max_h if max_h > 1e-6 else 1.0
        return min(max(h_norm, 0.0), 1.0), max_p

    def _check_and_trigger_block(
        self,
        mean_entropy: float,
        max_share: float,
        total_depth: float,
        sample_count: int,
    ) -> bool:
        # 1. Acute single-tier concentration
        if max_share >= self.acute_concentration and total_depth >= self.acute_total_depth:
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"ACUTE_TIER_CONCENTRATION: max_share={max_share:.2f} >= {self.acute_concentration:.2f}, "
                f"total_depth={total_depth:.2f} >= {self.acute_total_depth:.2f} lots"
            )
            return True

        # 2. Multi-level imbalance dispersion entropy collapse
        if (
            sample_count >= self.min_samples
            and mean_entropy <= self.min_normalized_entropy
            and total_depth >= self.min_total_depth
        ):
            now_mono = time.monotonic()
            self._blocked_until = now_mono + self.cooldown_seconds
            self._last_block_reason = (
                f"DISPERSION_ENTROPY_COLLAPSE: mean_entropy={mean_entropy:.2f} <= {self.min_normalized_entropy:.2f}, "
                f"depth={total_depth:.2f} >= {self.min_total_depth:.2f} lots (N={sample_count})"
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
            weights = []

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
                ):
                    now_mono = time.monotonic()
                    self._blocked_until = now_mono + self.cooldown_seconds
                    self._last_block_reason = "CORRUPTED_LEVEL_DATA"
                    return

                w_k = float(b_qty) + float(a_qty)
                weights.append(w_k)

            total_depth = sum(weights)
            entropy_norm, max_share = self._calculate_entropy(weights)

            self._latest_entropy = entropy_norm
            self._latest_max_share = max_share
            self._latest_total_depth = total_depth
            self._entropy_history.append(entropy_norm)
            self._depth_history.append(total_depth)
            self._sample_count += 1

            mean_ent = statistics.mean(self._entropy_history) if self._entropy_history else entropy_norm
            mean_dep = statistics.mean(self._depth_history) if self._depth_history else total_depth

            self._check_and_trigger_block(
                mean_ent,
                max_share,
                mean_dep,
                self._sample_count,
            )

    def record_entropy_metrics(
        self,
        entropy_norm: float,
        max_share: Optional[float] = None,
        total_depth: Optional[float] = None,
        sample_count: Optional[int] = None,
        ts: Optional[float] = None,
    ) -> None:
        """
        Directly record precomputed entropy dispersion metrics.
        """
        with self._lock:
            if not self._is_valid_num(entropy_norm) or entropy_norm < 0.0 or entropy_norm > 1.0:
                now_mono = time.monotonic()
                self._blocked_until = now_mono + self.cooldown_seconds
                self._last_block_reason = "CORRUPTED_ENTROPY_METRIC"
                return

            ent = float(entropy_norm)
            ms = float(max_share) if (self._is_valid_num(max_share) and 0.0 <= max_share <= 1.0) else 0.50
            td = float(total_depth) if (self._is_valid_num(total_depth) and total_depth >= 0.0) else self.min_total_depth + 2.0
            cnt = int(sample_count) if (self._is_valid_num(sample_count) and sample_count >= 0) else self.min_samples

            self._latest_entropy = ent
            self._latest_max_share = ms
            self._latest_total_depth = td
            self._sample_count = cnt
            self._entropy_history.append(ent)
            self._depth_history.append(td)

            mean_ent = statistics.mean(self._entropy_history) if self._entropy_history else ent
            mean_dep = statistics.mean(self._depth_history) if self._depth_history else td

            self._check_and_trigger_block(
                mean_ent,
                ms,
                mean_dep,
                cnt,
            )

    def update(self, entropy_norm: float, ts: Optional[float] = None) -> None:
        """Alias for record_entropy_metrics."""
        self.record_entropy_metrics(entropy_norm, ts=ts)

    def is_entry_blocked(self) -> bool:
        with self._lock:
            now_mono = time.monotonic()
            return now_mono < self._blocked_until

    def is_blocked(self) -> bool:
        """Alias for is_entry_blocked."""
        return self.is_entry_blocked()

    def get_dispersion_entropy_metrics(self) -> Dict[str, Any]:
        with self._lock:
            if self._entropy_history:
                mean_ent = statistics.mean(self._entropy_history)
            else:
                mean_ent = self._latest_entropy

            now_mono = time.monotonic()
            remaining_cooldown = max(0.0, self._blocked_until - now_mono)

            return {
                "normalized_entropy": float(mean_ent),
                "latest_entropy": float(self._latest_entropy),
                "max_tier_share": float(self._latest_max_share),
                "total_depth_lots": float(self._latest_total_depth),
                "sample_count": int(self._sample_count),
                "is_blocked": now_mono < self._blocked_until,
                "remaining_cooldown_sec": float(remaining_cooldown),
                "last_block_reason": str(self._last_block_reason),
            }

    def get_status(self) -> Dict[str, Any]:
        return self.get_dispersion_entropy_metrics()

    def reset(self) -> None:
        with self._lock:
            self._entropy_history.clear()
            self._depth_history.clear()
            self._latest_entropy = 1.0
            self._latest_max_share = 0.33
            self._latest_total_depth = 0.0
            self._sample_count = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
