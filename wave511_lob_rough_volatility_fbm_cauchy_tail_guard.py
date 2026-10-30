"""
Wave 511: High-Frequency Limit Order Book Rough Volatility Fractional Brownian Motion & Cauchy-Lorentz Heavy Tail Singularity Guard
===================================================================================================================================
Institutional Quantitative Mathematical Formulation:
Under Gatheral, Jaisson, and Rosenbaum (2018), Bayer, Friz, and Gatheral (2016), and Bouchaud & Potters (2003):
High-frequency log-volatility behaves not as standard Brownian motion (H = 0.50) nor persistent long-memory,
but as rough fractional Brownian motion (fBm) with Hurst parameter H_vol in (0.05, 0.25):

    E[ |ln sigma(t + Delta) - ln sigma(t)|^q ] ~ C_q * Delta^(q * H_vol)

1. Hyper-Rough Volatility Exponent (H_vol):
   Calm liquid markets maintain H_vol in [0.10, 0.18].
   When H_vol <= min_h_vol_threshold (default: <= 0.08), the volatility field becomes "hyper-rough",
   producing extreme sub-millisecond clustering, jagged spikes, and complete book liquidity evaporation.
   Conversely, when H_vol >= max_h_vol_threshold (default: >= 0.40), anomalous persistent clustering
   indicates macro regime dislocation.

2. Cauchy-Lorentz Heavy Tail Singularity Ratio (R_cauchy):
   Under extreme order book queue drainage, order returns follow a heavy-tailed Cauchy-Lorentz distribution.
   The Cauchy Dispersion Ratio compares the Interquartile Range (IQR) to standard deviation:
       R_cauchy = IQR(Delta x) / (2.0 * max(std(Delta x), 1e-12))
   - For pure Gaussian diffusion: R_cauchy ~ 0.6745.
   - For Cauchy/Lorentz tail singularity: R_cauchy drops significantly (<= 0.35) or explodes (>= 1.40).

3. Composite Rough Volatility Fragility Index (Psi_rough):
       Psi_rough = 0.50 * min(1.0, max(0.0, (0.14 - H_vol) / 0.08))
                 + 0.50 * min(1.0, max(0.0, (abs(R_cauchy - 0.675) - 0.15) / 0.40)) in [0.0, 1.0]

Circuit Breakers:
1. HYPER_ROUGH_VOLATILITY_COLLAPSE: H_vol <= min_h_vol_threshold (default: <= 0.08) or Psi_rough >= critical_fragility_threshold (default: >= 0.70) -> HALT_ALL
2. CAUCHY_TAIL_DISPERSION_CRITICAL: R_cauchy <= min_cauchy_ratio (default: <= 0.35) or R_cauchy >= max_cauchy_ratio (default: >= 1.40) -> HALT_ALL
3. Asymmetric Directional Toxicity Overrides:
   - H_vol <= 0.12 and z_rough >= z_rough_warning_threshold (default: >= 2.20) -> BLOCK_BUY (parabolic rough squeeze)
   - H_vol <= 0.12 and z_rough <= -z_rough_warning_threshold (default: <= -2.20) -> BLOCK_SELL (liquidation rough cascade)
"""

import math
import time
import numpy as np
from typing import List, Dict, Any, Optional


