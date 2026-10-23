"""Wave 324: Limit Order Book Micro-Price Information Flow Lead-Lag Asynchrony & Latency Arbitrage Guard.

Mathematical and Microstructural Context:
----------------------------------------
In high-frequency electronic markets, the simple mid-price P_mid = (a_t + b_t) / 2
lags the true short-term fundamental value of the order book because it neglects queue sizes.
The volume-weighted micro-price (Stoikov 2018; Gatheral & Oomen 2010):
    P_micro = (Q_b * a_t + Q_a * b_t) / (Q_b + Q_a)
            = b_t + (Q_b / (Q_b + Q_a)) * (a_t - b_t)
            = P_mid + (S_t / 2) * ((Q_b - Q_a) / (Q_b + Q_a))

The micro-price displacement from mid-price reflects queue-imbalance-driven predictive pressure:
    Delta_micro = P_micro - P_mid = (S_t / 2) * Imbalance_t

Under normal market-making equilibrium:
1. P_micro fluctuates smoothly within the inside spread [b_t, a_t].
2. Normalized displacement |Delta_micro| / S_t <= 0.35.

However, during toxic order book states or latency arbitrage attacks:
1. Asynchronous Boundary Crossings (P_micro > a_t or P_micro < b_t):
   Signals feed desynchronization, phantom queue updates, or stale depth quotes
   that fail to update alongside top-of-book price shifts.
2. Predictive Imbalance Displacement Surge (|Delta_micro| / S_t >= 0.42 over N >= 10 ticks):
   Signals persistent toxic queue crowding on one side, forecasting an impending
   quote jump that leaves passive limit orders vulnerable to adverse selection.
3. Acute Lead Shock (|Delta_micro,t - Delta_micro,t-1| / P_mid >= 3.0 bps in dt <= 0.10s):
   Signals a lightning-fast queue replacement or quote fade engineered by predatory HFTs.

When any of these anomalies occur, the guard trips an execution block for
`cooldown_seconds` (default: 45.0s) to protect against front-running and adverse selection.

Thread Safety: Protected by threading.RLock.
Fail-Closed: Any non-numeric, NaN, infinite, or non-positive queue/price inputs trip an immediate block.
"""

from collections import deque
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


