"""Wave 328: Limit Order Book Multi-Level Cumulative Depth Convexity & Curvature Collapse Guard.

Mathematical and Microstructural Context:
----------------------------------------
In resilient, well-provisioned electronic central limit order books, cumulative depth D(k)
increases convexly as price moves away from the best quote (Bouchaud, Farmer & Lillo 2009;
Roşu 2009; Gould et al. 2013).
For a 3-tier book with bid depths (Q_{b,1}, Q_{b,2}, Q_{b,3}) and ask depths (Q_{a,1}, Q_{a,2}, Q_{a,3}):
    Cumulative depth: D(1) = Q_1, D(2) = Q_1 + Q_2, D(3) = Q_1 + Q_2 + Q_3
    Depth profile curvature: kappa = (Q_2 - Q_1) + (Q_3 - Q_2) = Q_3 - Q_1

Under normal equilibrium:
1. Deep liquidity replenishment ensures Q_2 >= Q_1 and Q_3 >= Q_2, yielding positive curvature kappa >= 0.

However, during quote fading, predatory sweeps, or depth vacuum traps:
1. Curvature Collapse / Fragile Shell Anomaly (kappa_avg <= -1.50 lots over N >= 8 snapshots):
   The outer book is severely depleted relative to the inside quote (Q_1 >> Q_2, Q_3),
   creating a fragile liquidity facade where any aggressive order punctures through multiple tiers.
2. Acute Depth Evaporation Ratio (D_3 <= 1.25 * Q_1 with spread >= 2.20 bps):
   The subsequent tiers provide almost zero cushion behind the top-of-book quote.
3. Severe Cross-Side Curvature Asymmetry (|kappa_bid - kappa_ask| >= 4.0 lots with spread >= 2.50 bps):
   One side of the book exhibits robust depth thickening while the opposite side collapses,
   forecasting impending asymmetric price breakout.

When any of these anomalies occur, the guard trips an execution block for
`cooldown_seconds` (default: 45.0s) to protect against severe multi-tick slippage.

Thread Safety: Protected by threading.RLock.
Fail-Closed: Any non-numeric, NaN, infinite, or non-positive depth/price inputs trip an immediate block.
"""

from collections import deque
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


