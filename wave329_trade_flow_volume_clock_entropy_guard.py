"""Wave 329: High-Frequency Trade Flow Volume-Clock Information Entropy & Algorithmic Concentration Guard.

Mathematical and Microstructural Context:
----------------------------------------
Under informationally efficient market regimes, order flow sampled across volume tiers
exhibits high Shannon information entropy, reflecting heterogeneous order origins
(Easley, López de Prado & O'Hara 2011; Shannon 1948; Dacorogna et al. 2001).

Classifying trade volumes V into K=4 discrete size regimes:
    Tier 0 (Micro):     V < 0.5 lots
    Tier 1 (Standard):  0.5 <= V < 2.0 lots
    Tier 2 (Large):     2.0 <= V < 5.0 lots
    Tier 3 (Whale):     V >= 5.0 lots

For empirical probabilities p_k = n_k / N over a rolling buffer of N trades,
the normalized Shannon entropy is:
    H_vol = - (1 / ln(K)) * sum_{k=0}^{K-1} p_k * ln(p_k)   in [0, 1]

However, during predatory algorithmic slicing or toxic institutional sweeps:
1. Entropy Collapse / Monolithic Flow (H_vol <= 0.25 over N >= 16 trades):
   Overwhelming volume concentration into a single regime (e.g. rigid algorithmic TWAP/Iceberg slicing).
2. Acute Whale Concentration Shock (p_whale >= 0.50 with mean(V) >= 6.0 lots over N >= 10 trades):
   Predatory large-trader dominance absorbing lit liquidity and foretelling violent repricing.
3. Robotic Equal-Volume Sweep Streak (N_streak >= 8 consecutive trades with |V_t - V_{t-1}| <= 1e-3 lots):
   Deterministic machine slicing loops executing fixed-size orders with zero human variance.

When any of these anomalies occur, the guard trips an execution block for
`cooldown_seconds` (default: 45.0s).

Thread Safety: Protected by threading.RLock.
Fail-Closed: Any non-numeric, NaN, infinite, or non-positive trade volume trips an immediate block.
"""

from collections import deque
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


