"""
Wave 473: Cross-Venue Queue Imbalance Dispersion Guard
======================================================
Institutional Quantitative Mathematical Formulation:
Under O'Hara & Ye (2011) "Is Market Fragmentation Harming Market Quality?",
Budish, Cramton & Shim (2015) "The High-Frequency Trading Arms Race", and
Menkveld (2013) "High Frequency Trading and the New Market Makers", modern financial
markets operate across fragmented execution venues (ECNs, alternative trading systems,
and bank liquidity pools).

For V distinct execution venues (v = 1, ..., V), let the normalized top-of-book queue imbalance be:
    I_v(t) = (q_v^{bid}(t) - q_v^{ask}(t)) / max(q_v^{bid}(t) + q_v^{ask}(t), epsilon) in [-1.0, 1.0]

Microstructure Invariants:
1. Cross-Venue Queue Imbalance Divergence:
   Delta I_{cross}(t) = max_{v} I_v(t) - min_{v} I_v(t) in [0.0, 2.0]
   Under benign, efficient liquidity routing, Delta I_{cross}(t) < 0.80.
   When Delta I_{cross}(t) > max_divergence_threshold (default: > 1.40), venues exhibit
   diametrically opposed queue pressure, indicating that latency arbitrageurs are picking off
   stale quotes on one venue before liquidity providers can cancel on another.

2. Cross-Venue Imbalance Standard Deviation:
   sigma_I(t) = sqrt( 1 / (V - 1) * sum_{v=1}^V (I_v(t) - bar{I}(t))^2 )
   When sigma_I(t) > max_imbalance_std_threshold (default: > 0.65), queue state coherence has collapsed.

3. Directional Venue Contagion Attribution:
   bar{I}(t) = 1 / V * sum_{v=1}^V I_v(t)
   - When bar{I}(t) < -0.50: Aggregate venues are dominated by ask-side overhang -> BUY entries toxic.
   - When bar{I}(t) > 0.50: Aggregate venues are dominated by bid-side overhang -> SELL entries toxic.
   - When imbalance is mixed or unaligned: ALL entries blocked.

When triggered, the guard isolates multi-venue routing, protecting the trader from adverse selection
caused by predatory cross-venue latency arbitrage.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave473CrossVenueQueueImbalanceDispersionGuard:
    """
    Monitors queue imbalance divergence, variance, and cross-venue decoupling across
    fragmented execution venues to prevent latency-arbitrage adverse selection.
    """

    def __init__(
        self,
        max_divergence_threshold: float = 1.40,
        max_imbalance_std_threshold: float = 0.65,
        directional_bias_threshold: float = 0.50,
        cooldown_sec: float = 2.0
    ) -> None:
        if not (0.80 <= max_divergence_threshold <= 1.95):
            raise ValueError(f"max_divergence_threshold must be in [0.80, 1.95], got {max_divergence_threshold}")
        if not (0.30 <= max_imbalance_std_threshold <= 0.95):
            raise ValueError(f"max_imbalance_std_threshold must be in [0.30, 0.95], got {max_imbalance_std_threshold}")
        if not (0.20 <= directional_bias_threshold <= 0.80):
            raise ValueError(f"directional_bias_threshold must be in [0.20, 0.80], got {directional_bias_threshold}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.max_divergence_threshold: float = max_divergence_threshold
        self.max_imbalance_std_threshold: float = max_imbalance_std_threshold
        self.directional_bias_threshold: float = directional_bias_threshold
        self.cooldown_sec: float = cooldown_sec

        # Telemetry metrics
        self.divergence: float = 0.0
        self.imbalance_std: float = 0.0
        self.mean_imbalance: float = 0.0
        self.venue_imbalances: List[float] = []
        self.blocked_side: Optional[str] = None
        self._is_blocked: bool = False
        self._block_reason: str = ""
        self._last_breach_time: float = -1.0
        self._last_timestamp: float = -1.0

    def update(
        self,
        venue_bid_depths: List[float],
        venue_ask_depths: List[float],
        timestamp: float = 0.0
    ) -> bool:
        """
        Record top-of-book bid and ask depths across at least 2 fragmented execution venues.
        Returns True if trading is blocked, False otherwise.
        """
        if len(venue_bid_depths) != len(venue_ask_depths):
            raise ValueError("venue_bid_depths and venue_ask_depths must have equal length")
        if len(venue_bid_depths) < 2:
            raise ValueError("venue_bid_depths and venue_ask_depths must contain at least 2 venues")
        for b, a in zip(venue_bid_depths, venue_ask_depths):
            if not (math.isfinite(b) and math.isfinite(a)):
                raise ValueError("All venue depths must be finite numbers")
            if b < 0.0 or a < 0.0:
                raise ValueError("Venue depths must be non-negative")
        if not math.isfinite(timestamp):
            raise ValueError(f"timestamp must be finite, got {timestamp}")
        if self._last_timestamp >= 0.0 and timestamp <= self._last_timestamp:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._last_timestamp}")

        self._last_timestamp = timestamp

        # Check cooldown from prior breach
        if self._last_breach_time > 0 and (timestamp - self._last_breach_time) < self.cooldown_sec:
            self._is_blocked = True
            return True

        # Compute normalized queue imbalance for each venue: I_v in [-1.0, 1.0]
        eps = 1e-4
        imb = []
        for b, a in zip(venue_bid_depths, venue_ask_depths):
            total = b + a
            if total <= eps:
                imb.append(0.0)
            else:
                imb.append((b - a) / total)

        self.venue_imbalances = [round(float(x), 4) for x in imb]
        imb_arr = np.array(imb, dtype=np.float64)

        # 1. Cross-venue queue imbalance divergence
        self.divergence = float(np.max(imb_arr) - np.min(imb_arr))

        # 2. Cross-venue imbalance standard deviation
        self.imbalance_std = float(np.std(imb_arr, ddof=1))

        # 3. Mean cross-venue imbalance
        self.mean_imbalance = float(np.mean(imb_arr))

        # Evaluate Circuit Breakers
        divergence_breached = (self.divergence > self.max_divergence_threshold)
        std_breached = (self.imbalance_std > self.max_imbalance_std_threshold)
        decoupling_breached = (self.divergence > 1.20 and self.imbalance_std > 0.50)

        if divergence_breached or std_breached or decoupling_breached:
            self._is_blocked = True
            self._last_breach_time = timestamp

            # Directional attribution
            if self.mean_imbalance < -self.directional_bias_threshold:
                self.blocked_side = "BUY" # Systematic ask overhang -> buying into selling cascade is toxic
                side_note = "CROSS_VENUE_ASK_OVERHANG"
            elif self.mean_imbalance > self.directional_bias_threshold:
                self.blocked_side = "SELL" # Systematic bid overhang -> shorting into buy pressure is toxic
                side_note = "CROSS_VENUE_BID_OVERHANG"
            else:
                self.blocked_side = "ALL"
                side_note = "CROSS_VENUE_ARBITRAGE_DECOUPLING"

            trigger = (
                "CROSS_VENUE_IMBALANCE_DIVERGENCE" if divergence_breached else
                ("CROSS_VENUE_IMBALANCE_DISPERSION" if std_breached else "LATENCY_ARBITRAGE_QUEUE_DECOUPLING")
            )
            self._block_reason = (
                f"{trigger}: Delta_I={self.divergence:.2f} (max={self.max_divergence_threshold:.2f}), "
                f"sigma_I={self.imbalance_std:.2f} (max={self.max_imbalance_std_threshold:.2f}), "
                f"mean_I={self.mean_imbalance:.2f} [{side_note}], blocked: {self.blocked_side}"
            )
        else:
            self._is_blocked = False
            self.blocked_side = None
            self._block_reason = ""

        return self._is_blocked

    def is_blocked(self) -> bool:
        """Returns True if trading is blocked."""
        return self._is_blocked

    def is_entry_blocked(self, side: str = "BUY") -> bool:
        """OmniTrade interface compatibility. Checks if specific side is blocked."""
        if not self._is_blocked:
            return False
        if self.blocked_side == "ALL":
            return True
        return self.blocked_side == side.upper()

    @property
    def block_reason(self) -> str:
        return self._block_reason

    def get_telemetry(self) -> Dict[str, Any]:
        """Telemetry metadata for institutional risk auditing."""
        return {
            "guard": "Wave473CrossVenueQueueImbalanceDispersionGuard",
            "divergence": round(self.divergence, 4),
            "imbalance_std": round(self.imbalance_std, 4),
            "mean_imbalance": round(self.mean_imbalance, 4),
            "venue_imbalances": self.venue_imbalances,
            "max_divergence_threshold": self.max_divergence_threshold,
            "max_imbalance_std_threshold": self.max_imbalance_std_threshold,
            "blocked_side": self.blocked_side,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason
        }

    def reset(self) -> None:
        """Reset internal state."""
        self.divergence = 0.0
        self.imbalance_std = 0.0
        self.mean_imbalance = 0.0
        self.venue_imbalances.clear()
        self.blocked_side = None
        self._is_blocked = False
        self._block_reason = ""
        self._last_breach_time = -1.0
        self._last_timestamp = -1.0