class Wave324LOBMicroPriceLeadLagAsynchronyGuard:
    """Wave 324: LOB Micro-Price Information Flow Lead-Lag Asynchrony Guard."""

    def __init__(
        self,
        window_size: int = 12,
        max_displacement_ratio: float = 0.42,
        acute_displacement_bps: float = 3.0,
        acute_time_window_s: float = 0.10,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if isinstance(window_size, bool) or not isinstance(window_size, int) or window_size < 3:
            window_size = 12
        if isinstance(cooldown_seconds, bool) or not isinstance(cooldown_seconds, (int, float)) or cooldown_seconds <= 0:
            cooldown_seconds = 45.0

        self.window_size = window_size
        self.max_displacement_ratio = float(max_displacement_ratio)
        self.acute_displacement_bps = float(acute_displacement_bps)
        self.acute_time_window_s = float(acute_time_window_s)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._displacement_ratios: deque = deque(maxlen=self.window_size)
        self._last_delta_micro: float = 0.0
        self._last_update_time: Optional[float] = None
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""
        self._last_micro_price: float = 0.0
        self._last_displacement_ratio: float = 0.0
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
        bid_depth: float,
        ask_depth: float,
        current_time: Optional[float] = None,
    ) -> bool:
        """Process an inside book snapshot and evaluate micro-price lead-lag asynchrony.

        Returns True if trading is blocked, False otherwise.
        """
        now = time.monotonic() if current_time is None else float(current_time)

        with self._lock:
            self._total_updates += 1

            v_bid = self._validate_numeric(bid_price)
            v_ask = self._validate_numeric(ask_price)
            v_qbid = self._validate_numeric(bid_depth)
            v_qask = self._validate_numeric(ask_depth)

            if v_bid is None or v_ask is None or v_qbid is None or v_qask is None:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = "FAIL_CLOSED: Non-numeric, NaN, or infinite price/depth input"
                self._total_violations += 1
                return True

            spread = v_ask - v_bid
            if spread <= 0.0 or v_qbid <= 0.0 or v_qask <= 0.0:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = (
                    f"FAIL_CLOSED: Invalid book state: spread={spread:.6f}, Q_bid={v_qbid}, Q_ask={v_qask}"
                )
                self._total_violations += 1
                return True

            mid_price = (v_bid + v_ask) / 2.0
            total_depth = v_qbid + v_qask
            micro_price = (v_qbid * v_ask + v_qask * v_bid) / total_depth
            self._last_micro_price = micro_price

            # 1. Boundary crossing anomaly: micro-price out of [bid, ask]
            if micro_price < v_bid - 1e-7 or micro_price > v_ask + 1e-7:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = (
                    f"MICRO_PRICE_BOUNDARY_CROSSING: Micro-price {micro_price:.6f} "
                    f"outside [{v_bid:.6f}, {v_ask:.6f}]"
                )
                self._total_violations += 1
                return True

            delta_micro = micro_price - mid_price
            disp_ratio = abs(delta_micro) / spread
            self._last_displacement_ratio = disp_ratio

            # 2. Acute micro-price lead shock
            if self._last_update_time is not None:
                dt = now - self._last_update_time
                if 0.0 <= dt <= self.acute_time_window_s:
                    delta_shift = abs(delta_micro - self._last_delta_micro)
                    delta_shift_bps = (delta_shift / mid_price) * 10000.0
                    if delta_shift_bps >= self.acute_displacement_bps:
                        self._blocked_until = now + self.cooldown_seconds
                        self._last_block_reason = (
                            f"ACUTE_MICRO_PRICE_LEAD_SHOCK: Displacement shift {delta_shift_bps:.2f} bps "
                            f">= threshold {self.acute_displacement_bps:.2f} bps in {dt:.3f}s"
                        )
                        self._total_violations += 1
                        self._last_delta_micro = delta_micro
                        self._last_update_time = now
                        return True

            self._last_delta_micro = delta_micro
            self._last_update_time = now

            self._displacement_ratios.append(disp_ratio)

            # 3. Rolling predictive displacement surge
            if len(self._displacement_ratios) >= self.window_size:
                mean_ratio = sum(self._displacement_ratios) / len(self._displacement_ratios)
                if mean_ratio >= self.max_displacement_ratio:
                    self._blocked_until = now + self.cooldown_seconds
                    self._last_block_reason = (
                        f"PREDICTIVE_DISPLACEMENT_SURGE: Mean displacement ratio {mean_ratio:.3f} "
                        f">= threshold {self.max_displacement_ratio:.3f} over {len(self._displacement_ratios)} ticks"
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
        """Reset internal buffers and block states."""
        with self._lock:
            self._displacement_ratios.clear()
            self._last_delta_micro = 0.0
            self._last_update_time = None
            self._blocked_until = 0.0
            self._last_block_reason = ""
            self._last_micro_price = 0.0
            self._last_displacement_ratio = 0.0
            self._total_updates = 0
            self._total_violations = 0

    def get_status(self, current_time: Optional[float] = None) -> Dict[str, Any]:
        """Return diagnostic metrics and state dictionary."""
        now = time.monotonic() if current_time is None else float(current_time)
        with self._lock:
            remaining_cooldown = max(0.0, self._blocked_until - now)
            ratios = list(self._displacement_ratios)
            mean_ratio = (sum(ratios) / len(ratios)) if ratios else 0.0

            return {
                "guard_name": "Wave324LOBMicroPriceLeadLagAsynchronyGuard",
                "is_blocked": now < self._blocked_until,
                "remaining_cooldown_s": round(remaining_cooldown, 3),
                "last_block_reason": self._last_block_reason,
                "last_micro_price": round(self._last_micro_price, 6),
                "last_displacement_ratio": round(self._last_displacement_ratio, 4),
                "rolling_mean_displacement_ratio": round(mean_ratio, 4),
                "buffer_fill": len(self._displacement_ratios),
                "total_updates": self._total_updates,
                "total_violations": self._total_violations,
            }
