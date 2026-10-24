"""Wave 334: Limit Order Book Spread-Volatility Regime Dynamic Beta Decoupling Guard.

Mathematical and Microstructural Context:
----------------------------------------
In competitive electronic order books, market makers dynamically price the inside
bid-ask spread S_t (in basis points) proportional to short-term high-frequency realized
volatility sigma_t (in basis points) to cover inventory holding risk and adverse selection
(Roll 1984; Stoll 1989; Huang & Stoll 1997; Wyart et al. 2008):
    Theoretical spread: S_t = beta * sigma_t + S_0
    Instantaneous ratio: R_{S/sigma} = S_t / max(sigma_t, epsilon)

Under orderly market-making equilibrium:
1. Quoted spread and instantaneous volatility oscillate in close harmony,
   maintaining a stable ratio R_{S/sigma} in [0.50, 2.20].

However, during liquidity regime breakdowns, predatory quote extraction, or adverse selection shocks:
1. Spread-Gouging Volatility Decoupling (mean(R_{S/sigma}) >= 3.20 over N >= 10 ticks with S_t >= 2.20 bps):
   Market makers widen the spread excessively despite low or moderate underlying price volatility,
   extracting predatory monopoly rent or withholding liquidity.
2. Artificial Narrow Spread Trap / Latency Arbitrage Avalanche (mean(R_{S/sigma}) <= 0.28 with sigma_t >= 4.50 bps):
   High-frequency volatility explodes, yet quoted spread remains artificially tight (pinned by stale
   passive limit orders), creating an extreme adverse selection trap where scalpers get steamrolled.
3. Acute Spread Beta Shock:
   An instantaneous spread expansion Delta S >= 3.0 bps in dt <= 0.5s while realized volatility
   remains subdued (sigma_t <= 1.20 bps).

When any of these anomalies occur, the guard trips an execution block for
`cooldown_seconds` (default: 45.0s) to protect against adverse selection or spread gouging.

Thread Safety: Protected by threading.RLock.
Fail-Closed: Any non-numeric, NaN, infinite, or non-positive price/volatility inputs trip an immediate block.
"""

from collections import deque
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


