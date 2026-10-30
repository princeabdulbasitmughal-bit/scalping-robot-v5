"""
Wave 501: High-Frequency Limit Order Book Multi-Scale Wavelet Variance Decomposition & Transient Liquidity Singularity Guard
==========================================================================================================================
Institutional Quantitative Mathematical Formulation:
Under Percival & Walden (2000), Gençay, Selçuk & Whitcher (2001), and Mallat (1999),
order book depth and midprice variations exhibit multi-scale spectral phenomena across
distinct temporal horizons:
    Scale j = 1 (ultra-high frequency, 1-2 ticks): microstructural bouncing and jitter noise.
    Scale j = 2 (short horizon, 4-8 ticks): local liquidity replenishment.
    Scale j = 3 (intermediate horizon, 16-32 ticks): informed algorithmic inventory rebalancing.

1. Discrete Wavelet Haar Multi-Scale Detail Decomposition:
   Given time series X = [x_1, ..., x_N] with N >= 8:
       d_{1, k} = (x_{2k} - x_{2k-1}) / sqrt(2)
       s_{1, k} = (x_{2k} + x_{2k-1}) / sqrt(2)
       d_{2, k} = (s_{1, 2k} - s_{1, 2k-1}) / sqrt(2)
       s_{2, k} = (s_{1, 2k} + s_{1, 2k-1}) / sqrt(2)
       d_{3, k} = (s_{2, 2k} - s_{2, 2k-1}) / sqrt(2)

   Scale Wavelet Variances:
       sigma^2(j) = (1 / N_j) * sum_{k=1}^{N_j} (d_{j, k})^2

2. Ultra-High Frequency Noise Ratio (R_wavelet):
       R_wavelet = sigma^2(1) / max(sigma^2(1) + sigma^2(2) + sigma^2(3), 1e-12) in [0.0, 1.0]

3. Hölder Singularity Exponent (H_singularity):
   Estimated via log-scale linear regression:
       log2(sigma^2(j)) = slope * j + intercept
       H_singularity = (slope - 1.0) / 2.0  (clamped to [0.0, 1.0])

4. Composite Wavelet Fragility Index (Psi_wavelet):
       Psi_wavelet = 0.50 * min(1.0, max(0.0, (R_wavelet - 0.50) / 0.35))
                   + 0.50 * min(1.0, max(0.0, (0.45 - H_singularity) / 0.30)) in [0.0, 1.0]

Circuit Breakers:
1. WAVELET_NOISE_SINGULARITY: R_wavelet >= max_noise_ratio_threshold (default: >= 0.75) or Psi_wavelet >= critical_fragility_threshold (default: >= 0.70) -> HALT_ALL
2. HOLDER_REGULARITY_BREAKDOWN: H_singularity <= min_holder_threshold (default: <= 0.20) and R_wavelet >= 0.40 -> HALT_ALL
3. Asymmetric Directional Wavelet Overextension:
   - Z_wavelet >= z_wavelet_warning_threshold (default: >= 2.50) -> BLOCK_BUY
   - Z_wavelet <= -z_wavelet_warning_threshold (default: <= -2.50) -> BLOCK_SELL
"""

import math
import time
import numpy as np
from typing import List, Dict, Any, Optional


