"""
Wave 487: Order Flow Kyle Lambda & Microstructure Price Discovery Share Guard
==============================================================================
Institutional Quantitative Mathematical Formulation:
Under Kyle (1985) "Continuous Auctions and Informed Trader", Hasbrouck (1991),
and De Jong & Rindi (2009), institutional market makers quote prices subject to adverse selection:

    Delta P_t = lambda * Q_t + epsilon_t

where:
    - Q_t is the signed order flow volume (Q_t = sign(trade) * volume).
    - Delta P_t is the subsequent mid-quote revision or price return.
    - lambda is Kyle's Lambda (price impact per unit of order flow):
      lambda = Cov(Delta P, Q) / max(Var(Q), 1e-9)

1. Information Share of Order Flow (Price Discovery Share):
   S_info = R^2 = [Cov(Delta P, Q)]^2 / (Var(Delta P) * Var(Q) + 1e-9) in [0.0, 1.0]

   - S_info measures the proportion of price discovery driven by informed order flow.
   - When S_info > 0.75, informed institutional toxic flow saturates the book, causing massive adverse selection.

2. Directional Kyle Lambda Asymmetry:
   lambda_buy = Cov(Delta P_buy, Q_buy) / max(Var(Q_buy), 1e-9)
   lambda_sell = Cov(|Delta P_sell|, |Q_sell|) / max(Var(Q_sell), 1e-9)

   Lambda_skew = (lambda_buy - lambda_sell) / (lambda_buy + lambda_sell + 1e-9) in [-1.0, 1.0]

Circuit Breakers:
1. INFORMATION_SHARE_SATURATION: S_info >= max_info_share (default: >= 0.80) -> HALT_ALL
2. KYLE_LAMBDA_CRITICAL: lambda_norm >= critical_lambda_threshold (default: >= 0.85) -> HALT_ALL
3. Asymmetric Directional Adverse Selection:
   - Lambda_skew >= lambda_skew_threshold (default: >= 0.65) -> BLOCK_BUY
   - Lambda_skew <= -lambda_skew_threshold (default: <= -0.65) -> BLOCK_SELL
"""

import math
import time
import numpy as np
from typing import List, Dict, Any, Optional


