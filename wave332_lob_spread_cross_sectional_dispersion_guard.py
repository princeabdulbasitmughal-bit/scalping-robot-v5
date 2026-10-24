"""Wave 332: Limit Order Book Cross-Venue Spread Dispersion & Fragmentation Latency Arbitrage Guard.

Mathematical and Microstructural Context:
----------------------------------------
In modern fragmented electronic markets, order flow executes across multiple competing venues
and secondary liquidity providers (O'Hara & Ye 2011; Hasbrouck 2003; Menkveld 2013).
For M synchronized venue quotes with spreads S_1, S_2, ..., S_M (in basis points):
    Mean spread:       S_bar = (1 / M) * sum(S_m)
    Spread dispersion: D_S = sqrt((1 / M) * sum((S_m - S_bar)^2))

Under normal competitive fragmentation:
1. Fast inter-market arbitrageurs align venue prices, keeping cross-sectional spread dispersion tight (D_S <= 0.80 bps).

However, during liquidity fragmentation breakdown, latency arbitrage sweeps, or feed desynchronization:
1. Cross-Venue Spread Decoupling (D_S >= 1.80 bps with primary spread S_1 >= 2.20 bps over N >= 10 ticks):
   Indicates severe liquidity withdrawal on secondary venues and impending wide spread contagion.
2. Acute Cross-Venue Quote Crossing / Locked Market:
   The best bid on venue A exceeds the best ask on venue B (b_A >= a_B), signaling a fractured
   cross-market state where latency arbitrageurs are extracting toxic rent.
3. Outlier Venue Drift:
   A single venue spread deviates by >= 4.0 bps from the cross-venue median.

When any of these anomalies occur, the guard trips an execution block for
`cooldown_seconds` (default: 45.0s) to protect against fragmented execution slippage.

Thread Safety: Protected by threading.RLock.
Fail-Closed: Any non-numeric, NaN, infinite, or non-positive price/spread inputs trip an immediate block.
"""

from collections import deque
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