class Wave329TradeFlowVolumeClockEntropyGuard:
    """Wave 329: Trade Flow Volume-Clock Information Entropy Guard."""

    def __init__(
        self,
        window_size: int = 20,
        entropy_collapse_threshold: float = 0.25,
        whale_prob_threshold: float = 0.50,
        whale_min_mean_volume: float = 6.0,
        robotic_streak_threshold: int = 8,
        robotic_volume_tolerance: float = 0.001,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if isinstance(window_size, bool) or not isinstance(window_size, int) or window_size < 5:
            window_size = 20
        if isinstance(cooldown_seconds, bool) or not isinstance(cooldown_seconds, (int, float)) or cooldown_seconds <= 0:
            cooldown_seconds = 45.0

        self.window_size = window_size
        self.entropy_collapse_threshold = float(entropy_collapse_threshold)
        self.whale_prob_threshold = float(whale_prob_threshold)
        self.whale_min_mean_volume = float(whale_min_mean_volume)
        self.robotic_streak_threshold = int(robotic_streak_threshold)
        self.robotic_volume_tolerance = float(robotic_volume_tolerance)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._trade_volumes: deque = deque(maxlen=self.window_size)
        self._last_volume: float = 0.0
        self._robotic_streak: int = 0
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""
        self._last_normalized_entropy: float = 1.0
        self._total_trades: int = 0
        self._total_violations: int = 0

    def _validate_numeric(self, val: Any) -> Optional[float]:
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return None
        fval = float(val)
        if math.isnan(fval) or math.isinf(fval):
            return None
        return fval

    def _classify_tier(self, vol: float) -> int:
        if vol < 0.5:
            return 0  # Micro
        elif vol < 2.0:
            return 1  # Standard
        elif vol < 5.0:
            return 2  # Large
        else:
            return 3  # Whale

    def _calculate_normalized_entropy(self, volumes: List[float]) -> Tuple[float, float, float]:
        """Compute normalized Shannon entropy, whale probability, and mean volume."""
        n = len(volumes)
        if n == 0:
            return 1.0, 0.0, 0.0

        counts = [0, 0, 0, 0]
        for v in volumes:
            counts[self._classify_tier(v)] += 1

        p_whale = counts[3] / n
        mean_v = sum(volumes) / n

        h = 0.0
        k = 4
        for c in counts:
            if c > 0:
                p = c / n
                h -= p * math.log(p)

        norm_h = h / math.log(k)
        return norm_h, p_whale, mean_v

    def update(
        self,
        trade_volume: float,
        current_time: Optional[float] = None,
    ) -> bool:
        """Process a trade volume and evaluate entropy & robotic slicing dynamics.

        Returns True if trading is blocked, False otherwise.
        """
        now = time.monotonic() if current_time is None else float(current_time)

        with self._lock:
            self._total_trades += 1

            v_vol = self._validate_numeric(trade_volume)

            if v_vol is None or v_vol <= 0.0:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = f"FAIL_CLOSED: Non-numeric, NaN, or non-positive volume: {trade_volume}"
                self._total_violations += 1
                return True

            # 1. Robotic Equal-Volume Sweep Streak
            if self._last_volume > 0.0 and abs(v_vol - self._last_volume) <= self.robotic_volume_tolerance:
                self._robotic_streak += 1
            else:
                self._robotic_streak = 1
            self._last_volume = v_vol

            if self._robotic_streak >= self.robotic_streak_threshold:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = (
                    f"ROBOTIC_EQUAL_VOLUME_STREAK: {self._robotic_streak} consecutive trades "
                    f"with identical volume {v_vol:.3f} lots"
                )
                self._total_violations += 1
                return True

            self._trade_volumes.append(v_vol)

            # Rolling entropy analysis
            if len(self._trade_volumes) >= 10:
                vols = list(self._trade_volumes)
                norm_h, p_whale, mean_v = self._calculate_normalized_entropy(vols)
                self._last_normalized_entropy = norm_h

                # 2. Acute Whale Concentration Shock
                if p_whale >= self.whale_prob_threshold and mean_v >= self.whale_min_mean_volume:
                    self._blocked_until = now + self.cooldown_seconds
                    self._last_block_reason = (
                        f"ACUTE_WHALE_CONCENTRATION_SHOCK: Whale fraction {p_whale:.2f} >= "
                        f"{self.whale_prob_threshold:.2f} with mean volume {mean_v:.2f} >= {self.whale_min_mean_volume:.2f}"
                    )
                    self._total_violations += 1
                    return True

                # 3. Entropy Collapse / Monolithic Flow (requires deeper buffer >= 16)
                if len(vols) >= 16 and norm_h <= self.entropy_collapse_threshold:
                    self._blocked_until = now + self.cooldown_seconds
                    self._last_block_reason = (
                        f"VOLUME_ENTROPY_COLLAPSE: Normalized entropy {norm_h:.3f} <= "
                        f"threshold {self.entropy_collapse_threshold:.2f} over {len(vols)} trades"
                    )
                    self._total_violations += 1
                    return True

            return now < self._blocked_until

    def is_blocked(self, current_time: Optional[float] = None) -> bool:
        """Return True if the guard is currently blocking entries."""
        now = time.monotonic() if current_time is None else float(current_time)
        with self._lock:
            return now < self._blocked_until

    def is_entry_blocked(self, current_time: Optional[float] = None) -> bool:
        """Alias for is_blocked."""
        return self.is_blocked(current_time)

    def reset(self) -> None:
        """Reset internal buffers and state."""
        with self._lock:
            self._trade_volumes.clear()
            self._last_volume = 0.0
            self._robotic_streak = 0
            self._blocked_until = 0.0
            self._last_block_reason = ""
            self._last_normalized_entropy = 1.0
            self._total_trades = 0
            self._total_violations = 0

    def get_status(self, current_time: Optional[float] = None) -> Dict[str, Any]:
        """Return diagnostic metrics and state dictionary."""
        now = time.monotonic() if current_time is None else float(current_time)
        with self._lock:
            remaining_cooldown = max(0.0, self._blocked_until - now)
            vols = list(self._trade_volumes)
            norm_h, p_whale, mean_v = self._calculate_normalized_entropy(vols)

            return {
                "guard_name": "Wave329TradeFlowVolumeClockEntropyGuard",
                "is_blocked": now < self._blocked_until,
                "remaining_cooldown_s": round(remaining_cooldown, 3),
                "last_block_reason": self._last_block_reason,
                "normalized_entropy": round(norm_h, 4),
                "whale_fraction": round(p_whale, 4),
                "mean_volume": round(mean_v, 3),
                "robotic_streak": self._robotic_streak,
                "buffer_fill": len(self._trade_volumes),
                "total_trades": self._total_trades,
                "total_violations": self._total_violations,
            }
