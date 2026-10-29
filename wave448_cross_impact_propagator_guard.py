"""
Wave 448: Multi-Asset Cross-Impact Propagator Guard
==================================================
Institutional Quantitative Mathematical Formulation:
Under Hasbrouck (1991) and Eisler, Bouchaud & Kockelkoren (2012) "The Models of Cross-Impact",
correlated order flows across cross-margined venues and sister assets (e.g. XAUUSD vs XAGUSD or DXY)
propagate non-local price impact through the cross-impact matrix Lambda:
    r_i(t) = sum_j Lambda_ij * Omega_j(t) + eta_i(t)

Where:
- r_i(t) is the midprice log-return of primary asset i (e.g. XAUUSD).
- Omega_j(t) is the signed trade volume flow of correlated asset j.
- Lambda_ij is the cross-impact propagator coefficient:
      Lambda_ij = Cov(r_i, Omega_j) / Var(Omega_j)

When cross-asset contagion drives endogenous returns, the cross-impact spillover ratio:
    chi_spillover = |Lambda_ij * Omega_j(t)| / max(sigma_i(t), epsilon)
exceeds institutional thresholds (e.g. > 2.0x local volatility), indicating that the primary
order book is being violently re-priced by foreign order flow contagion rather than native liquidity.

The guard computes real-time rolling OLS cross-impact Lambda_ij and blocks execution when
foreign spillover exceeds safe absorption capacity.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave448CrossImpactPropagatorGuard:
    """
    Evaluates cross-asset order flow contagion and cross-impact propagation Lambda_ij
    to guard against exogenous liquidity shocks and proxy-flow predatory front-running.
    """

    def __init__(
        self,
        window_size: int = 30,
        max_spillover_ratio: float = 2.20,
        min_samples_for_ols: int = 12
    ) -> None:
        if window_size < 15:
            raise ValueError(f"window_size must be >= 15, got {window_size}")
        if max_spillover_ratio <= 0.50:
            raise ValueError(f"max_spillover_ratio must be > 0.50, got {max_spillover_ratio}")

        self.window_size: int = window_size
        self.max_spillover_ratio: float = max_spillover_ratio
        self.min_samples_for_ols: int = min_samples_for_ols

        # Ring buffers: returns r_i, correlated flows Omega_j, timestamps
        self._returns: List[float] = []
        self._correlated_flows: List[float] = []
        self._timestamps: List[float] = []

        # State outputs
        self.cross_impact_lambda: float = 0.0
        self.spillover_ratio: float = 0.0
        self._is_blocked: bool = False
        self._block_reason: str = ""

    def update(self, primary_return: float, correlated_order_flow: float, timestamp: float) -> bool:
        """
        Record a synchronized observation of primary asset log-return and correlated sister order flow.
        Returns True if trading is blocked, False otherwise.
        """
        if not math.isfinite(primary_return) or not math.isfinite(correlated_order_flow):
            raise ValueError("primary_return and correlated_order_flow must be finite")
        if self._timestamps and timestamp <= self._timestamps[-1]:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._timestamps[-1]}")

        self._returns.append(float(primary_return))
        self._correlated_flows.append(float(correlated_order_flow))
        self._timestamps.append(float(timestamp))

        if len(self._returns) > self.window_size:
            self._returns.pop(0)
            self._correlated_flows.pop(0)
            self._timestamps.pop(0)

        if len(self._returns) < self.min_samples_for_ols:
            self._is_blocked = False
            self._block_reason = "INSUFFICIENT_SAMPLE"
            return False

        r_arr = np.array(self._returns, dtype=np.float64)
        w_arr = np.array(self._correlated_flows, dtype=np.float64)

        var_w = np.var(w_arr)
        std_r = np.std(r_arr)

        if var_w < 1e-12 or std_r < 1e-12:
            self.cross_impact_lambda = 0.0
            self.spillover_ratio = 0.0
            self._is_blocked = False
            self._block_reason = ""
            return False

        cov_rw = np.cov(r_arr, w_arr)[0, 1]
        self.cross_impact_lambda = float(cov_rw / var_w)

        # Current predicted cross-impact on latest flow
        latest_flow = self._correlated_flows[-1]
        predicted_cross_impact = abs(self.cross_impact_lambda * latest_flow)
        self.spillover_ratio = float(predicted_cross_impact / max(std_r, 1e-8))

        if self.spillover_ratio > self.max_spillover_ratio:
            self._is_blocked = True
            self._block_reason = (
                f"EXOGENOUS_CROSS_IMPACT_SPILLOVER: Spillover ratio {self.spillover_ratio:.2f}x > "
                f"threshold {self.max_spillover_ratio:.2f}x (Lambda={self.cross_impact_lambda:.4e})"
            )
        else:
            self._is_blocked = False
            self._block_reason = ""

        return self._is_blocked

    def is_blocked(self) -> bool:
        """Returns True if trading is blocked by the Cross-Impact Propagator Guard."""
        return self._is_blocked

    def is_entry_blocked(self, side: str = "BUY") -> bool:
        """OmniTrade interface compatibility."""
        return self._is_blocked

    @property
    def block_reason(self) -> str:
        return self._block_reason

    def get_telemetry(self) -> Dict[str, Any]:
        """Telemetry metadata for institutional risk auditing."""
        return {
            "guard": "Wave448CrossImpactPropagatorGuard",
            "cross_impact_lambda": round(self.cross_impact_lambda, 6),
            "spillover_ratio": round(self.spillover_ratio, 4),
            "max_spillover_ratio": self.max_spillover_ratio,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason,
            "sample_size": len(self._returns)
        }

    def reset(self) -> None:
        """Reset internal buffer state."""
        self._returns.clear()
        self._correlated_flows.clear()
        self._timestamps.clear()
        self.cross_impact_lambda = 0.0
        self.spillover_ratio = 0.0
        self._is_blocked = False
        self._block_reason = ""