class Wave334LOBSpreadVolatilityRegimeBetaGuard:
    """Wave 334: LOB Spread-Volatility Regime Dynamic Beta Decoupling Guard."""

    def __init__(
        self,
        window_size: int = 10,
        spread_gouging_ratio_threshold: float = 3.20,
        min_spread_bps_for_gouging: float = 2.20,
        narrow_spread_trap_ratio_threshold: float = 0.28,
        min_volatility_bps_for_trap: float = 4.50,
        acute_spread_jump_bps: float = 3.00,
        acute_time_window_s: float = 0.50,
        acute_max_volatility_bps: float = 1.20,
        cooldown_seconds: float = 45.0,
    ) -> None:
        if isinstance(window_size, bool) or not isinstance(window_size, int) or window_size < 3:
            window_size = 10
        if isinstance(cooldown_seconds, bool) or not isinstance(cooldown_seconds, (int, float)) or cooldown_seconds <= 0:
            cooldown_seconds = 45.0

        self.window_size = window_size
        self.spread_gouging_ratio_threshold = float(spread_gouging_ratio_threshold)
        self.min_spread_bps_for_gouging = float(min_spread_bps_for_gouging)
        self.narrow_spread_trap_ratio_threshold = float(narrow_spread_trap_ratio_threshold)
        self.min_volatility_bps_for_trap = float(min_volatility_bps_for_trap)
        self.acute_spread_jump_bps = float(acute_spread_jump_bps)
        self.acute_time_window_s = float(acute_time_window_s)
        self.acute_max_volatility_bps = float(acute_max_volatility_bps)
        self.cooldown_seconds = float(cooldown_seconds)

        self._lock = threading.RLock()
        self._ratios: deque = deque(maxlen=self.window_size)
        self._spreads: deque = deque(maxlen=self.window_size)
        self._volatilities: deque = deque(maxlen=self.window_size)
        self._recent_spread_events: deque = deque(maxlen=self.window_size)
        self._blocked_until: float = 0.0
        self._last_block_reason: str = ""
        self._last_ratio: float = 0.0
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
        bid: float,
        ask: float,
        realized_volatility_bps: float,
        current_time: Optional[float] = None,
    ) -> bool:
        """Update guard with instantaneous top-of-book quotes and realized volatility (in bps).

        Returns True if trading is blocked, False otherwise.
        """
        now = time.monotonic() if current_time is None else float(current_time)

        with self._lock:
            self._total_updates += 1

            v_bid = self._validate_numeric(bid)
            v_ask = self._validate_numeric(ask)
            v_vol = self._validate_numeric(realized_volatility_bps)

            if v_bid is None or v_ask is None or v_vol is None or v_bid <= 0.0 or v_ask <= 0.0 or v_vol < 0.0:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = (
                    f"FAIL_CLOSED: Invalid inputs bid={bid}, ask={ask}, vol={realized_volatility_bps}"
                )
                self._total_violations += 1
                return True

            spread = v_ask - v_bid
            if spread <= 0.0:
                self._blocked_until = now + self.cooldown_seconds
                self._last_block_reason = (
                    f"CROSSED_OR_LOCKED_BOOK: Ask {v_ask} <= Bid {v_bid} (Spread: {spread:.6f})"
                )
                self._total_violations += 1
                return True

            mid = (v_bid + v_ask) / 2.0
            spread_bps = (spread / mid) * 10000.0

            # 1. Acute Spread Jump check against subdued volatility
            self._recent_spread_events.append((now, spread_bps, v_vol))
            # Purge entries older than acute_time_window_s
            while self._recent_spread_events and (now - self._recent_spread_events[0][0]) > self.acute_time_window_s:
                self._recent_spread_events.popleft()

            if len(self._recent_spread_events) >= 2:
                earliest_spread = self._recent_spread_events[0][1]
                delta_spread = spread_bps - earliest_spread
                if delta_spread >= self.acute_spread_jump_bps and v_vol <= self.acute_max_volatility_bps:
                    self._blocked_until = now + self.cooldown_seconds
                    self._last_block_reason = (
                        f"ACUTE_SPREAD_BETA_SHOCK: Spread jump +{delta_spread:.2f} bps >= {self.acute_spread_jump_bps:.2f} bps "
                        f"in {self.acute_time_window_s:.2f}s with subdued volatility {v_vol:.2f} bps <= {self.acute_max_volatility_bps:.2f} bps"
                    )
                    self._total_violations += 1
                    return True

            # Calculate instantaneous ratio
            # Use small epsilon (0.01 bps) to avoid division by zero if vol is zero
            denom_vol = max(v_vol, 0.01)
            ratio = spread_bps / denom_vol
            self._last_ratio = ratio

            self._ratios.append(ratio)
            self._spreads.append(spread_bps)
            self._volatilities.append(v_vol)

            if len(self._ratios) >= self.window_size:
                mean_ratio = sum(self._ratios) / len(self._ratios)
                mean_spread = sum(self._spreads) / len(self._spreads)
                mean_vol = sum(self._volatilities) / len(self._volatilities)

                # 2. Spread-Gouging Volatility Decoupling
                if mean_ratio >= self.spread_gouging_ratio_threshold and mean_spread >= self.min_spread_bps_for_gouging:
                    self._blocked_until = now + self.cooldown_seconds
                    self._last_block_reason = (
                        f"SPREAD_GOUGING_VOLATILITY_DECOUPLING: Mean ratio {mean_ratio:.2f} >= "
                        f"{self.spread_gouging_ratio_threshold:.2f} with mean spread {mean_spread:.2f} bps >= {self.min_spread_bps_for_gouging:.2f} bps"
                    )
                    self._total_violations += 1
                    return True

                # 3. Artificial Narrow Spread Trap
                if mean_ratio <= self.narrow_spread_trap_ratio_threshold and mean_vol >= self.min_volatility_bps_for_trap:
                    self._blocked_until = now + self.cooldown_seconds
                    self._last_block_reason = (
                        f"NARROW_SPREAD_TRAP: Mean ratio {mean_ratio:.2f} <= "
                        f"{self.narrow_spread_trap_ratio_threshold:.2f} with mean volatility {mean_vol:.2f} bps >= {self.min_volatility_bps_for_trap:.2f} bps"
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
            self._ratios.clear()
            self._spreads.clear()
            self._volatilities.clear()
            self._recent_spread_events.clear()
            self._blocked_until = 0.0
            self._last_block_reason = ""
            self._last_ratio = 0.0
            self._total_updates = 0
            self._total_violations = 0

    def get_status(self, current_time: Optional[float] = None) -> Dict[str, Any]:
        """Return diagnostic metrics and state dictionary."""
        now = time.monotonic() if current_time is None else float(current_time)
        with self._lock:
            remaining_cooldown = max(0.0, self._blocked_until - now)
            ratios_list = list(self._ratios)
            mean_r = (sum(ratios_list) / len(ratios_list)) if ratios_list else self._last_ratio

            return {
                "guard_name": "Wave334LOBSpreadVolatilityRegimeBetaGuard",
                "is_blocked": now < self._blocked_until,
                "remaining_cooldown_s": round(remaining_cooldown, 3),
                "last_block_reason": self._last_block_reason,
                "last_ratio": round(self._last_ratio, 4),
                "rolling_mean_ratio": round(mean_r, 4),
                "buffer_fill": len(self._ratios),
                "total_updates": self._total_updates,
                "total_violations": self._total_violations,
            }