class Wave501LobWaveletVarianceSingularityGuard:
    """
    Monitors multi-scale wavelet detail variance ratios, Hölder singularity exponents,
    and instantaneous microstructural liquidity noise cascades.
    """

    def __init__(
        self,
        max_noise_ratio_threshold: float = 0.75,
        min_holder_threshold: float = 0.20,
        critical_fragility_threshold: float = 0.70,
        z_wavelet_warning_threshold: float = 2.50,
        cooldown_sec: float = 2.0
    ) -> None:
        if not (0.55 <= max_noise_ratio_threshold <= 0.95):
            raise ValueError(f"max_noise_ratio_threshold must be in [0.55, 0.95], got {max_noise_ratio_threshold}")
        if not (0.10 <= min_holder_threshold <= 0.40):
            raise ValueError(f"min_holder_threshold must be in [0.10, 0.40], got {min_holder_threshold}")
        if not (0.45 <= critical_fragility_threshold <= 0.90):
            raise ValueError(f"critical_fragility_threshold must be in [0.45, 0.90], got {critical_fragility_threshold}")
        if not (1.80 <= z_wavelet_warning_threshold <= 3.50):
            raise ValueError(f"z_wavelet_warning_threshold must be in [1.80, 3.50], got {z_wavelet_warning_threshold}")
        if cooldown_sec < 0.1:
            raise ValueError(f"cooldown_sec must be >= 0.1, got {cooldown_sec}")

        self.max_noise_ratio_threshold: float = max_noise_ratio_threshold
        self.min_holder_threshold: float = min_holder_threshold
        self.critical_fragility_threshold: float = critical_fragility_threshold
        self.z_wavelet_warning_threshold: float = z_wavelet_warning_threshold
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

    def decompose_wavelet_variances(
        self,
        series: List[float]
    ) -> Dict[str, float]:
        """
        Computes 3-scale Haar wavelet detail variances sigma^2(1), sigma^2(2), sigma^2(3),
        noise ratio R_wavelet, and estimated Hölder exponent.
        """
        if len(series) < 8:
            raise ValueError(f"Must provide at least 8 observations for 3-scale wavelet decomposition, got {len(series)}")

        x = np.array(series, dtype=np.float64)
        n = len(x)

        # Scale 1 Haar decomposition
        n1 = (n // 2) * 2
        d1 = (x[1:n1:2] - x[0:n1:2]) / np.sqrt(2.0)
        s1 = (x[1:n1:2] + x[0:n1:2]) / np.sqrt(2.0)

        # Scale 2 Haar decomposition
        n2 = (len(s1) // 2) * 2
        d2 = (s1[1:n2:2] - s1[0:n2:2]) / np.sqrt(2.0)
        s2 = (s1[1:n2:2] + s1[0:n2:2]) / np.sqrt(2.0)

        # Scale 3 Haar decomposition
        n3 = (len(s2) // 2) * 2
        d3 = (s2[1:n3:2] - s2[0:n3:2]) / np.sqrt(2.0)

        var1 = float(np.mean(d1 ** 2)) if len(d1) > 0 else 0.0
        var2 = float(np.mean(d2 ** 2)) if len(d2) > 0 else 0.0
        var3 = float(np.mean(d3 ** 2)) if len(d3) > 0 else 0.0

        total_var = var1 + var2 + var3
        if total_var > 1e-12:
            r_wavelet = float(np.clip(var1 / total_var, 0.0, 1.0))
        else:
            r_wavelet = 0.3333

        # Estimate Hölder exponent from log2(variance) vs scale j in [1, 2, 3]
        log_vars = np.array([
            math.log2(max(var1, 1e-9)),
            math.log2(max(var2, 1e-9)),
            math.log2(max(var3, 1e-9))
        ])
        scales = np.array([1.0, 2.0, 3.0])
        slope, _ = np.polyfit(scales, log_vars, deg=1)

        # Normal Brownian diffusion has slope around 2.0 -> H ~ 0.50
        holder = float(np.clip((slope - 1.0) / 2.0, 0.0, 1.0))

        return {
            "var1": var1,
            "var2": var2,
            "var3": var3,
            "r_wavelet": r_wavelet,
            "h_singularity": holder
        }

    def evaluate(
        self,
        r_wavelet: float,
        h_singularity: float,
        z_wavelet: float = 0.0,
        timestamp: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Evaluates multi-scale wavelet noise ratio, Hölder regularity, and directional singularity.
        """
        now = time.time() if timestamp is None else float(timestamp)

        # Input validations
        if not (0.0 <= r_wavelet <= 1.0):
            raise ValueError(f"r_wavelet must be in [0.0, 1.0], got {r_wavelet}")
        if not (0.0 <= h_singularity <= 1.0):
            raise ValueError(f"h_singularity must be in [0.0, 1.0], got {h_singularity}")
        if not (-10.0 <= z_wavelet <= 10.0):
            raise ValueError(f"z_wavelet must be in [-10.0, 10.0], got {z_wavelet}")

        # Check existing cooldown
        if self.breaker_active:
            elapsed = now - self.breaker_tripped_at
            if elapsed < self.cooldown_sec:
                return {
                    "action": "HALT_ALL",
                    "circuit_breaker": True,
                    "reason": f"COOLDOWN_ACTIVE: {self.last_trip_reason} ({elapsed:.2f}s < {self.cooldown_sec}s)",
                    "r_wavelet": r_wavelet,
                    "h_singularity": h_singularity,
                    "psi_wavelet": 1.0,
                    "z_wavelet": z_wavelet
                }
            else:
                self.breaker_active = False
                self.last_trip_reason = "NONE"

        # Compute composite wavelet fragility index Psi_wavelet in [0.0, 1.0]
        phi_r = min(1.0, max(0.0, (r_wavelet - 0.50) / 0.35))
        phi_h = min(1.0, max(0.0, (0.45 - h_singularity) / 0.30))
        psi_wavelet = float(np.clip(0.50 * phi_r + 0.50 * phi_h, 0.0, 1.0))

        # 1. Critical Wavelet Noise Singularity Breaker
        if r_wavelet >= self.max_noise_ratio_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"WAVELET_NOISE_SINGULARITY: r_wavelet={r_wavelet:.3f} >= {self.max_noise_ratio_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "r_wavelet": r_wavelet,
                "h_singularity": h_singularity,
                "psi_wavelet": psi_wavelet,
                "z_wavelet": z_wavelet
            }

        if psi_wavelet >= self.critical_fragility_threshold:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"WAVELET_FRAGILITY_CRITICAL: psi_wavelet={psi_wavelet:.3f} >= {self.critical_fragility_threshold:.3f}"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "r_wavelet": r_wavelet,
                "h_singularity": h_singularity,
                "psi_wavelet": psi_wavelet,
                "z_wavelet": z_wavelet
            }

        # 2. Hölder Regularity Breakdown (Singularity Flash Crash)
        if h_singularity <= self.min_holder_threshold and r_wavelet >= 0.40:
            self.breaker_active = True
            self.breaker_tripped_at = now
            self.last_trip_reason = f"HOLDER_REGULARITY_BREAKDOWN: h_singularity={h_singularity:.2f} <= {self.min_holder_threshold:.2f} and r_wavelet={r_wavelet:.2f} >= 0.40"
            return {
                "action": "HALT_ALL",
                "circuit_breaker": True,
                "reason": self.last_trip_reason,
                "r_wavelet": r_wavelet,
                "h_singularity": h_singularity,
                "psi_wavelet": psi_wavelet,
                "z_wavelet": z_wavelet
            }

        # 3. Asymmetric Directional Overextension
        if z_wavelet >= self.z_wavelet_warning_threshold:
            return {
                "action": "BLOCK_BUY",
                "circuit_breaker": False,
                "reason": f"WAVELET_PARABOLIC_BLOWOUT: z_wavelet={z_wavelet:.2f} >= {self.z_wavelet_warning_threshold:.2f}",
                "r_wavelet": r_wavelet,
                "h_singularity": h_singularity,
                "psi_wavelet": psi_wavelet,
                "z_wavelet": z_wavelet
            }

        if z_wavelet <= -self.z_wavelet_warning_threshold:
            return {
                "action": "BLOCK_SELL",
                "circuit_breaker": False,
                "reason": f"WAVELET_LIQUIDATION_SINGULARITY: z_wavelet={z_wavelet:.2f} <= -{self.z_wavelet_warning_threshold:.2f}",
                "r_wavelet": r_wavelet,
                "h_singularity": h_singularity,
                "psi_wavelet": psi_wavelet,
                "z_wavelet": z_wavelet
            }

        return {
            "action": "ALLOW_ALL",
            "circuit_breaker": False,
            "reason": "WAVELET_EQUILIBRIUM_ACTIVE",
            "r_wavelet": r_wavelet,
            "h_singularity": h_singularity,
            "psi_wavelet": psi_wavelet,
            "z_wavelet": z_wavelet
        }
