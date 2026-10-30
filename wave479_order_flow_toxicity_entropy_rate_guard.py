"""
Wave 479: Order Flow Toxicity Entropy Rate Guard
================================================
Institutional Quantitative Mathematical Formulation:
Under Easley, Lopez de Prado & O'Hara (2012) "Flow Toxicity and Liquidity in a High-Frequency World",
Shannon (1948), and Rényi (1961), order flow toxicity represents the probability that incoming
orders are submitted by informed traders possessing superior private information.

In Volume-Synchronized Clock space with bucket volume V_{bucket}, let:
    p_{buy} = V_{buy} / V_{bucket},  p_{sell} = V_{sell} / V_{bucket}

1. Volumetric Shannon Entropy:
   H_V = - p_{buy} * log2(p_{buy}) - p_{sell} * log2(p_{sell}) in [0.0, 1.0]

2. Rényi Collision Entropy (alpha = 2):
   H_2 = - log2(p_{buy}^2 + p_{sell}^2) in [0.0, 1.0]

3. Temporal Entropy Evaporation Velocity:
   v_H = [H_V(t) - H_V(t - Delta t)] / Delta t  (sec^-1)
   When v_H < max_negative_entropy_velocity (default: < -0.40 sec^-1), order flow entropy is
   collapsing rapidly, indicating sudden coordination by predatory institutional flow.

4. Rolling VPIN (Volume-Synchronized Probability of Toxicity):
   VPIN = 1 / B * sum_{b=1}^B |2 * p_{buy}(b) - 1| in [0.0, 1.0]

Circuit Breakers:
1. FLOW_TOXICITY_ENTROPY_COLLAPSE: H_V < min_entropy_threshold (default: < 0.45)
2. VPIN_TOXICITY_EXPLOSION: VPIN > max_vpin_threshold (default: > 0.65)
3. ENTROPY_EVAPORATION_VELOCITY_BREACH: v_H < max_negative_entropy_velocity (default: < -0.40 sec^-1)

Directional Attribution:
- When p_{buy} > 0.80: Informed buy pressure -> SELL entries toxic.
- When p_{sell} > 0.80: Informed sell pressure -> BUY entries toxic.
- When general entropy collapses: ALL entries blocked.

When triggered, the guard freezes execution routing, avoiding adverse selection from toxic informed flows.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave479OrderFlowToxicityEntropyRateGuard:
    """
    Monitors volume-synchronized order flow entropy, Rényi collision entropy,
    entropy evaporation velocity, and rolling VPIN to defend against toxic informed flow.
    """

    def __init__(
        self,
        window_buckets: int = 20,
        min_buckets: int = 8,
        min_entropy_threshold: float = 0.45,
        max_vpin_threshold: float = 0.65,
        max_negative_entropy_velocity: float = -0.40,
        cooldown_sec: float = 2.0
    ) -> None:
        if window_buckets < 10:
            raise ValueError(f"window_buckets must be >= 10, got {window_buckets}")
        if min_buckets < 5:
            raise ValueError(f"min_buckets must be >= 5, got {min_buckets}")
        if min_buckets > window_buckets:
            raise ValueError(f"min_buckets ({min_buckets}) cannot exceed window_buckets ({window_buckets})")
        if not (0.20 <= min_entropy_threshold <= 0.80):
            raise ValueError(f"min_entropy_threshold must be in [0.20, 0.80], got {min_entropy_threshold}")
        if not (0.40 <= max_vpin_threshold <= 0.90):
            raise ValueError(f"max_vpin_threshold must be in [0.40, 0.90], got {max_vpin_threshold}")
        if max_negative_entropy_velocity > -0.05:
            raise ValueError(f"max_negative_entropy_velocity must be <= -0.05, got {max_negative_entropy_velocity}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.window_buckets: int = window_buckets
        self.min_buckets: int = min_buckets
        self.min_entropy_threshold: float = min_entropy_threshold
        self.max_vpin_threshold: float = max_vpin_threshold
        self.max_negative_entropy_velocity: float = max_negative_entropy_velocity
        self.cooldown_sec: float = cooldown_sec

        # Historical state
        self._imbalances: List[float] = []
        self._prev_entropy: Optional[float] = None

        # Telemetry metrics
        self.shannon_entropy: float = 1.0
        self.renyi_entropy: float = 1.0
        self.entropy_velocity: float = 0.0
        self.vpin: float = 0.0
        self.p_buy: float = 0.50
        self.p_sell: float = 0.50
        self.sample_count: int = 0
        self.blocked_side: Optional[str] = None
        self._is_blocked: bool = False
        self._block_reason: str = ""
        self._last_breach_time: float = -1.0
        self._last_timestamp: float = -1.0

    def _binary_entropy(self, p: float) -> float:
        """Compute binary Shannon entropy."""
        eps = 1e-6
        p = min(1.0 - eps, max(eps, p))
        return -p * math.log2(p) - (1.0 - p) * math.log2(1.0 - p)

    def update(
        self,
        buy_volume: float,
        sell_volume: float,
        timestamp: float = 0.0
    ) -> bool:
        """
        Record instantaneous bucket buy and sell volume.
        Returns True if trading is blocked, False otherwise.
        """
        if not (math.isfinite(buy_volume) and math.isfinite(sell_volume)):
            raise ValueError("buy_volume and sell_volume must be finite numbers")
        if buy_volume < 0.0 or sell_volume < 0.0:
            raise ValueError("Volumes must be non-negative")
        if not math.isfinite(timestamp):
            raise ValueError(f"timestamp must be finite, got {timestamp}")
        if self._last_timestamp >= 0.0 and timestamp <= self._last_timestamp:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._last_timestamp}")

        dt = (timestamp - self._last_timestamp) if self._last_timestamp >= 0.0 else 0.0
        self._last_timestamp = timestamp

        # Check cooldown from prior breach
        if self._last_breach_time > 0 and (timestamp - self._last_breach_time) < self.cooldown_sec:
            self._is_blocked = True
            return True

        total_vol = buy_volume + sell_volume
        eps = 1e-6
        if total_vol <= eps:
            self.p_buy = 0.50
            self.p_sell = 0.50
            imb = 0.0
        else:
            self.p_buy = buy_volume / total_vol
            self.p_sell = sell_volume / total_vol
            imb = abs(self.p_buy - self.p_sell)

        self.shannon_entropy = self._binary_entropy(self.p_buy)

        # Rényi Collision Entropy H_2
        sum_sq = self.p_buy**2 + self.p_sell**2
        self.renyi_entropy = -math.log2(max(eps, sum_sq))

        # Entropy velocity
        if self._prev_entropy is not None and dt > 0.0:
            self.entropy_velocity = (self.shannon_entropy - self._prev_entropy) / dt
        else:
            self.entropy_velocity = 0.0
        self._prev_entropy = self.shannon_entropy

        self._imbalances.append(imb)
        if len(self._imbalances) > self.window_buckets:
            self._imbalances.pop(0)

        self.sample_count = len(self._imbalances)
        if self.sample_count < self.min_buckets:
            self._is_blocked = False
            self.blocked_side = None
            self._block_reason = "INSUFFICIENT_SAMPLES"
            self.vpin = float(np.mean(self._imbalances)) if self._imbalances else 0.0
            return False

        self.vpin = float(np.mean(self._imbalances))

        # Evaluate Circuit Breakers
        entropy_collapsed = (self.shannon_entropy < self.min_entropy_threshold)
        vpin_breached = (self.vpin > self.max_vpin_threshold)
        velocity_breached = (self.entropy_velocity < self.max_negative_entropy_velocity)

        if entropy_collapsed or vpin_breached or velocity_breached:
            self._is_blocked = True
            self._last_breach_time = timestamp

            # Directional attribution
            if self.p_buy > 0.80:
                self.blocked_side = "SELL" # Heavy toxic buying pressure -> shorting is toxic
                side_note = "INFORMED_BUY_SWEEP"
            elif self.p_sell > 0.80:
                self.blocked_side = "BUY" # Heavy toxic selling pressure -> buying is toxic
                side_note = "INFORMED_SELL_DUMP"
            else:
                self.blocked_side = "ALL"
                side_note = "BILATERAL_FLOW_TOXICITY"

            trigger = (
                "FLOW_TOXICITY_ENTROPY_COLLAPSE" if entropy_collapsed else
                ("VPIN_TOXICITY_EXPLOSION" if vpin_breached else "ENTROPY_EVAPORATION_VELOCITY_BREACH")
            )
            self._block_reason = (
                f"{trigger}: H_V={self.shannon_entropy:.3f} (min={self.min_entropy_threshold:.3f}), "
                f"VPIN={self.vpin:.3f} (max={self.max_vpin_threshold:.3f}), v_H={self.entropy_velocity:.2f}/s "
                f"[{side_note}], blocked: {self.blocked_side}"
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
            "guard": "Wave479OrderFlowToxicityEntropyRateGuard",
            "shannon_entropy": round(self.shannon_entropy, 4),
            "renyi_entropy": round(self.renyi_entropy, 4),
            "entropy_velocity": round(self.entropy_velocity, 4),
            "vpin": round(self.vpin, 4),
            "p_buy": round(self.p_buy, 4),
            "p_sell": round(self.p_sell, 4),
            "sample_count": self.sample_count,
            "min_entropy_threshold": self.min_entropy_threshold,
            "max_vpin_threshold": self.max_vpin_threshold,
            "blocked_side": self.blocked_side,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason
        }

    def reset(self) -> None:
        """Reset internal state."""
        self._imbalances.clear()
        self._prev_entropy = None
        self.shannon_entropy = 1.0
        self.renyi_entropy = 1.0
        self.entropy_velocity = 0.0
        self.vpin = 0.0
        self.p_buy = 0.50
        self.p_sell = 0.50
        self.sample_count = 0
        self.blocked_side = None
        self._is_blocked = False
        self._block_reason = ""
        self._last_breach_time = -1.0
        self._last_timestamp = -1.0
