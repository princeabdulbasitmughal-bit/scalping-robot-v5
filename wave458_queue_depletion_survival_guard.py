"""
Wave 458: Multi-Tier LOB Queue Depletion Survival Analysis Guard
================================================================
Institutional Quantitative Mathematical Formulation:
Under Cont & de Larrard (2013) "Price Dynamics in a Markovian Limit Order Book",
Abergel et al. (2016), and Huang & Tapia (2015), the depletion of limit order queues
is formalized via continuous-time survival analysis and hazard rate theory.

For each price level tier k in {1, ..., K} (where k=1 is top of book, k=2 is tier-2,
and k=3 is tier-3), the instantaneous queue depletion hazard rate h_k(t) measures
the arrival intensity of queue-depleting events (order cancellations C_k and aggressive
market order executions M_k) normalized by prevailing resting depth V_k(t):

    h_k(t) = (Delta C_k(t) + Delta M_k(t)) / (max(V_k(t), epsilon) * Delta t)

Under a local Poisson-Markovian hazard approximation, the survival probability of tier k's
liquidity queue over a forward latency horizon tau (e.g. tau = 100 ms) is given by:

    S_k(tau) = exp(-h_k(t) * tau)

The Composite Multi-Tier Liquidity Survival Index is the weighted survival probability
across the top K=3 tiers:
    S_multi(tau) = w_1 * S_1(tau) + w_2 * S_2(tau) + w_3 * S_3(tau)
    where w = [0.50, 0.30, 0.20]

Circuit Breaker Triggers:
1. Top-of-Book Queue Flash Drain:
   h_1(t) > max_top_hazard (default: > 4.0 s^-1)
2. Multi-Tier Liquidity Evaporation Crisis:
   S_multi(tau) < min_survival_prob (default: < 0.30 at tau = 100 ms)

When limit order queues suffer multi-tier flash depletion, resting quotes face extreme
adverse selection from predatory sweepers clearing the entire order book. The guard
triggers an emergency quotation freeze, blocking order submission and resting liquidity
until the depth replenishment rate restores queue stability.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave458QueueDepletionSurvivalGuard:
    """
    Evaluates multi-tier limit order book queue survival probabilities S(tau) and
    depletion hazard rates h_k(t) to guard against predatory liquidity sweeps.
    """

    def __init__(
        self,
        horizon_sec: float = 0.10,
        min_survival_prob: float = 0.30,
        max_top_hazard: float = 4.0,
        cooldown_sec: float = 1.5
    ) -> None:
        if horizon_sec <= 0.005:
            raise ValueError(f"horizon_sec must be > 0.005, got {horizon_sec}")
        if not (0.05 <= min_survival_prob <= 0.80):
            raise ValueError(f"min_survival_prob must be in [0.05, 0.80], got {min_survival_prob}")
        if max_top_hazard < 1.0:
            raise ValueError(f"max_top_hazard must be >= 1.0, got {max_top_hazard}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.horizon_sec: float = horizon_sec
        self.min_survival_prob: float = min_survival_prob
        self.max_top_hazard: float = max_top_hazard
        self.cooldown_sec: float = cooldown_sec

        # Weights for top 3 tiers: L1 (50%), L2 (30%), L3 (20%)
        self._weights: np.ndarray = np.array([0.50, 0.30, 0.20], dtype=np.float64)

        # Telemetry metrics
        self.hazard_rates: List[float] = [0.0, 0.0, 0.0]
        self.survival_probs: List[float] = [1.0, 1.0, 1.0]
        self.composite_survival: float = 1.0
        self._is_blocked: bool = False
        self._block_reason: str = ""
        self._last_breach_time: float = -1.0
        self._last_timestamp: float = -1.0

    def update(
        self,
        resting_depths: List[float],
        cancellations: List[float],
        market_fills: List[float],
        dt: float,
        timestamp: float
    ) -> bool:
        """
        Update the survival model with multi-tier depth observations.
        Expects at least 3 tiers of depth, cancellations, and fills.
        Returns True if trading is blocked, False otherwise.
        """
        if len(resting_depths) < 3 or len(cancellations) < 3 or len(market_fills) < 3:
            raise ValueError(
                f"Must provide at least 3 tiers of depth data. Got {len(resting_depths)}, "
                f"{len(cancellations)}, {len(market_fills)}"
            )

        if dt <= 0.0:
            raise ValueError(f"dt must be strictly positive, got {dt}")

        if self._last_timestamp >= 0.0 and timestamp <= self._last_timestamp:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._last_timestamp}")

        for i in range(3):
            if resting_depths[i] < 0.0 or cancellations[i] < 0.0 or market_fills[i] < 0.0:
                raise ValueError("Depths, cancellations, and fills must be non-negative")

        self._last_timestamp = timestamp

        # Check active cooldown
        if self._last_breach_time > 0 and (timestamp - self._last_breach_time) < self.cooldown_sec:
            self._is_blocked = True
            return True

        # Calculate hazard rate and survival probability for each tier
        h_list = []
        s_list = []
        for i in range(3):
            dep = max(resting_depths[i], 1e-4)
            drain = cancellations[i] + market_fills[i]
            # Instantaneous depletion intensity (hazard rate) per second
            h = drain / (dep * dt)
            s = math.exp(-h * self.horizon_sec)
            h_list.append(float(h))
            s_list.append(float(s))

        self.hazard_rates = h_list
        self.survival_probs = s_list

        # Composite multi-tier survival probability
        self.composite_survival = float(np.dot(self._weights, np.array(s_list, dtype=np.float64)))

        # Evaluate Circuit Breakers
        top_hazard = self.hazard_rates[0]
        if top_hazard > self.max_top_hazard:
            self._is_blocked = True
            self._last_breach_time = timestamp
            self._block_reason = (
                f"TOP_QUEUE_FLASH_DRAIN: Top hazard rate h_1={top_hazard:.2f}/s > "
                f"threshold {self.max_top_hazard:.2f}/s (L1 survival={s_list[0]:.1%})"
            )
        elif self.composite_survival < self.min_survival_prob:
            self._is_blocked = True
            self._last_breach_time = timestamp
            self._block_reason = (
                f"MULTI_TIER_QUEUE_EVAPORATION: Composite survival S_multi={self.composite_survival:.1%} < "
                f"floor {self.min_survival_prob:.1%} (h=[{h_list[0]:.1f}, {h_list[1]:.1f}, {h_list[2]:.1f}]/s)"
            )
        else:
            self._is_blocked = False
            self._block_reason = ""

        return self._is_blocked

    def is_blocked(self) -> bool:
        """Returns True if trading is blocked by the Queue Depletion Survival Guard."""
        return self._is_blocked

    def is_entry_blocked(self, side: str = "BUY") -> bool:
        """OmniTrade interface compatibility. Blocks all entries when active."""
        return self._is_blocked

    @property
    def block_reason(self) -> str:
        return self._block_reason

    def get_telemetry(self) -> Dict[str, Any]:
        """Telemetry metadata for institutional risk auditing."""
        return {
            "guard": "Wave458QueueDepletionSurvivalGuard",
            "top_hazard_rate": round(self.hazard_rates[0], 3),
            "tier2_hazard_rate": round(self.hazard_rates[1], 3),
            "tier3_hazard_rate": round(self.hazard_rates[2], 3),
            "top_survival_prob": round(self.survival_probs[0], 4),
            "composite_survival": round(self.composite_survival, 4),
            "min_survival_prob": self.min_survival_prob,
            "max_top_hazard": self.max_top_hazard,
            "horizon_sec": self.horizon_sec,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason
        }

    def reset(self) -> None:
        """Reset internal state."""
        self.hazard_rates = [0.0, 0.0, 0.0]
        self.survival_probs = [1.0, 1.0, 1.0]
        self.composite_survival = 1.0
        self._is_blocked = False
        self._block_reason = ""
        self._last_breach_time = -1.0
        self._last_timestamp = -1.0