class Wave487KyleLambdaPriceDiscoveryShareGuard:
    """
    Monitors Kyle's Lambda price impact coefficient, Hasbrouck information share,
    and directional adverse selection asymmetry to protect liquidity routing.
    """

    def __init__(
        self,
        max_info_share: float = 0.80,
        critical_lambda_threshold: float = 0.85,
        lambda_skew_threshold: float = 0.65,
        cooldown_sec: float = 2.0
    ) -> None:
        if not (0.50 <= max_info_share <= 0.95):
            raise ValueError(f"max_info_share must be in [0.50, 0.95], got {max_info_share}")
        if not (0.50 <= critical_lambda_threshold <= 1.20):
            raise ValueError(f"critical_lambda_threshold must be in [0.50, 1.20], got {critical_lambda_threshold}")
        if not (0.35 <= lambda_skew_threshold <= 0.85):
            raise ValueError(f"lambda_skew_threshold must be in [0.35, 0.85], got {lambda_skew_threshold}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.max_info_share: float = max_info_share
        self.critical_lambda_threshold: float = critical_lambda_threshold
        self.lambda_skew_threshold: float = lambda_skew_threshold
        self.cooldown_sec: float = cooldown_sec

        # State tracking
        self.breaker_active: bool = False
        self.breaker_tripped_at: float = 0.0
        self.last_trip_reason: str = "NONE"

    def reset(self) -> None:
        """Reset temporal state."""
        self.breaker_active = False
        self.breaker_tripped_at = 0.0
        self.last_trip_reason = "NONE"

    def estimate_kyle_metrics(
        self,
        signed_volumes: List[float],
        price_changes: List[float]
    ) -> Dict[str, float]:
        """
        Estimate Kyle's Lambda and Hasbrouck Information Share via OLS regression.
        """
        if len(signed_volumes) != len(price_changes):
            raise ValueError(f"signed_volumes length ({len(signed_volumes)}) != price_changes length ({len(price_changes)})")
        if len(signed_volumes) < 4:
            raise ValueError(f"Must provide at least 4 observations for Kyle estimation, got {len(signed_volumes)}")

        q = np.array(signed_volumes, dtype=np.float64)
        dp = np.array(price_changes, dtype=np.float64)

        var_q = float(np.var(q, ddof=1)) if len(q) > 1 else 0.0
        var_dp = float(np.var(dp, ddof=1)) if len(dp) > 1 else 0.0

        if var_q < 1e-9 or var_dp < 1e-9:
            return {"lambda": 0.0, "s_info": 0.0, "lambda_buy": 0.0, "lambda_sell": 0.0, "lambda_skew": 0.0}

        cov_q_dp = float(np.cov(q, dp)[0, 1])
        kyle_lambda = cov_q_dp / var_q
        s_info = (cov_q_dp ** 2) / (var_q * var_dp)
        s_info = max(0.0, min(1.0, s_info))

        # Directional buy vs sell estimation
        buy_mask = q > 1e-6
        sell_mask = q < -1e-6

        lambda_buy = 0.0
        lambda_sell = 0.0

        if np.sum(buy_mask) >= 2:
            q_b = q[buy_mask]
            dp_b = dp[buy_mask]
            var_qb = float(np.var(q_b, ddof=1))
            if var_qb > 1e-9:
                cov_qb = float(np.cov(q_b, dp_b)[0, 1])
                lambda_buy = max(0.0, cov_qb / var_qb)

        if np.sum(sell_mask) >= 2:
            q_s = np.abs(q[sell_mask])
            dp_s = np.abs(dp[sell_mask])
            var_qs = float(np.var(q_s, ddof=1))
            if var_qs > 1e-9:
                cov_qs = float(np.cov(q_s, dp_s)[0, 1])
                lambda_sell = max(0.0, cov_qs / var_qs)

        denom = lambda_buy + lambda_sell
        lambda_skew = (lambda_buy - lambda_sell) / denom if denom > 1e-9 else 0.0

        return {
            "lambda": float(kyle_lambda),
            "s_info": float(s_info),
            "lambda_buy": float(lambda_buy),
            "lambda_sell": float(lambda_sell),
            "lambda_skew": float(lambda_skew)
        }

    def evaluate(
        self,
        s_info: float,
        lambda_norm: float,
        lambda_skew: float = 0.0,
        timestamp: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Evaluate Kyle adverse selection metrics and information share.
        """
        now = time.time() if timestamp is None else float(timestamp)

        # Input validations
        if not (0.0 <= s_info <= 1.0):
            raise ValueError(f"s_info must be in [0.0, 1.0], got {s_info}")
        if not (0.0 <= lambda_norm <= 2.0):
            raise ValueError(f"lambda_norm must be in [0.0, 2.0], got {lambda_norm}")
        if not (-1.0 <= lambda_skew <= 1.0):
            raise ValueError(f"lambda_skew must be in [-1.0, 1.0], got {lambda_skew}")

        # Check existing cooldown
        if self.breaker_active:
            elapsed = now - self.breaker_tripped_at
            if elapsed < self.cooldown_sec:
                return {
                    "action": "HALT_ALL",
                    "circuit_breaker": True,
                    "reason": f"COOLDOWN_ACTIVE: {self.last_trip_reason} ({elapsed:.2f}s < {self.cooldown_sec}s)",
                    "s_info": s_info,
                    "lambda_norm": lambda_norm,
                    "lambda_skew": lambda_skew
                }
            else:
                self.breaker_active = False
                self.last_trip_reason = "NONE"

        # 1. Information Share Saturation Breach
        if s_info >= self.max_info_share:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"INFORMATION_SHARE_SATURATION: S_info={s_info:.3f} >= {self.max_info_share:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "s_info": s_info,
                "lambda_norm": lambda_norm,
                "lambda_skew": lambda_skew
            }

        # 2. Kyle Lambda Critical Breaker
        if lambda_norm >= self.critical_lambda_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"KYLE_LAMBDA_CRITICAL: lambda_norm={lambda_norm:.3f} >= {self.critical_lambda_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "s_info": s_info,
                "lambda_norm": lambda_norm,
                "lambda_skew": lambda_skew
            }

        # 3. Directional Asymmetry Protection
        if lambda_skew >= self.lambda_skew_threshold:
            return {
                "action": "BLOCK_BUY",
                "circuit_breaker": False,
                "reason": f"BUY_ADVERSE_SELECTION (lambda_skew={lambda_skew:.2f} >= {self.lambda_skew_threshold:.2f})",
                "s_info": s_info,
                "lambda_norm": lambda_norm,
                "lambda_skew": lambda_skew
            }

        if lambda_skew <= -self.lambda_skew_threshold:
            return {
                "action": "BLOCK_SELL",
                "circuit_breaker": False,
                "reason": f"SELL_ADVERSE_SELECTION (lambda_skew={lambda_skew:.2f} <= -{self.lambda_skew_threshold:.2f})",
                "s_info": s_info,
                "lambda_norm": lambda_norm,
                "lambda_skew": lambda_skew
            }

        return {
            "action": "ALLOW_ALL",
            "circuit_breaker": False,
            "reason": "EQUILIBRIUM_INFORMATION_SHARE",
            "s_info": s_info,
            "lambda_norm": lambda_norm,
            "lambda_skew": lambda_skew
        }
