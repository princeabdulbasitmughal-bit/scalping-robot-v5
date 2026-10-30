"""
Wave 505: High-Frequency Limit Order Book Fractionally Integrated Autoregressive Noise & Long-Memory Liquidity Hurst Exponent Guard
==================================================================================================================================
Institutional Quantitative Mathematical Formulation:
Under Granger & Joyeux (1980), Hosking (1981), and Bouchaud, Gefen, Potters & Wyart (2004),
order book flow signs and depth replenishment exhibit fractional integration and long-range memory:

1. Fractional Differencing Operator (1 - L)^d:
   d in (-0.50, 0.50) with Hurst exponent H = d + 0.50 in (0.0, 1.0):
       H ~ 0.50: Standard uncorrelated Brownian diffusion (efficient quoting).
       H > 0.75: Strong long-memory persistence (institutional execution herd runaway).
       H < 0.35: Hyper-anti-persistent mean-reversion jitter (quote stuffing / pinging).

2. Rescaled Range (R/S) Hurst Exponent Estimation:
   Given time series X of length N >= 10:
       Y_t = sum_{i=1}^t (X_i - mean(X))
       R = max(Y) - min(Y)
       S = std(X)
       (R/S) ~ c * N^H  =>  H_hurst = ln(R / max(S, 1e-12)) / ln(N)  (clamped to [0.05, 0.98])
       d_frac = H_hurst - 0.50 in [-0.45, 0.48]

3. Composite Long-Memory Fragility Index (Psi_memory):
       Psi_memory = 0.50 * min(1.0, max(0.0, (abs(H_hurst - 0.50) - 0.15) / 0.20))
                  + 0.50 * min(1.0, max(0.0, (abs(d_frac) - 0.15) / 0.25)) in [0.0, 1.0]

Circuit Breakers:
1. LONG_MEMORY_HERD_RUNAWAY: H_hurst >= max_hurst_threshold (default: >= 0.78) or Psi_memory >= critical_fragility_threshold (default: >= 0.70) -> HALT_ALL
2. HYPER_ANTIPERSISTENT_JITTER: H_hurst <= min_hurst_threshold (default: <= 0.28) -> HALT_ALL
3. Asymmetric Directional Memory Overextensions:
   - Z_memory >= z_memory_warning_threshold (default: >= 2.50) -> BLOCK_BUY
   - Z_memory <= -z_memory_warning_threshold (default: <= -2.50) -> BLOCK_SELL
"""

import math
import time
import numpy as np
from typing import List, Dict, Any, Optional


