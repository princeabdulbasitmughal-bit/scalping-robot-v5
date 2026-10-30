"""
Wave 467: Cross-Asset Order Flow Spillover & Lead-Lag Spillover Guard
=====================================================================
Institutional Quantitative Mathematical Formulation:
Under Engle (2002) "Dynamic Conditional Correlation", Fleming, Kirby & Ostdiek (1998),
and Kodres & Pritsker (2002) "A Theory of Contagion Through Cross-Market Rebalancing",
order flow shocks originating in a leading macro correlated proxy (e.g. DXY, US10Y, EURUSD)
spill over into the primary trading instrument (e.g. Spot Gold XAUUSD) via latency lead-lag.

Let F_lead(t) be the signed order flow or return impulse of the leading cross-asset proxy,
and r(t) be the target asset log-return.
Across a rolling window of N observations:
1. Dynamic Cross-Asset Sensitivity (Correlation & Beta):
    rho_cross = Cov(r, F_lead) / (sigma_r * sigma_F + epsilon)
    beta_cross = Cov(r, F_lead) / (Var(F_lead) + epsilon)

2. Standardized Cross-Asset Impulse Z-Score:
    Z_F = (F_lead(t) - mu_F) / max(sigma_F, 1e-4)

3. Dimensionless Cross-Asset Spillover Pressure:
    Psi(t) = rho_cross * Z_F

In normal decoupled or balanced conditions:
- Cross-asset spillover pressure is mild: |Psi(t)| < 1.0.
- Order flow in the target asset is driven primarily by its own intrinsic order book dynamics.

Pathological Regimes:
1. Toxic Macro Spillover Surge:
   |Psi(t)| > max_spillover_pressure (default: > 2.00) and |rho_cross| > min_correlation (default: > 0.20)
   An aggressive foreign order flow cascade has hit the lead asset and is actively spilling
   over into target liquidity before local quotes reprice.
2. Cross-Asset Directional Adverse Selection:
   Psi(t) > max_spillover_pressure: Foreign aggressive buying surge -> Shorting is toxic (Block SELL)
   Psi(t) < -max_spillover_pressure: Foreign aggressive selling surge -> Longs are toxic (Block BUY)

When cross-asset spillover pressure breaches institutional thresholds, the guard freezes
vulnerable order submissions on the adverse side until foreign flow stabilizes.
"""

import math
import numpy as np
from typing import List, Dict, Any, Optional


