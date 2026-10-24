"""Wave 331: High-Frequency Trade Size Heavy-Tail Extreme Value Theory (EVT) Hill Estimator Guard.

Mathematical and Microstructural Context:
----------------------------------------
In high-frequency markets, the distribution of executed trade sizes exhibits heavy power-law
tails P(V > x) ~ x^(-alpha), where alpha is the Pareto tail index (Hill 1975; Embrechts, Klüppelberg
& Mikosch 1997; Gabaix 2009).
When alpha <= 2.0, the variance of trade sizes diverges; when alpha <= 1.0, the mean itself diverges.

For descending sorted order sizes V_{(1)} >= V_{(2)} >= ... >= V_{(n)} with tail cutoff k:
    Hill Estimator: H_k = (1 / k) * sum_{i=1}^k ln(V_{(i)} / V_{(k+1)})
    Tail Exponent:  alpha_hat = 1 / H_k

Under standard retail scalping market conditions:
1. Trade sizes are moderately distributed with alpha_hat in [1.5, 3.0], reflecting finite variance.

However, during predatory institutional block trades or panic liquidation sweeps:
1. Infinite-Variance Heavy Tail Regime (alpha_hat <= 1.10 over N >= 16 trades):
   The volume distribution collapses into an extreme Pareto regime dominated by catastrophic outliers.
2. Acute Extreme Tail Outlier (V_t >= 20.0 lots with V_t >= 15.0 * median(V)):
   A massive rogue trade execution overwhelming order book depth.
3. Top-3 Volume Tail Concentration (sum(V_{(1..3)}) / sum(V) >= 0.65 over N >= 10 trades):
   A few massive prints command the vast majority of executed volume.

When any of these anomalies occur, the guard trips an execution block for
`cooldown_seconds` (default: 45.0s).

Thread Safety: Protected by threading.RLock.
Fail-Closed: Any non-numeric, NaN, infinite, or non-positive volume trips an immediate block.
"""

from collections import deque
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