class Wave328LOBEffectiveDepthDecayCurvatureGuard:
    """Wave 328: LOB Multi-Level Cumulative Depth Convexity & Curvature Collapse Guard."""

    def __init__(
        self,
        window_size: int = 8,
        curvature_collapse_threshold: float = -1.50,
        acute_evaporation_ratio: float = 1.25,
        acute_spread_bps: float = 2.20,
        asymmetry_curvature_threshold: float = 4.0,
        asymmetry_spread_bps: float = 2.50,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if isinstance(window_size, bool) or not isinstance(window_size, int) or window_size < 3:
            window_size = 8
        if isinstance(cooldown_seconds, bool) or not isinstance(cooldown_seconds, (int, float)) or cooldown_seconds <= 0:
            cooldown_seconds = 45.0

        self.window_size = window_size
        self.curvature_collapse_threshold = float(curvature_collapse_threshold)
        self.acute_evaporation_ratio = float(acute_evaporation_ratio)
        self.acute_spread_bps = float(acute_spread_bps)
        self.asymmetry_curvature_threshold = float(asymmetry_curvature_threshold)
        self.asymmetry_spread_bps = float(asymmetry_spread_bps)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._curvatures: deque = deque(maxlen=self.window_size)
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""
        self._last_mean_curvature: float = 0.0
        self._last_bid_curvature: float = 0.0
        self._last_ask_curvature: float = 0.0
        self._total_updates: int = 0
        self._total_violations: int = 0

    def _validate_numeric(self, val: Any) -> Optional[float]:
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return None
        fval = float(val)
        if math.isnan(fval) or math.isinf(fval):
            return None
        return fval

    def update(
        self,
        bid_price: float,
        ask_price: float,
        bid_depths: List[float],
        ask_depths: List[float],
        current_time: Optional[float] = None,
    ) -> bool:
        """Process a multi-level LOB snapshot and evaluate depth curvature profile.

        bid_depths, ask_depths: list of depths for levels 1, 2, 3 (Q_1, Q_2, Q_3).
        Returns True if trading is blocked, False otherwise.
        """
        now = time.monotonic() if current_time is None else float(current_time)

        with self._lock:
            self._total_updates += 1

            v_bid = self._validate_numeric(bid_price)
            v_ask = self._validate_numeric(ask_price)

            if v_bid is None or v_ask is None:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = "FAIL_CLOSED: Non-numeric, NaN, or infinite price input"
                self._total_violations += 1
                return True

            spread = v_ask - v_bid
            if spread <= 0.0:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = f"FAIL_CLOSED: Crossed or locked book (spread {spread:.6f} <= 0)"
                self._total_violations += 1
                return True

            if not isinstance(bid_depths, (list, tuple)) or not isinstance(ask_depths, (list, tuple)):
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = "FAIL_CLOSED: Depths must be list or tuple"
                self._total_violations += 1
                return True

            if len(bid_depths) < 3 or len(ask_depths) < 3:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = "FAIL_CLOSED: Minimum 3 depth tiers required"
                self._total_violations += 1
                return True

            v_bids = [self._validate_numeric(x) for x in bid_depths[:3]]
            v_asks = [self._validate_numeric(x) for x in ask_depths[:3]]

            if any(x is None or x <= 0.0 for x in v_bids) or any(x is None or x <= 0.0 for x in v_asks):
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = "FAIL_CLOSED: Non-numeric, NaN, or non-positive depth in tiers"
                self._total_violations += 1
                return True

            mid_price = (v_bid + v_ask) / 2.0
            spread_bps = (spread / mid_price) * 10000.0

            # Compute curvatures: kappa = Q_3 - Q_1
            kappa_bid = v_bids[2] - v_bids[0]
            kappa_ask = v_asks[2] - v_asks[0]
            kappa_avg = (kappa_bid + kappa_ask) / 2.0
            self._last_bid_curvature = kappa_bid
            self._last_ask_curvature = kappa_ask
            self._last_mean_curvature = kappa_avg

            # 1. Acute Depth Evaporation Ratio: D_3 <= 1.25 * Q_1 with wide spread
            d3_bid = sum(v_bids)
            d3_ask = sum(v_asks)
            ratio_bid = d3_bid / v_bids[0]
            ratio_ask = d3_ask / v_asks[0]

            if (ratio_bid <= self.acute_evaporation_ratio or ratio_ask <= self.acute_evaporation_ratio) and spread_bps >= self.acute_spread_bps:
                self._blocked_until = now + self.cooldown_seconds
                side = "BID" if ratio_bid <= self.acute_evaporation_ratio else "ASK"
                val = ratio_bid if side == "BID" else ratio_ask
                self._last_block_reason = (
                    f"ACUTE_DEPTH_EVAPORATION: {side} D3/Q1 {val:.2f} <= {self.acute_evaporation_ratio:.2f} "
                    f"with spread {spread_bps:.2f} bps >= {self.acute_spread_bps:.2f}"
                )
                self._total_violations += 1
                return True

            # 2. Severe Cross-Side Curvature Asymmetry
            diff_curvature = abs(kappa_bid - kappa_ask)
            if diff_curvature >= self.asymmetry_curvature_threshold and spread_bps >= self.asymmetry_spread_bps:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = (
                    f"CURVATURE_ASYMMETRY_DISCREPANCY: |kappa_bid - kappa_ask| {diff_curvature:.2f} lots "
                    f">= {self.asymmetry_curvature_threshold:.2f} with spread {spread_bps:.2f} bps"
                )
                self._total_violations += 1
                return True

            self._curvatures.append(kappa_avg)

            # 3. Rolling Curvature Collapse (Fragile Shell Book)
            if len(self._curvatures) >= self.window_size:
                rolling_mean_kappa = sum(self._curvatures) / len(self._curvatures)
                if rolling_mean_kappa <= self.curvature_collapse_threshold:
                    self._blocked_until = now + self.cooldown_seconds
                    self._last_block_reason = (
                        f"ROLLING_CURVATURE_COLLAPSE: Mean curvature {rolling_mean_kappa:.2f} lots "
                        f"<= threshold {self.curvature_collapse_threshold:.2f} lots over {len(self._curvatures)} ticks"
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
            self._curvatures.clear()
            self._blocked_until = 0.0
            self._last_block_reason = ""
            self._last_mean_curvature = 0.0
            self._last_bid_curvature = 0.0
            self._last_ask_curvature = 0.0
            self._total_updates = 0
            self._total_violations = 0

    def get_status(self, current_time: Optional[float] = None) -> Dict[str, Any]:
        """Return diagnostic metrics and state dictionary."""
        now = time.monotonic() if current_time is None else float(current_time)
        with self._lock:
            remaining_cooldown = max(0.0, self._blocked_until - now)
            curvs = list(self._curvatures)
            rolling_k = (sum(curvs) / len(curvs)) if curvs else self._last_mean_curvature

            return {
                "guard_name": "Wave328LOBEffectiveDepthDecayCurvatureGuard",
                "is_blocked": now < self._blocked_until,
                "remaining_cooldown_s": round(remaining_cooldown, 3),
                "last_block_reason": self._last_block_reason,
                "last_bid_curvature": round(self._last_bid_curvature, 3),
                "last_ask_curvature": round(self._last_ask_curvature, 3),
                "rolling_mean_curvature": round(rolling_k, 3),
                "buffer_fill": len(self._curvatures),
                "total_updates": self._total_updates,
                "total_violations": self._total_violations,
            }