class Wave467CrossAssetFlowSpilloverGuard:
    """
    Evaluates cross-asset lead-lag order flow spillover pressure Psi(t) and dynamic correlation
    to protect against foreign macro cascades and cross-market adverse selection.
    """

    def __init__(
        self,
        window_size: int = 30,
        max_spillover_pressure: float = 2.00,
        min_correlation_significance: float = 0.20,
        min_samples: int = 10,
        cooldown_sec: float = 2.0
    ) -> None:
        if window_size < 15:
            raise ValueError(f"window_size must be >= 15, got {window_size}")
        if max_spillover_pressure <= 0.50:
            raise ValueError(f"max_spillover_pressure must be > 0.50, got {max_spillover_pressure}")
        if not (0.05 <= min_correlation_significance <= 0.90):
            raise ValueError(f"min_correlation_significance must be in [0.05, 0.90], got {min_correlation_significance}")
        if min_samples < 8:
            raise ValueError(f"min_samples must be >= 8, got {min_samples}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.window_size: int = window_size
        self.max_spillover_pressure: float = max_spillover_pressure
        self.min_correlation_significance: float = min_correlation_significance
        self.min_samples: int = min_samples
        self.cooldown_sec: float = cooldown_sec

        # Ring buffers: target returns, lead flow impulses, timestamps
        self._target_returns: List[float] = []
        self._lead_flows: List[float] = []
        self._timestamps: List[float] = []

        # State telemetry
        self.correlation_cross: float = 0.0
        self.beta_cross: float = 0.0
        self.spillover_pressure: float = 0.0
        self.target_sigma: float = 0.0
        self.blocked_side: Optional[str] = None
        self._is_blocked: bool = False
        self._block_reason: str = ""
        self._last_breach_time: float = -1.0

    def update(self, target_return: float, lead_flow: float, timestamp: float) -> bool:
        """
        Record discrete target asset return and leading cross-asset flow impulse.
        Returns True if trading is blocked, False otherwise.
        """
        for val, name in [(target_return, "target_return"), (lead_flow, "lead_flow")]:
            if not math.isfinite(val):
                raise ValueError(f"{name} must be finite, got {val}")

        if not math.isfinite(timestamp):
            raise ValueError(f"timestamp must be finite, got {timestamp}")
        if self._timestamps and timestamp <= self._timestamps[-1]:
            raise ValueError(f"timestamp must be strictly monotonic. Got {timestamp} <= {self._timestamps[-1]}")

        self._target_returns.append(float(target_return))
        self._lead_flows.append(float(lead_flow))
        self._timestamps.append(float(timestamp))

        # Maintain window size
        if len(self._target_returns) > self.window_size:
            self._target_returns.pop(0)
            self._lead_flows.pop(0)
            self._timestamps.pop(0)

        # Check cooldown
        if self._last_breach_time > 0 and (timestamp - self._last_breach_time) < self.cooldown_sec:
            self._is_blocked = True
            return True

        if len(self._target_returns) < self.min_samples:
            self._is_blocked = False
            self._block_reason = "INSUFFICIENT_SAMPLES"
            self.blocked_side = None
            return False

        r_arr = np.array(self._target_returns, dtype=np.float64)
        f_arr = np.array(self._lead_flows, dtype=np.float64)

        self.target_sigma = float(max(np.std(r_arr), 1e-6))
        f_sigma = float(max(np.std(f_arr), 1e-6))
        f_mean = float(np.mean(f_arr))

        # Correlation and Beta
        cov_matrix = np.cov(r_arr, f_arr)
        cov_rf = float(cov_matrix[0, 1])
        var_f = float(cov_matrix[1, 1])

        self.correlation_cross = float(cov_rf / (self.target_sigma * f_sigma))
        self.beta_cross = float(cov_rf / max(var_f, 1e-8))

        # Standardized cross-asset impulse Z-score
        latest_lead = self._lead_flows[-1]
        z_f = float((latest_lead - f_mean) / f_sigma)

        # Instantaneous Dimensionless Cross-Asset Spillover Pressure
        self.spillover_pressure = float(self.correlation_cross * z_f)

        # Evaluate Circuit Breaker
        significant_corr = abs(self.correlation_cross) > self.min_correlation_significance
        pressure_surge = abs(self.spillover_pressure) > self.max_spillover_pressure

        if significant_corr and pressure_surge:
            self._is_blocked = True
            self._last_breach_time = timestamp

            # Determine toxic adverse direction
            if self.spillover_pressure > 0:
                self.blocked_side = "SELL" # Upward foreign pressure -> shorting is adverse
            else:
                self.blocked_side = "BUY"  # Downward foreign pressure -> buying is adverse

            self._block_reason = (
                f"CROSS_ASSET_SPILLOVER_SURGE: Psi={self.spillover_pressure:.2f} > "
                f"threshold {self.max_spillover_pressure:.2f} (rho={self.correlation_cross:.3f}, blocked: {self.blocked_side})"
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
        """OmniTrade interface compatibility. Checks if a specific order side is blocked."""
        if not self._is_blocked:
            return False
        if self.blocked_side in ("ALL", None):
            return True
        return side.upper() == self.blocked_side

    @property
    def block_reason(self) -> str:
        return self._block_reason

    def get_telemetry(self) -> Dict[str, Any]:
        """Telemetry metadata for institutional risk auditing."""
        return {
            "guard": "Wave467CrossAssetFlowSpilloverGuard",
            "correlation_cross": round(self.correlation_cross, 4),
            "beta_cross": round(self.beta_cross, 4),
            "spillover_pressure": round(self.spillover_pressure, 4),
            "target_sigma": round(self.target_sigma, 6),
            "max_spillover_pressure": self.max_spillover_pressure,
            "blocked_side": self.blocked_side,
            "is_blocked": self._is_blocked,
            "block_reason": self._block_reason,
            "sample_size": len(self._target_returns)
        }

    def reset(self) -> None:
        """Reset internal buffers and state."""
        self._target_returns.clear()
        self._lead_flows.clear()
        self._timestamps.clear()
        self.correlation_cross = 0.0
        self.beta_cross = 0.0
        self.spillover_pressure = 0.0
        self.target_sigma = 0.0
        self.blocked_side = None
        self._is_blocked = False
        self._block_reason = ""
        self._last_breach_time = -1.0