class Wave511LobRoughVolatilityFbmCauchyTailGuard:
    """
    Monitors rough volatility Hurst scaling H_vol and Cauchy-Lorentz heavy-tail dispersion
    to shield institutional high-frequency execution from hyper-rough volatility shocks.
    """

    def __init__(
        self,
        min_h_vol_threshold: float = 0.08,
        max_h_vol_threshold: float = 0.40,
        min_cauchy_ratio: float = 0.35,
        max_cauchy_ratio: float = 1.40,
        critical_fragility_threshold: float = 0.70,
        z_rough_warning_threshold: float = 2.20,
        cooldown_sec: float = 2.0
    ) -> None:
        if not (0.02 <= min_h_vol_threshold <= 0.15):
            raise ValueError(f"min_h_vol_threshold must be in [0.02, 0.15], got {min_h_vol_threshold}")
        if not (0.30 <= max_h_vol_threshold <= 0.70):
            raise ValueError(f"max_h_vol_threshold must be in [0.30, 0.70], got {max_h_vol_threshold}")
        if not (0.15 <= min_cauchy_ratio <= 0.50):
            raise ValueError(f"min_cauchy_ratio must be in [0.15, 0.50], got {min_cauchy_ratio}")
        if not (1.10 <= max_cauchy_ratio <= 2.50):
            raise ValueError(f"max_cauchy_ratio must be in [1.10, 2.50], got {max_cauchy_ratio}")
        if not (0.45 <= critical_fragility_threshold <= 0.90):
            raise ValueError(f"critical_fragility_threshold must be in [0.45, 0.90], got {critical_fragility_threshold}")
        if not (1.20 <= z_rough_warning_threshold <= 3.50):
            raise ValueError(f"z_rough_warning_threshold must be in [1.20, 3.50], got {z_rough_warning_threshold}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.min_h_vol_threshold: float = min_h_vol_threshold
        self.max_h_vol_threshold: float = max_h_vol_threshold
        self.min_cauchy_ratio: float = min_cauchy_ratio
        self.max_cauchy_ratio: float = max_cauchy_ratio
        self.critical_fragility_threshold: float = critical_fragility_threshold
        self.z_rough_warning_threshold: float = z_rough_warning_threshold
        self.cooldown_sec: float = cooldown_sec

        # State tracking
        self.breaker_active: bool = False
        self.breaker_tripped_at: float = 0.0
        self.last_trip_reason: str = "NONE"

    def reset(self) -> None:
        """Reset internal circuit breaker states."""
        self.breaker_active = False
        self.breaker_tripped_at = 0.0
        self.last_trip_reason = "NONE"

    def estimate_roughness_and_cauchy(
        self,
        log_vol_series: List[float],
        return_increments: List[float]
    ) -> Dict[str, float]:
        """
        Estimates rough volatility Hurst parameter H_vol and Cauchy dispersion ratio R_cauchy.
        """
        if len(log_vol_series) < 16:
            raise ValueError(f"Must provide at least 16 log-volatility points, got {len(log_vol_series)}")
        if len(return_increments) < 16:
            raise ValueError(f"Must provide at least 16 return increments, got {len(return_increments)}")

        lv = np.array(log_vol_series, dtype=np.float64)
        lags = [1, 2, 4, 8]
        m_q = []
        for lag in lags:
            diffs = np.abs(lv[lag:] - lv[:-lag])
            m_q.append(np.mean(diffs ** 2))

        log_lags = np.log(lags)
        log_m = np.log(np.maximum(m_q, 1e-12))
        slope = float(np.polyfit(log_lags, log_m, 1)[0])
        h_vol = float(np.clip(slope / 2.0, 0.02, 0.65))

        rets = np.array(return_increments, dtype=np.float64)
        q75, q25 = np.percentile(rets, [75, 25])
        iqr = float(q75 - q25)
        std_ret = float(np.std(rets, ddof=1)) if len(rets) > 1 else 1.0
        r_cauchy = float(np.clip(iqr / (2.0 * max(std_ret, 1e-12)), 0.01, 3.0))

        return {
            "h_vol": h_vol,
            "r_cauchy": r_cauchy
        }

    def evaluate(
        self,
        h_vol: float,
        r_cauchy: float = 0.675,
        z_rough: float = 0.0,
        timestamp: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Evaluates rough volatility Hurst exponent, Cauchy dispersion ratio, and directional tail risk.
        """
        now = time.time() if timestamp is None else float(timestamp)

        # Input validations
        if not (0.01 <= h_vol <= 1.0):
            raise ValueError(f"h_vol must be in [0.01, 1.0], got {h_vol}")
        if not (0.01 <= r_cauchy <= 5.0):
            raise ValueError(f"r_cauchy must be in [0.01, 5.0], got {r_cauchy}")
        if not (-10.0 <= z_rough <= 10.0):
            raise ValueError(f"z_rough must be in [-10.0, 10.0], got {z_rough}")

        # Check existing cooldown
        if self.breaker_active:
            elapsed = now - self.breaker_tripped_at
            if elapsed < self.cooldown_sec:
                return {
                    "action": "HALT_ALL",
                    "circuit_breaker": True,
                    "reason": f"COOLDOWN_ACTIVE: {self.last_trip_reason} ({elapsed:.2f}s < {self.cooldown_sec}s)",
                    "h_vol": h_vol,
                    "r_cauchy": r_cauchy,
                    "z_rough": z_rough,
                    "psi_rough": 1.0
                }
            else:
                self.breaker_active = False
                self.last_trip_reason = "NONE"

        # Calculate composite fragility index Psi_rough in [0.0, 1.0]
        phi_h = min(1.0, max(0.0, (0.14 - h_vol) / 0.08))
        phi_cauchy = min(1.0, max(0.0, (abs(r_cauchy - 0.675) - 0.15) / 0.40))
        psi_rough = float(np.clip(0.50 * phi_h + 0.50 * phi_cauchy, 0.0, 1.0))

        # 1. Hyper-Rough Volatility Collapse Breaker
        if h_vol <= self.min_h_vol_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"HYPER_ROUGH_VOLATILITY_COLLAPSE: h_vol={h_vol:.3f} <= {self.min_h_vol_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "h_vol": h_vol,
                "r_cauchy": r_cauchy,
                "z_rough": z_rough,
                "psi_rough": psi_rough
            }

        if psi_rough >= self.critical_fragility_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"ROUGH_VOLATILITY_FRAGILITY_CRITICAL: psi_rough={psi_rough:.3f} >= {self.critical_fragility_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "h_vol": h_vol,
                "r_cauchy": r_cauchy,
                "z_rough": z_rough,
                "psi_rough": psi_rough
            }

        # 2. Cauchy Tail Dispersion Breaker
        if r_cauchy <= self.min_cauchy_ratio:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"CAUCHY_TAIL_COMPRESSION_COLLAPSE: r_cauchy={r_cauchy:.3f} <= {self.min_cauchy_ratio:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "h_vol": h_vol,
                "r_cauchy": r_cauchy,
                "z_rough": z_rough,
                "psi_rough": psi_rough
            }

        if r_cauchy >= self.max_cauchy_ratio:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"CAUCHY_TAIL_DISPERSION_BLOWOUT: r_cauchy={r_cauchy:.3f} >= {self.max_cauchy_ratio:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "h_vol": h_vol,
                "r_cauchy": r_cauchy,
                "z_rough": z_rough,
                "psi_rough": psi_rough
            }

        # 3. Asymmetric Directional Rough Volatility Overextensions
        if h_vol <= 0.12 and z_rough >= self.z_rough_warning_threshold:
            return {
                "action": "BLOCK_BUY",
                "circuit_breaker": False,
                "reason": f"PARABOLIC_ROUGH_VOLATILITY_SQUEEZE: h_vol={h_vol:.2f} <= 0.12 and z_rough={z_rough:.2f} >= {self.z_rough_warning_threshold:.2f}",
                "h_vol": h_vol,
                "r_cauchy": r_cauchy,
                "z_rough": z_rough,
                "psi_rough": psi_rough
            }

        if h_vol <= 0.12 and z_rough <= -self.z_rough_warning_threshold:
            return {
                "action": "BLOCK_SELL",
                "circuit_breaker": False,
                "reason": f"LIQUIDATION_ROUGH_VOLATILITY_CASCADE: h_vol={h_vol:.2f} <= 0.12 and z_rough={z_rough:.2f} <= -{self.z_rough_warning_threshold:.2f}",
                "h_vol": h_vol,
                "r_cauchy": r_cauchy,
                "z_rough": z_rough,
                "psi_rough": psi_rough
            }

        return {
            "action": "ALLOW_ALL",
            "circuit_breaker": False,
            "reason": "ROUGH_VOLATILITY_EQUILIBRIUM_SECURE",
            "h_vol": h_vol,
            "r_cauchy": r_cauchy,
            "z_rough": z_rough,
            "psi_rough": psi_rough
        }