class Wave331TradeArrivalTailRiskHillGuard:
    """Wave 331: Trade Size Heavy-Tail EVT Hill Estimator Guard."""

    def __init__(
        self,
        window_size: int = 20,
        hill_tail_threshold: float = 1.10,
        acute_outlier_volume: float = 20.0,
        acute_outlier_median_mult: float = 15.0,
        top3_concentration_threshold: float = 0.65,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if isinstance(window_size, bool) or not isinstance(window_size, int) or window_size < 8:
            window_size = 20
        if isinstance(cooldown_seconds, bool) or not isinstance(cooldown_seconds, (int, float)) or cooldown_seconds <= 0:
            cooldown_seconds = 45.0

        self.window_size = window_size
        self.hill_tail_threshold = float(hill_tail_threshold)
        self.acute_outlier_volume = float(acute_outlier_volume)
        self.acute_outlier_median_mult = float(acute_outlier_median_mult)
        self.top3_concentration_threshold = float(top3_concentration_threshold)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._trade_volumes: deque = deque(maxlen=self.window_size)
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""
        self._last_hill_alpha: float = 2.50
        self._total_trades: int = 0
        self._total_violations: int = 0

    def _validate_numeric(self, val: Any) -> Optional[float]:
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return None
        fval = float(val)
        if math.isnan(fval) or math.isinf(fval):
            return None
        return fval

    def _calculate_hill_alpha(self, sorted_desc: List[float], k: int) -> float:
        """Compute the Hill tail index alpha = 1 / H_k."""
        if k < 1 or k >= len(sorted_desc):
            return 2.50

        v_k1 = sorted_desc[k]
        if v_k1 <= 1e-9:
            return 2.50

        h_sum = 0.0
        for i in range(k):
            val = sorted_desc[i]
            if val > v_k1:
                h_sum += math.log(val / v_k1)

        h_k = h_sum / k
        if h_k <= 1e-6:
            return 10.0  # Zero tail dispersion

        alpha = 1.0 / h_k
        return max(0.01, min(10.0, alpha))

    def update(
        self,
        trade_volume: float,
        current_time: Optional[float] = None,
    ) -> bool:
        """Process a trade print and evaluate heavy-tail EVT risk.

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

            # Check acute outlier against existing buffer
            if len(self._trade_volumes) >= 8:
                sorted_existing = sorted(list(self._trade_volumes))
                med = sorted_existing[len(sorted_existing) // 2]
                if v_vol >= self.acute_outlier_volume and (v_vol / max(1e-4, med)) >= self.acute_outlier_median_mult:
                    self._blocked_until = now + self.cooldown_seconds
                    self._last_block_reason = (
                        f"ACUTE_EXTREME_TAIL_OUTLIER: Volume {v_vol:.2f} lots >= {self.acute_outlier_volume:.2f} "
                        f"and {v_vol / med:.1f}x median {med:.2f}"
                    )
                    self._total_violations += 1
                    self._trade_volumes.append(v_vol)
                    return True

            self._trade_volumes.append(v_vol)

            if len(self._trade_volumes) >= 10:
                vols = list(self._trade_volumes)
                vols_desc = sorted(vols, reverse=True)
                total_vol = sum(vols_desc)

                # 1. Top-3 Tail Jump Concentration
                if total_vol > 0.0 and len(vols_desc) >= 3:
                    top3_vol = sum(vols_desc[:3])
                    top3_ratio = top3_vol / total_vol
                    if top3_ratio >= self.top3_concentration_threshold:
                        self._blocked_until = now + self.cooldown_seconds
                        self._last_block_reason = (
                            f"TAIL_VOLUME_CONCENTRATION: Top-3 trades account for {top3_ratio:.2%} "
                            f">= {self.top3_concentration_threshold:.2%} of total volume ({total_vol:.2f} lots)"
                        )
                        self._total_violations += 1
                        return True

                # 2. Hill Estimator Tail Index (requires deeper buffer >= 16)
                if len(vols_desc) >= 16:
                    k = max(4, int(0.25 * len(vols_desc)))
                    alpha = self._calculate_hill_alpha(vols_desc, k)
                    self._last_hill_alpha = alpha

                    if alpha <= self.hill_tail_threshold:
                        self._blocked_until = now + self.cooldown_seconds
                        self._last_block_reason = (
                            f"INFINITE_VARIANCE_TAIL_REGIME: Hill tail alpha {alpha:.3f} <= "
                            f"{self.hill_tail_threshold:.2f} (cutoff k={k}, N={len(vols_desc)})"
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
        """Reset internal state and buffers."""
        with self._lock:
            self._trade_volumes.clear()
            self._blocked_until = 0.0
            self._last_block_reason = ""
            self._last_hill_alpha = 2.50
            self._total_trades = 0
            self._total_violations = 0

    def get_status(self, current_time: Optional[float] = None) -> Dict[str, Any]:
        """Return diagnostic metrics and state dictionary."""
        now = time.monotonic() if current_time is None else float(current_time)
        with self._lock:
            remaining_cooldown = max(0.0, self._blocked_until - now)
            vols = list(self._trade_volumes)
            vols_desc = sorted(vols, reverse=True)
            k = max(4, int(0.25 * len(vols_desc))) if len(vols_desc) >= 8 else 4
            alpha = self._calculate_hill_alpha(vols_desc, k) if len(vols_desc) >= 8 else 2.50

            return {
                "guard_name": "Wave331TradeArrivalTailRiskHillGuard",
                "is_blocked": now < self._blocked_until,
                "remaining_cooldown_s": round(remaining_cooldown, 3),
                "last_block_reason": self._last_block_reason,
                "hill_tail_alpha": round(alpha, 4),
                "buffer_fill": len(self._trade_volumes),
                "total_trades": self._total_trades,
                "total_violations": self._total_violations,
            }