class Wave505LobArfimaLongMemoryHurstGuard:
    """
    Monitors fractional integration parameters, Rescaled Range Hurst exponents,
    and long-memory adverse selection herd runaways in high-frequency order books.
    """

    def __init__(
        self,
        max_hurst_threshold: float = 0.78,
        min_hurst_threshold: float = 0.28,
        critical_fragility_threshold: float = 0.70,
        z_memory_warning_threshold: float = 2.50,
        cooldown_sec: float = 2.0
    ) -> None:
        if not (0.65 <= max_hurst_threshold <= 0.95):
            raise ValueError(f"max_hurst_threshold must be in [0.65, 0.95], got {max_hurst_threshold}")
        if not (0.15 <= min_hurst_threshold <= 0.40):
            raise ValueError(f"min_hurst_threshold must be in [0.15, 0.40], got {min_hurst_threshold}")
        if min_hurst_threshold >= max_hurst_threshold:
            raise ValueError("min_hurst_threshold must be strictly less than max_hurst_threshold")
        if not (0.45 <= critical_fragility_threshold <= 0.90):
            raise ValueError(f"critical_fragility_threshold must be in [0.45, 0.90], got {critical_fragility_threshold}")
        if not (1.80 <= z_memory_warning_threshold <= 3.50):
            raise ValueError(f"z_memory_warning_threshold must be in [1.80, 3.50], got {z_memory_warning_threshold}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.max_hurst_threshold: float = max_hurst_threshold
        self.min_hurst_threshold: float = min_hurst_threshold
        self.critical_fragility_threshold: float = critical_fragility_threshold
        self.z_memory_warning_threshold: float = z_memory_warning_threshold
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

    def estimate_hurst_rs(
        self,
        series: List[float]
    ) -> Dict[str, float]:
        """
        Estimates the Hurst exponent H and fractional parameter d via Rescaled Range (R/S) analysis.
        """
        if len(series) < 10:
            raise ValueError(f"Must provide at least 10 observations for R/S analysis, got {len(series)}")

        x = np.array(series, dtype=np.float64)
        n = len(x)
        mean_x = float(np.mean(x))
        std_x = float(np.std(x, ddof=1))

        if std_x <= 1e-9:
            return {"h_hurst": 0.50, "d_frac": 0.0, "rs_ratio": 1.0}

        dev = x - mean_x
        cum_dev = np.cumsum(dev)
        r = float(np.max(cum_dev) - np.min(cum_dev))
        rs = r / std_x

        if rs <= 1e-12:
            return {"h_hurst": 0.50, "d_frac": 0.0, "rs_ratio": 1.0}

        # Estimate H = ln(R/S) / ln(N)
        h_est = math.log(max(rs, 1e-9)) / math.log(n)
        h_hurst = float(np.clip(h_est, 0.05, 0.98))
        d_frac = float(h_hurst - 0.50)

        return {
            "h_hurst": h_hurst,
            "d_frac": d_frac,
            "rs_ratio": rs
        }

    def evaluate(
        self,
        h_hurst: float,
        d_frac: Optional[float] = None,
        z_memory: float = 0.0,
        timestamp: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Evaluates long-memory persistence, hyper-anti-persistence, and directional overextension.
        """
        now = time.time() if timestamp is None else float(timestamp)

        # Input validations
        if not (0.0 <= h_hurst <= 1.0):
            raise ValueError(f"h_hurst must be in [0.0, 1.0], got {h_hurst}")
        if not (-10.0 <= z_memory <= 10.0):
            raise ValueError(f"z_memory must be in [-10.0, 10.0], got {z_memory}")

        d = h_hurst - 0.50 if d_frac is None else float(d_frac)

        # Check existing cooldown
        if self.breaker_active:
            elapsed = now - self.breaker_tripped_at
            if elapsed < self.cooldown_sec:
                return {
                    "action": "HALT_ALL",
                    "circuit_breaker": True,
                    "reason": f"COOLDOWN_ACTIVE: {self.last_trip_reason} ({elapsed:.2f}s < {self.cooldown_sec}s)",
                    "h_hurst": h_hurst,
                    "d_frac": d,
                    "psi_memory": 1.0,
                    "z_memory": z_memory
                }
            else:
                self.breaker_active = False
                self.last_trip_reason = "NONE"

        # Calculate composite memory fragility index Psi_memory in [0.0, 1.0]
        dev_h = abs(h_hurst - 0.50)
        phi_h = min(1.0, max(0.0, (dev_h - 0.15) / 0.20))
        phi_d = min(1.0, max(0.0, (abs(d) - 0.15) / 0.25))
        psi_memory = float(np.clip(0.50 * phi_h + 0.50 * phi_d, 0.0, 1.0))

        # 1. Critical Long-Memory Herd Runaway Breaker
        if h_hurst >= self.max_hurst_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"LONG_MEMORY_HERD_RUNAWAY: h_hurst={h_hurst:.3f} >= {self.max_hurst_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "h_hurst": h_hurst,
                "d_frac": d,
                "psi_memory": psi_memory,
                "z_memory": z_memory
            }

        if psi_memory >= self.critical_fragility_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"MEMORY_FRAGILITY_CRITICAL: psi_memory={psi_memory:.3f} >= {self.critical_fragility_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "h_hurst": h_hurst,
                "d_frac": d,
                "psi_memory": psi_memory,
                "z_memory": z_memory
            }

        # 2. Hyper-Anti-Persistent Microstructural Jitter Breaker
        if h_hurst <= self.min_hurst_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"HYPER_ANTIPERSISTENT_JITTER: h_hurst={h_hurst:.3f} <= {self.min_hurst_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "h_hurst": h_hurst,
                "d_frac": d,
                "psi_memory": psi_memory,
                "z_memory": z_memory
            }

        # 3. Asymmetric Directional Memory Overextensions
        if z_memory >= self.z_memory_warning_threshold:
            return {
                "action": "BLOCK_BUY",
                "circuit_breaker": False,
                "reason": f"LONG_MEMORY_UPWARD_OVEREXTENSION: z_memory={z_memory:.2f} >= {self.z_memory_warning_threshold:.2f}",
                "h_hurst": h_hurst,
                "d_frac": d,
                "psi_memory": psi_memory,
                "z_memory": z_memory
            }

        if z_memory <= -self.z_memory_warning_threshold:
            return {
                "action": "BLOCK_SELL",
                "circuit_breaker": False,
                "reason": f"LONG_MEMORY_DOWNWARD_OVEREXTENSION: z_memory={z_memory:.2f} <= -{self.z_memory_warning_threshold:.2f}",
                "h_hurst": h_hurst,
                "d_frac": d,
                "psi_memory": psi_memory,
                "z_memory": z_memory
            }

        return {
            "action": "ALLOW_ALL",
            "circuit_breaker": False,
            "reason": "EQUILIBRIUM_MEMORYLESS_ACTIVE",
            "h_hurst": h_hurst,
            "d_frac": d,
            "psi_memory": psi_memory,
            "z_memory": z_memory
        }