class Wave332LOBSpreadCrossSectionalDispersionGuard:
    """Wave 332: LOB Cross-Venue Spread Dispersion & Fragmentation Guard."""

    def __init__(
        self,
        window_size: int = 10,
        dispersion_threshold_bps: float = 1.80,
        primary_spread_threshold_bps: float = 2.20,
        venue_drift_threshold_bps: float = 4.0,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if isinstance(window_size, bool) or not isinstance(window_size, int) or window_size < 3:
            window_size = 10
        if isinstance(cooldown_seconds, bool) or not isinstance(cooldown_seconds, (int, float)) or cooldown_seconds <= 0:
            cooldown_seconds = 45.0

        self.window_size = window_size
        self.dispersion_threshold_bps = float(dispersion_threshold_bps)
        self.primary_spread_threshold_bps = float(primary_spread_threshold_bps)
        self.venue_drift_threshold_bps = float(venue_drift_threshold_bps)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._dispersions: deque = deque(maxlen=self.window_size)
        self._primary_spreads: deque = deque(maxlen=self.window_size)
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""
        self._last_dispersion_bps: float = 0.0
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
        venue_quotes: List[Tuple[float, float]],
        current_time: Optional[float] = None,
    ) -> bool:
        """Process concurrent top-of-book quotes across M venues: [(bid_1, ask_1), (bid_2, ask_2), ...].

        Returns True if trading is blocked, False otherwise.
        """
        now = time.monotonic() if current_time is None else float(current_time)

        with self._lock:
            self._total_updates += 1

            if not isinstance(venue_quotes, (list, tuple)) or len(venue_quotes) < 2:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = "FAIL_CLOSED: Minimum 2 venue quotes required"
                self._total_violations += 1
                return True

            spreads_bps: List[float] = []
            bids: List[float] = []
            asks: List[float] = []

            for idx, q in enumerate(venue_quotes):
                if not isinstance(q, (list, tuple)) or len(q) < 2:
                    self._blocked_until = now + self.cooldown_seconds
                    self._last_block_reason = f"FAIL_CLOSED: Invalid quote tuple at venue {idx}"
                    self._total_violations += 1
                    return True

                v_bid = self._validate_numeric(q[0])
                v_ask = self._validate_numeric(q[1])

                if v_bid is None or v_ask is None or v_bid <= 0.0 or v_ask <= 0.0:
                    self._blocked_until = now + self.cooldown_seconds
                    self._last_block_reason = f"FAIL_CLOSED: Non-numeric, NaN, or non-positive price at venue {idx}"
                    self._total_violations += 1
                    return True

                spread = v_ask - v_bid
                if spread <= 0.0:
                    self._blocked_until = now + self.cooldown_seconds
                    self._last_block_reason = (
                        f"VENUE_CROSSED_OR_LOCKED: Venue {idx} spread {spread:.6f} <= 0 (Ask {v_ask} <= Bid {v_bid})"
                    )
                    self._total_violations += 1
                    return True

                mid = (v_bid + v_ask) / 2.0
                s_bps = (spread / mid) * 10000.0
                spreads_bps.append(s_bps)
                bids.append(v_bid)
                asks.append(v_ask)

            # 1. Acute Cross-Venue Quote Inversion / Locked Market (b_A >= a_B)
            max_bid = max(bids)
            min_ask = min(asks)
            if max_bid >= min_ask:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = (
                    f"CROSS_VENUE_QUOTE_CROSSING: Best bid across venues {max_bid:.5f} >= "
                    f"best ask across venues {min_ask:.5f}"
                )
                self._total_violations += 1
                return True

            # Compute cross-sectional dispersion
            m = len(spreads_bps)
            s_bar = sum(spreads_bps) / m
            dispersion = math.sqrt(sum((x - s_bar) ** 2 for x in spreads_bps) / m)
            self._last_dispersion_bps = dispersion

            # 2. Outlier Venue Drift relative to median
            sorted_spreads = sorted(spreads_bps)
            med_s = sorted_spreads[m // 2]
            max_drift = max(abs(x - med_s) for x in spreads_bps)
            if max_drift >= self.venue_drift_threshold_bps:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = (
                    f"OUTLIER_VENUE_DRIFT: Max spread drift {max_drift:.2f} bps >= "
                    f"{self.venue_drift_threshold_bps:.2f} bps relative to median {med_s:.2f} bps"
                )
                self._total_violations += 1
                return True

            self._dispersions.append(dispersion)
            self._primary_spreads.append(spreads_bps[0])

            # 3. Rolling Cross-Venue Spread Decoupling
            if len(self._dispersions) >= self.window_size:
                mean_disp = sum(self._dispersions) / len(self._dispersions)
                mean_p_spread = sum(self._primary_spreads) / len(self._primary_spreads)

                if mean_disp >= self.dispersion_threshold_bps and mean_p_spread >= self.primary_spread_threshold_bps:
                    self._blocked_until = now + self.cooldown_seconds
                    self._last_block_reason = (
                        f"CROSS_VENUE_SPREAD_DECOUPLING: Mean dispersion {mean_disp:.2f} bps >= "
                        f"{self.dispersion_threshold_bps:.2f} bps with primary spread {mean_p_spread:.2f} bps"
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
            self._dispersions.clear()
            self._primary_spreads.clear()
            self._blocked_until = 0.0
            self._last_block_reason = ""
            self._last_dispersion_bps = 0.0
            self._total_updates = 0
            self._total_violations = 0

    def get_status(self, current_time: Optional[float] = None) -> Dict[str, Any]:
        """Return diagnostic metrics and state dictionary."""
        now = time.monotonic() if current_time is None else float(current_time)
        with self._lock:
            remaining_cooldown = max(0.0, self._blocked_until - now)
            disps = list(self._dispersions)
            mean_d = (sum(disps) / len(disps)) if disps else self._last_dispersion_bps

            return {
                "guard_name": "Wave332LOBSpreadCrossSectionalDispersionGuard",
                "is_blocked": now < self._blocked_until,
                "remaining_cooldown_s": round(remaining_cooldown, 3),
                "last_block_reason": self._last_block_reason,
                "last_dispersion_bps": round(self._last_dispersion_bps, 4),
                "rolling_mean_dispersion_bps": round(mean_d, 4),
                "buffer_fill": len(self._dispersions),
                "total_updates": self._total_updates,
                "total_violations": self._total_violations,
            }
