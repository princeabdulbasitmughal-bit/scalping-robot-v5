"""
Wave 457: Cross-Venue Order Flow Toxicity Kyle's Lambda Divergence Guard
========================================================================
Institutional Quantitative Mathematical Formulation:
Under Kyle (1985) "Continuous Auctions and Informed Trader", Hasbrouck (1991),
and Cont, Kukanov & Stoikov (2014) "The Price Impact of Order Book Events",
price impact per unit of net signed order flow Q is modeled via Kyle's Lambda:
    Delta P_t = lambda * Q_t + epsilon_t

Where:
    lambda = Cov(Delta P, Q) / (Var(Q) + epsilon)

In multi-venue fragmented electronic markets (e.g. Primary ECN Venue A vs
Secondary Broker / MT5 Retail Feed Venue B):
- Venue A Kyle's Lambda: lambda_A = Cov(Delta P_A, Q_A) / (Var(Q_A) + epsilon)
- Venue B Kyle's Lambda: lambda_B = Cov(Delta P_B, Q_B) / (Var(Q_B) + epsilon)

The Normalized Cross-Venue Kyle Lambda Divergence is:
    D_lambda = |lambda_A - lambda_B| / max(|lambda_A|, |lambda_B|, 1e-6)

When an informed institutional sweep or HFT latency arbitrage cluster arrives:
1. Primary Venue A undergoes an instantaneous liquidity drain, causing lambda_A
   to spike dramatically into toxic territory:
   lambda_A > toxic_lambda_threshold
2. Secondary Venue B remains briefly stale, leading to extreme cross-venue divergence:
   D_lambda > max_divergence_ratio (e.g. > 0.70)
   or Cross-Venue Impact Ratio: lambda_A / max(lambda_B, 1e-6) > max_impact_ratio (e.g. > 3.0x)

Under such asymmetric adverse selection regimes, market makers and scalpers on the
stale venue are systematically picked off by latency arbitrageurs. The guard triggers
an institutional circuit breaker, immediately blocking fills and quoting until price
impact settles across all connected liquidity pools.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave457CrossVenueKyleLambdaGuard:
    """
    Guards against cross-venue adverse selection and predatory latency arbitrage
    by tracking Kyle's Lambda price impact divergence across primary and secondary venues.
    """

    def __init__(
        self,
        window_size: int = 20,
        max_divergence_ratio: float = 0.70,
        toxic_lambda_threshold: float = 0.02,
        max_impact_ratio: float = 3.0,
        min_samples: int = 10,
        cooldown_sec: float = 2.0
    ) -> None:
        if window_size < 10:
            raise ValueError(f"window_size must be >= 10, got {window_size}")
        if not (0.20 <= max_divergence_ratio <= 0.95):
            raise ValueError(f"max_divergence_ratio must be in [0.20, 0.95], got {max_divergence_ratio}")
        if toxic_lambda_threshold <= 0.0:
            raise ValueError(f"toxic_lambda_threshold must be > 0.0, got {toxic_lambda_threshold}")
        if max_impact_ratio <= 1.0:
            raise ValueError(f"max_impact_ratio must be > 1.0, got {max_impact_ratio}")
        if min_samples < 5:
            raise ValueError(f"min_samples must be >= 5, got {min_samples}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.window_size: int = window_size
        self.max_divergence_ratio: float = max_divergence_ratio
        self.toxic_lambda_threshold: float = toxic_lambda_threshold
        self.max_impact_ratio: float = max_impact_ratio
        self.min_samples: int = min_samples
        self.cooldown_sec: float = cooldown_sec

        # Ring buffers for Venue A and Venue B observations
        self._dp_a: List[float] = []
        self._flow_a: List[float] = []
        self._dp_b: List[float] = []
        self._flow_b: List[float] = []
        self._timestamps: List[float] = []

        # State telemetry
        self.lambda_a: float = 0.0
        self.lambda_b: float = 0.0
        self.divergence_ratio: float = 0.0
        self.impact_ratio: float = 1.0
        self.blocked_side: Optional[str] = None
        self._is_blocked: bool = False
        self._block_reason: str = ""
        self._last_breach_time: float = -1.0

    def update(
        self,
        d_price_a: float,
        flow_a: float,
        d_price_b: float,
        flow_b: float,
        timestamp: float
    ) -> bool:
        """
        Record discrete price revisions Delta P and signed order flows Q across both venues.
        Returns True if trading is blocked, False otherwise.
        """
        for val, name in [
            (d_price_a, "d_price_a"),
            (flow_a, "flow_a"),
            (d_price_b, "d_price_b"),
            (flow_b, "flow_b"),
        ]:
            if not math.isfinite(val):
                raise ValueError(f"{name} must be finite, got {val}")

        if self._timestamps and timestamp <= self._timestamps[-1]:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._timestamps[-1]}")

        self._dp_a.append(float(d_price_a))
        self._flow_a.append(float(flow_a))
        self._dp_b.append(float(d_price_b))
        self._flow_b.append(float(flow_b))
        self._timestamps.append(float(timestamp))

        # Maintain window size
        if len(self._dp_a) > self.window_size:
            self._dp_a.pop(0)
            self._flow_a.pop(0)
            self._dp_b.pop(0)
            self._flow_b.pop(0)
            self._timestamps.pop(0)

        # Check cooldown period
        if self._last_breach_time > 0 and (timestamp - self._last_breach_time) < self.cooldown_sec:
            self._is_blocked = True
            return True

        if len(self._dp_a) < self.min_samples:
            self._is_blocked = False
            self._block_reason = "INSUFFICIENT_SAMPLES"
            self.blocked_side = None
            return False

        # Compute Kyle's Lambda for Venue A
        dp_a_arr = np.array(self._dp_a, dtype=np.float64)
        flow_a_arr = np.array(self._flow_a, dtype=np.float64)
        var_flow_a = float(np.var(flow_a_arr))
        if var_flow_a > 1e-8:
            cov_a = float(np.cov(dp_a_arr, flow_a_arr)[0, 1])
            self.lambda_a = max(0.0, cov_a / var_flow_a)
        else:
            self.lambda_a = 0.0

        # Compute Kyle's Lambda for Venue B
        dp_b_arr = np.array(self._dp_b, dtype=np.float64)
        flow_b_arr = np.array(self._flow_b, dtype=np.float64)
        var_flow_b = float(np.var(flow_b_arr))
        if var_flow_b > 1e-8:
            cov_b = float(np.cov(dp_b_arr, flow_b_arr)[0, 1])
            self.lambda_b = max(0.0, cov_b / var_flow_b)
        else:
            self.lambda_b = 0.0

        # Compute Divergence and Impact Ratio
        max_lam = max(self.lambda_a, self.lambda_b, 1e-6)
        min_lam = max(min(self.lambda_a, self.lambda_b), 1e-6)
        self.divergence_ratio = float(abs(self.lambda_a - self.lambda_b) / max_lam)
        self.impact_ratio = float(max_lam / min_lam)

        # Evaluate Toxicity Circuit Breaker
        is_toxic = (
            (self.lambda_a > self.toxic_lambda_threshold or self.lambda_b > self.toxic_lambda_threshold)
            and (self.divergence_ratio > self.max_divergence_ratio or self.impact_ratio > self.max_impact_ratio)
        )

        if is_toxic:
            self._is_blocked = True
            self._last_breach_time = timestamp

            # Determine toxic flow direction from recent net flow on dominant venue
            dom_flow = np.mean(flow_a_arr[-3:]) if self.lambda_a >= self.lambda_b else np.mean(flow_b_arr[-3:])
            if dom_flow > 0:
                self.blocked_side = "BUY"  # Aggressive buy sweep adverse selection
            elif dom_flow < 0:
                self.blocked_side = "SELL" # Aggressive sell sweep adverse selection
            else:
                self.blocked_side = "ALL"

            self._block_reason = (
                f"TOXIC_KYLE_LAMBDA_DIVERGENCE: lambda_A={self.lambda_a:.4f}, lambda_B={self.lambda_b:.4f}, "
                f"div={self.divergence_ratio:.2%}>{self.max_divergence_ratio:.2%}, "
                f"ratio={self.impact_ratio:.1f}x (blocked: {self.blocked_side})"
            )
        else:
            self._is_blocked = False
            self._block_reason = ""
            self.blocked_side = None

        return self._is_blocked

    def is_blocked(self) -> bool:
        """Returns True if any trading or entry is blocked."""
        return self._is_blocked

    def is_entry_blocked(self, side: str = "BUY") -> bool:
        """
        OmniTrade interface compatibility. Checks if a specific order side is blocked.
        """
        if not self._is_blocked:
            return False
        if self.blocked_side in ("ALL", None):
            return True
        return side.upper() == self.blocked_side

    @property
    def block_reason(self) -> str:
        return self._block_reason

    def get_telemetry(self) -> Dict[str, Any]:
        """Returns telemetry dictionary for audit logs and risk dashboards."""
        return {
            "guard": "Wave457CrossVenueKyleLambdaGuard",
            "lambda_a": round(self.lambda_a, 6),
            "lambda_b": round(self.lambda_b, 6),
            "divergence_ratio": round(self.divergence_ratio, 4),
            "impact_ratio": round(self.impact_ratio, 2),
            "max_divergence_ratio": self.max_divergence_ratio,
            "toxic_lambda_threshold": self.toxic_lambda_threshold,
            "blocked_side": self.blocked_side,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason,
            "sample_size": len(self._dp_a)
        }

    def reset(self) -> None:
        """Resets all internal buffers and telemetry."""
        self._dp_a.clear()
        self._flow_a.clear()
        self._dp_b.clear()
        self._flow_b.clear()
        self._timestamps.clear()
        self.lambda_a = 0.0
        self.lambda_b = 0.0
        self.divergence_ratio = 0.0
        self.impact_ratio = 1.0
        self.blocked_side = None
        self._is_blocked = False
        self._block_reason = ""
        self._last_breach_time = -1.0
